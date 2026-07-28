"""Empirical Verification & Stress Test Harness for Milestone M1 (OpenAI REST Gateway)."""

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


def run_empirical_tests():
    print("=== STARTING EMPIRICAL VERIFICATION HARNESS FOR M1 ===")
    
    # 1. Setup RSA Keypair
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    app.state.jwt_public_key = public_key_pem

    # 2. Reset app state
    app.state.rate_limiter = TokenBucketLimiter(capacity=5, refill_rate=0.5)
    mock_consensus = MagicMock()
    mock_consensus.is_active.return_value = True
    mock_consensus.propose = AsyncMock()
    app.state.registry.consensus_engine = mock_consensus

    app.state.registry._nodes.clear()
    app.state.registry._heartbeats.clear()
    app.state.registry._telemetry.clear()

    mock_node = Node(
        node_id="empirical-node-1",
        hostname="localhost",
        ip_address="127.0.0.1",
        region="us-west",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3", "mistral-7b"],
    )
    app.state.registry._nodes["empirical-node-1"] = mock_node

    def generate_token(tenant_id="tenant-emp", expired=False):
        payload = {
            "sub": "empirical-user",
            "tenant_id": tenant_id,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=10) if not expired else datetime.now(UTC) - timedelta(minutes=10),
        }
        return jwt.encode(payload, private_key, algorithm="RS256")

    client = TestClient(app)

    # --- TEST 1: Non-streaming JSON OpenAI Compliance ---
    print("\n--- Test 1: Non-streaming POST /v1/chat/completions ---")
    token = generate_token("tenant-1")
    req_body = {
        "model": "llama3",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 2+2?"}
        ],
        "stream": False,
        "temperature": 0.7
    }

    mock_node_resp = httpx.Response(
        status_code=200,
        json={"model": "llama3", "response": "2+2 is 4."}
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_resp
        resp = client.post(
            "/v1/chat/completions",
            json=req_body,
            headers={"Authorization": f"Bearer {token}"}
        )

    print(f"Status Code: {resp.status_code}")
    print(f"Headers: {resp.headers.get('content-type')}")
    data = resp.json()
    print(f"Response JSON: {json.dumps(data, indent=2)}")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert data["object"] == "chat.completion", f"Expected object 'chat.completion', got {data.get('object')}"
    assert data["model"] == "llama3"
    assert data["id"].startswith("chatcmpl-")
    assert isinstance(data["created"], int)
    assert len(data["choices"]) == 1
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["message"]["content"] == "2+2 is 4."
    assert data["choices"][0]["finish_reason"] == "stop"
    assert "usage" in data
    assert data["usage"]["prompt_tokens"] > 0
    assert data["usage"]["completion_tokens"] > 0
    assert data["usage"]["total_tokens"] == data["usage"]["prompt_tokens"] + data["usage"]["completion_tokens"]
    print(">>> Test 1 PASSED: Non-streaming response is 100% OpenAI compliant.")

    # --- TEST 2: Streaming SSE Chunk Formatting ---
    print("\n--- Test 2: Streaming SSE POST /v1/chat/completions ---")
    token = generate_token("tenant-2")
    req_stream_body = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Hello stream!"}],
        "stream": True
    }

    stream_tokens = [
        'data: {"response": "Hello"}\n',
        'data: {"response": " world"}\n',
        'data: {"response": "!"}\n'
    ]

    async def mock_aiter_lines():
        for line in stream_tokens:
            yield line

    mock_stream_resp = MagicMock()
    mock_stream_resp.status_code = 200
    mock_stream_resp.aiter_lines = mock_aiter_lines

    class MockStreamContext:
        async def __aenter__(self):
            return mock_stream_resp
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch.object(httpx.AsyncClient, "stream", return_value=MockStreamContext()):
        resp_stream = client.post(
            "/v1/chat/completions",
            json=req_stream_body,
            headers={"Authorization": f"Bearer {token}"}
        )

    print(f"Status Code: {resp_stream.status_code}")
    print(f"Content-Type: {resp_stream.headers.get('content-type')}")
    body = resp_stream.text
    print("RAW STREAM BODY:")
    print(body)

    assert resp_stream.status_code == 200
    assert "text/event-stream" in resp_stream.headers.get("content-type", "")

    lines = [line.strip() for line in body.strip().split("\n") if line.strip()]
    sse_events = [line for line in lines if line.startswith("data: ")]
    print(f"Parsed SSE data lines count: {len(sse_events)}")

    # Verify first SSE line has role="assistant"
    first_chunk = json.loads(sse_events[0][6:])
    assert first_chunk["object"] == "chat.completion.chunk"
    assert first_chunk["choices"][0]["delta"]["role"] == "assistant"

    # Verify token deltas
    chunk_2 = json.loads(sse_events[1][6:])
    assert chunk_2["choices"][0]["delta"]["content"] == "Hello"

    chunk_3 = json.loads(sse_events[2][6:])
    assert chunk_3["choices"][0]["delta"]["content"] == " world"

    chunk_4 = json.loads(sse_events[3][6:])
    assert chunk_4["choices"][0]["delta"]["content"] == "!"

    # Verify stop chunk
    stop_chunk = json.loads(sse_events[4][6:])
    assert stop_chunk["choices"][0]["finish_reason"] == "stop"

    # Verify terminating marker
    assert sse_events[5] == "data: [DONE]"

    print(">>> Test 2 PASSED: Streaming SSE formatting is 100% OpenAI compliant.")

    # --- TEST 3: Rate Limit Exhaustion (HTTP 429) ---
    print("\n--- Test 3: Multi-Tenant Rate Limiting (HTTP 429) ---")
    token_rl = generate_token("tenant-limited")

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_resp

        # Exhaust capacity (5 tokens)
        for i in range(5):
            r = client.post(
                "/v1/chat/completions",
                json=req_body,
                headers={"Authorization": f"Bearer {token_rl}"}
            )
            assert r.status_code == 200, f"Request {i+1} failed with status {r.status_code}"

        # 6th request must trip rate limiter
        r_429 = client.post(
            "/v1/chat/completions",
            json=req_body,
            headers={"Authorization": f"Bearer {token_rl}"}
        )

    print(f"6th Request Status: {r_429.status_code}")
    print(f"6th Request Body: {r_429.json()}")
    assert r_429.status_code == 429
    assert r_429.json()["detail"] == "Rate limit exceeded. Multi-tenant quota exhausted."
    print(">>> Test 3 PASSED: Rate limit exhaustion correctly returns HTTP 429.")

    # --- TEST 4: Telemetry Endpoints ---
    print("\n--- Test 4: Node Telemetry Endpoints ---")
    app.state.registry._telemetry["empirical-node-1"] = {
        "node_id": "empirical-node-1",
        "cpu_utilization": 30.0,
        "ram_used_bytes": 16000000000,
        "ram_total_bytes": 64000000000,
        "gpu_utilization": 50.0,
        "vram_used_bytes": 10000000000,
        "vram_total_bytes": 24000000000,
        "wan_connected": True,
    }

    res_all_telemetry = client.get("/nodes/telemetry")
    assert res_all_telemetry.status_code == 200
    assert "empirical-node-1" in res_all_telemetry.json()

    res_single_telemetry = client.get("/nodes/empirical-node-1/telemetry")
    assert res_single_telemetry.status_code == 200
    assert res_single_telemetry.json()["cpu_utilization"] == 30.0

    print(">>> Test 4 PASSED: Telemetry endpoints work as expected.")

    print("\n=== ALL EMPIRICAL GATEWAY VERIFICATION TESTS PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    run_empirical_tests()
