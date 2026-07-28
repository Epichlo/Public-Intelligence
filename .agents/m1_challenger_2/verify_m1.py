"""Empirical verification harness for Milestone M1 (Scheduler OpenAI Gateway & Telemetry)."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.main import app
from scheduler.models.node import GPUInfo, Node


def generate_key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_key, public_key_pem


def generate_token(
    private_key: rsa.RSAPrivateKey, tenant_id: str | None, expired: bool = False
) -> str:
    payload = {
        "sub": "client-user",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=10)
        if not expired
        else datetime.now(UTC) - timedelta(minutes=10),
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id

    return jwt.encode(payload, private_key, algorithm="RS256")


def run_all_tests() -> None:
    print("=== STARTING EMPIRICAL VERIFICATION HARNESS ===")
    private_key, public_key_pem = generate_key_pair()

    # Configure app state
    app.state.jwt_public_key = public_key_pem
    app.state.rate_limiter = TokenBucketLimiter(capacity=5, refill_rate=0.5)

    mock_consensus = MagicMock()
    mock_consensus.is_active.return_value = True
    mock_consensus.propose = AsyncMock()
    app.state.registry.consensus_engine = mock_consensus

    app.state.registry._nodes.clear()
    app.state.registry._heartbeats.clear()
    app.state.registry._telemetry.clear()

    mock_node = Node(
        node_id="test-node-1",
        hostname="localhost",
        ip_address="127.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=8,
        ram_total_gb=32.0,
        available_models=["llama3", "mistral7b"],
    )
    app.state.registry._nodes["test-node-1"] = mock_node
    app.state.registry._telemetry["test-node-1"] = {
        "node_id": "test-node-1",
        "cpu_utilization": 18.5,
        "ram_used_bytes": 4294967296,
        "ram_total_bytes": 17179869184,
        "gpu_utilization": 30.0,
        "vram_used_bytes": 2147483648,
        "vram_total_bytes": 8589934592,
        "wan_connected": True,
    }

    client = TestClient(app)

    # 1. GET /v1/models
    print("\n--- Test 1: GET /v1/models ---")
    resp = client.get("/v1/models")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert data["object"] == "list"
    model_ids = [m["id"] for m in data["data"]]
    assert "llama3" in model_ids and "mistral7b" in model_ids
    print("PASS: GET /v1/models returned list of models correctly.")

    # 2. GET /nodes/telemetry and GET /nodes/{node_id}/telemetry
    print("\n--- Test 2: GET Telemetry Endpoints ---")
    resp_all = client.get("/nodes/telemetry")
    assert resp_all.status_code == 200
    all_telemetry = resp_all.json()
    assert "test-node-1" in all_telemetry
    assert all_telemetry["test-node-1"]["cpu_utilization"] == 18.5
    print("PASS: GET /nodes/telemetry returned all node telemetry.")

    resp_single = client.get("/nodes/test-node-1/telemetry")
    assert resp_single.status_code == 200
    assert resp_single.json()["node_id"] == "test-node-1"
    print("PASS: GET /nodes/test-node-1/telemetry returned single node telemetry.")

    resp_404 = client.get("/nodes/nonexistent-node/telemetry")
    assert resp_404.status_code == 404
    assert "Telemetry not found" in resp_404.json()["detail"]
    print("PASS: GET /nodes/nonexistent-node/telemetry returned 404 with proper error detail.")

    # 3. Unauthorized Token Rejection (401)
    print("\n--- Test 3: Unauthorized Token Rejection (401) ---")
    resp_no_header = client.post("/v1/chat/completions", json={"model": "llama3", "messages": []})
    assert resp_no_header.status_code in (401, 422), f"Got {resp_no_header.status_code}"
    print(f"PASS: Missing auth header rejected with {resp_no_header.status_code}.")

    resp_bad = client.post(
        "/v1/chat/completions",
        json={"model": "llama3", "messages": []},
        headers={"Authorization": "Bearer bad.jwt.token"},
    )
    assert resp_bad.status_code == 401
    assert "JWT signature verification failed" in resp_bad.json()["detail"]
    print("PASS: Malformed JWT token rejected with 401 and descriptive error detail.")

    token_no_tenant = generate_token(private_key, tenant_id=None)
    resp_no_tenant = client.post(
        "/v1/chat/completions",
        json={"model": "llama3", "messages": []},
        headers={"Authorization": f"Bearer {token_no_tenant}"},
    )
    assert resp_no_tenant.status_code == 401
    assert "Missing 'tenant_id'" in resp_no_tenant.json()["detail"]
    print("PASS: Token missing tenant_id claim rejected with 401.")

    token_expired = generate_token(private_key, tenant_id="tenant-1", expired=True)
    resp_expired = client.post(
        "/v1/chat/completions",
        json={"model": "llama3", "messages": []},
        headers={"Authorization": f"Bearer {token_expired}"},
    )
    assert resp_expired.status_code == 401
    print("PASS: Expired JWT token rejected with 401.")

    # 4. Authorized Non-Streaming Completion
    print("\n--- Test 4: Authorized Non-Streaming Chat Completion ---")
    token_valid = generate_token(private_key, tenant_id="tenant-emp-1")
    mock_node_resp = httpx.Response(
        status_code=200,
        json={"model": "llama3", "response": "Empirical response from mock LLM"},
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_resp
        resp_cmpl = client.post(
            "/v1/chat/completions",
            json={
                "model": "llama3",
                "messages": [
                    {"role": "system", "content": "Be concise."},
                    {"role": "user", "content": "What is 2+2?"},
                ],
                "stream": False,
            },
            headers={"Authorization": f"Bearer {token_valid}"},
        )
    assert resp_cmpl.status_code == 200
    cmpl_data = resp_cmpl.json()
    assert cmpl_data["object"] == "chat.completion"
    assert cmpl_data["choices"][0]["message"]["content"] == "Empirical response from mock LLM"
    assert cmpl_data["choices"][0]["message"]["role"] == "assistant"
    assert cmpl_data["usage"]["total_tokens"] > 0
    print("PASS: Authorized non-streaming chat completion returned valid OpenAI response payload.")

    # 5. Authorized Streaming Completion (SSE)
    print("\n--- Test 5: Authorized Streaming Chat Completion (SSE) ---")
    token_valid_stream = generate_token(private_key, tenant_id="tenant-emp-2")
    stream_chunks = [
        'data: {"response": "Tokens "}\n',
        'data: {"response": "streaming "}\n',
        'data: {"response": "live"}\n',
    ]

    async def mock_stream_lines():
        for line in stream_chunks:
            yield line

    mock_resp_obj = MagicMock()
    mock_resp_obj.status_code = 200
    mock_resp_obj.aiter_lines = mock_stream_lines

    class StreamCtx:
        async def __aenter__(self):
            return mock_resp_obj

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch.object(httpx.AsyncClient, "stream", return_value=StreamCtx()):
        resp_stream = client.post(
            "/v1/chat/completions",
            json={
                "model": "llama3",
                "messages": [{"role": "user", "content": "Stream me a response"}],
                "stream": True,
            },
            headers={"Authorization": f"Bearer {token_valid_stream}"},
        )

    assert resp_stream.status_code == 200
    assert "text/event-stream" in resp_stream.headers["content-type"]
    stream_text = resp_stream.text
    assert "chat.completion.chunk" in stream_text
    assert '"content":"Tokens "' in stream_text
    assert '"content":"streaming "' in stream_text
    assert '"content":"live"' in stream_text
    assert "data: [DONE]" in stream_text
    print("PASS: Streaming chat completion returned valid SSE chunks terminating with data: [DONE].")

    # 6. Multi-Tenant Rate Limiting (429)
    print("\n--- Test 6: Multi-Tenant Rate Limiting (429) ---")
    token_rate = generate_token(private_key, tenant_id="tenant-quota-test")
    app.state.rate_limiter = TokenBucketLimiter(capacity=3, refill_rate=0.01)

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_resp
        for idx in range(3):
            r = client.post(
                "/v1/chat/completions",
                json={"model": "llama3", "messages": [{"role": "user", "content": f"Req {idx}"}]},
                headers={"Authorization": f"Bearer {token_rate}"},
            )
            assert r.status_code == 200

        r_429 = client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "Exceeded"}]},
            headers={"Authorization": f"Bearer {token_rate}"},
        )
        assert r_429.status_code == 429
        assert "Rate limit exceeded" in r_429.json()["detail"]
    print("PASS: 4th request when capacity is 3 returned 429 Too Many Requests with clear detail.")

    # 7. Model Not Available (503)
    print("\n--- Test 7: Model Not Available (503) ---")
    token_503 = generate_token(private_key, tenant_id="tenant-503")
    resp_503 = client.post(
        "/v1/chat/completions",
        json={"model": "nonexistent-model-xyz", "messages": [{"role": "user", "content": "test"}]},
        headers={"Authorization": f"Bearer {token_503}"},
    )
    assert resp_503.status_code == 503
    assert "No suitable compute node available" in resp_503.json()["detail"]
    print("PASS: Requesting unavailable model returned HTTP 503 Service Unavailable.")

    # 8. CORS Preflight Verification
    print("\n--- Test 8: CORS Header Verification ---")
    cors_resp = client.options(
        "/v1/chat/completions",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    print(f"CORS Headers: {cors_resp.headers}")
    assert cors_resp.status_code == 200
    assert cors_resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    print("PASS: CORS preflight request returned Access-Control-Allow-Origin matching origin.")

    print("\n=== ALL EMPIRICAL FUNCTIONAL TESTS PASSED PERFECTLY ===")


if __name__ == "__main__":
    run_all_tests()
