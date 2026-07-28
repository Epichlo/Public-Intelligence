"""Empirical Stress Test Harness for OpenAI API Gateway and Task Ingress Endpoints.
Executed by challenger_1.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import json
import time
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
from fastapi.testclient import TestClient

from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.main import app as scheduler_app
from scheduler.models.node import GPUInfo, Node as SchedulerNode
from scheduler.models.openai import ChatCompletionChunk


def generate_rsa_key_pair() -> tuple[rsa.RSAPrivateKey, str]:
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


def generate_jwt(
    private_key: rsa.RSAPrivateKey,
    tenant_id: str | None = "stress-tenant",
    expired: bool = False,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "stress-test-user",
        "iat": now,
        "exp": now - timedelta(minutes=10) if expired else now + timedelta(minutes=10),
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, private_key, algorithm="RS256")


def setup_scheduler_app(public_key_pem: str) -> TestClient:
    scheduler_app.state.jwt_public_key = public_key_pem
    scheduler_app.state.rate_limiter = TokenBucketLimiter(capacity=5, refill_rate=0.5)

    mock_consensus = MagicMock()
    mock_consensus.is_active.return_value = True
    mock_consensus.propose = AsyncMock()
    scheduler_app.state.registry.consensus_engine = mock_consensus

    mock_scheduling_engine = AsyncMock()
    mock_scheduling_engine.schedule_task.return_value = ("tx_hash_123", "node-stress-1")
    scheduler_app.state.scheduling_engine = mock_scheduling_engine

    scheduler_app.state.registry._nodes.clear()
    scheduler_app.state.registry._heartbeats.clear()
    scheduler_app.state.registry._telemetry.clear()

    test_node = SchedulerNode(
        node_id="node-stress-1",
        hostname="localhost",
        ip_address="127.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3", "mistral-7b"],
    )
    scheduler_app.state.registry._nodes["node-stress-1"] = test_node

    return TestClient(scheduler_app)


# -----------------------------------------------------------------------------
# Test 1: SSE Token Streaming Formatting & Protocol Verification
# -----------------------------------------------------------------------------


def test_sse_streaming_chunk_formatting() -> dict[str, Any]:
    print("\n--- Running Test 1: SSE Streaming Chunk Formatting Stress & Protocol Oracle ---")
    private_key, public_key_pem = generate_rsa_key_pair()
    client = setup_scheduler_app(public_key_pem)
    token = generate_jwt(private_key, tenant_id="sse-tenant")

    payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Format test"}],
        "stream": True,
    }

    raw_tokens = [
        '{"response": "Hello"}',
        '{"response": " world!"}',
        '{"response": " \\n\\tSpecial \\"JSON\\" symbols test"}',
        '{"text": " Suffix token"}',
    ]

    async def mock_node_stream() -> AsyncGenerator[str, None]:
        for t in raw_tokens:
            yield f"data: {t}\n\n"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = mock_node_stream

    class MockStreamCtx:
        async def __aenter__(self) -> MagicMock:
            return mock_resp

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    with patch.object(httpx.AsyncClient, "stream", return_value=MockStreamCtx()):
        response = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert "text/event-stream" in response.headers.get("content-type", ""), "Content-Type header mismatch"

    raw_body = response.text
    # SSE blocks are separated by double newline \n\n
    sse_blocks = [b.strip() for b in raw_body.split("\n\n") if b.strip()]

    assert len(sse_blocks) >= 3, f"Expected at least 3 SSE blocks, got {len(sse_blocks)}"
    
    # Final block must be data: [DONE]
    assert sse_blocks[-1] == "data: [DONE]", f"Final SSE block was not 'data: [DONE]', got: {sse_blocks[-1]}"

    # Validate each non-DONE block starts with data: and parses to ChatCompletionChunk
    chunks: list[ChatCompletionChunk] = []
    for i, block in enumerate(sse_blocks[:-1]):
        assert block.startswith("data: "), f"Block {i} does not start with 'data: ': {block}"
        json_str = block[6:]
        chunk_data = json.loads(json_str)
        chunk_obj = ChatCompletionChunk.model_validate(chunk_data)
        chunks.append(chunk_obj)
        assert chunk_obj.object == "chat.completion.chunk"
        assert chunk_obj.id.startswith("chatcmpl-")
        assert len(chunk_obj.choices) == 1
        assert chunk_obj.choices[0].index == 0

    # First chunk role initialization check
    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[0].choices[0].delta.content == ""

    # Middle chunks token content check
    assert chunks[1].choices[0].delta.content == "Hello"
    assert chunks[2].choices[0].delta.content == " world!"
    assert chunks[3].choices[0].delta.content == ' \n\tSpecial "JSON" symbols test'
    assert chunks[4].choices[0].delta.content == " Suffix token"

    # Penultimate chunk finish_reason check
    assert chunks[-1].choices[0].finish_reason == "stop"

    print("✅ Test 1 Passed: SSE Streaming Protocol and Chunk Schema strictly validated!")
    return {"name": "SSE Streaming Formatting", "status": "PASS", "details": f"{len(chunks)} chunks verified"}


# -----------------------------------------------------------------------------
# Test 2: Rate Limiting (HTTP 429) & Burst Capacity Verification
# -----------------------------------------------------------------------------


def test_rate_limiting_capacity_and_isolation() -> dict[str, Any]:
    print("\n--- Running Test 2: Multi-Tenant TokenBucket Rate Limiting (HTTP 429) ---")
    private_key, public_key_pem = generate_rsa_key_pair()
    client = setup_scheduler_app(public_key_pem)

    token_tenant_a = generate_jwt(private_key, tenant_id="tenant-rate-A")
    token_tenant_b = generate_jwt(private_key, tenant_id="tenant-rate-B")

    payload_openai = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Rate check"}],
        "stream": False,
    }

    mock_node_resp = httpx.Response(200, json={"model": "llama3", "response": "OK"})

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_resp

        # 1. Tenant A sends 5 requests -> All 5 must succeed (HTTP 200)
        for i in range(5):
            res = client.post(
                "/v1/chat/completions",
                json=payload_openai,
                headers={"Authorization": f"Bearer {token_tenant_a}"},
            )
            assert res.status_code == 200, f"Tenant A Request {i+1} failed with status {res.status_code}"

        # 2. Tenant A sends 6th request -> Must trigger HTTP 429
        res_429_openai = client.post(
            "/v1/chat/completions",
            json=payload_openai,
            headers={"Authorization": f"Bearer {token_tenant_a}"},
        )
        assert res_429_openai.status_code == 429, f"Expected 429, got {res_429_openai.status_code}"
        assert res_429_openai.json()["detail"] == "Rate limit exceeded. Multi-tenant quota exhausted."

        # 3. Tenant B sends request -> Must succeed (HTTP 200), showing multi-tenant isolation
        res_tenant_b = client.post(
            "/v1/chat/completions",
            json=payload_openai,
            headers={"Authorization": f"Bearer {token_tenant_b}"},
        )
        assert res_tenant_b.status_code == 200, "Tenant B failed despite having fresh quota"

        # 4. Check Task Ingress endpoint (/api/v1/tasks/submit) rate limiting as well
        payload_ingress = {
            "task_id": "task-stress-1",
            "action": "infer",
            "data": {"model_name": "llama3"},
        }

        # Tenant B sends 4 more requests to ingress -> All 4 succeed (reaching 5 total)
        for i in range(4):
            r = client.post(
                "/api/v1/tasks/submit",
                json={"task_id": f"task-stress-{i+2}", "action": "infer", "data": {"model_name": "llama3"}},
                headers={"Authorization": f"Bearer {token_tenant_b}"},
            )
            assert r.status_code == 200

        # Tenant B sends 6th request to ingress -> Triggers HTTP 429
        res_429_ingress = client.post(
            "/api/v1/tasks/submit",
            json={"task_id": "task-stress-overflow", "action": "infer", "data": {"model_name": "llama3"}},
            headers={"Authorization": f"Bearer {token_tenant_b}"},
        )
        assert res_429_ingress.status_code == 429
        assert res_429_ingress.json()["detail"] == "Rate limit exceeded. Multi-tenant quota exhausted."

    print("✅ Test 2 Passed: HTTP 429 Capacity limits & Tenant Isolation verified for Gateway & Ingress!")
    return {"name": "Rate Limiting Capacity & Isolation", "status": "PASS", "details": "Burst 5 capacity & 429 confirmed"}


# -----------------------------------------------------------------------------
# Test 3: RS256 JWT Auth Rejections & Edge Case Mining
# -----------------------------------------------------------------------------


def test_jwt_auth_rejections() -> dict[str, Any]:
    print("\n--- Running Test 3: RS256 JWT Auth Rejection Edge Cases ---")
    private_key, public_key_pem = generate_rsa_key_pair()
    other_private_key, _ = generate_rsa_key_pair()
    client = setup_scheduler_app(public_key_pem)

    payload = {"model": "llama3", "messages": [{"role": "user", "content": "Auth test"}]}
    ingress_payload = {"task_id": "task-auth-1", "action": "infer", "data": {}}

    endpoints = [
        ("/v1/chat/completions", payload),
        ("/api/v1/tasks/submit", ingress_payload),
    ]

    for path, body in endpoints:
        # Case A: Missing Authorization Header
        res_no_hdr = client.post(path, json=body)
        assert res_no_hdr.status_code in (401, 422), f"{path}: Missing header returned {res_no_hdr.status_code}"

        # Case B: Malformed Header Prefix (e.g. Basic instead of Bearer)
        res_bad_prefix = client.post(path, json=body, headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert res_bad_prefix.status_code == 401, f"{path}: Bad prefix returned {res_bad_prefix.status_code}"
        assert "Invalid Authorization header format" in res_bad_prefix.json()["detail"]

        # Case C: Token signed with untrusted RSA key
        untrusted_jwt = generate_jwt(other_private_key, tenant_id="tenant-untrusted")
        res_untrusted = client.post(path, json=body, headers={"Authorization": f"Bearer {untrusted_jwt}"})
        assert res_untrusted.status_code == 401, f"{path}: Untrusted key returned {res_untrusted.status_code}"
        assert "JWT signature verification failed" in res_untrusted.json()["detail"]

        # Case D: Expired Token
        expired_jwt = generate_jwt(private_key, tenant_id="tenant-expired", expired=True)
        res_expired = client.post(path, json=body, headers={"Authorization": f"Bearer {expired_jwt}"})
        assert res_expired.status_code == 401, f"{path}: Expired token returned {res_expired.status_code}"
        assert "JWT signature verification failed" in res_expired.json()["detail"]

        # Case E: Missing tenant_id Claim
        no_tenant_jwt = generate_jwt(private_key, tenant_id=None)
        res_no_tenant = client.post(path, json=body, headers={"Authorization": f"Bearer {no_tenant_jwt}"})
        assert res_no_tenant.status_code == 401, f"{path}: Missing tenant_id returned {res_no_tenant.status_code}"
        assert "Missing 'tenant_id'" in res_no_tenant.json()["detail"]

        # Case F: Corrupted JWT string
        res_corrupt = client.post(path, json=body, headers={"Authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.corrupt.signature"})
        assert res_corrupt.status_code == 401, f"{path}: Corrupt JWT returned {res_corrupt.status_code}"

    print("✅ Test 3 Passed: All RS256 JWT auth rejections verified across all ingress endpoints!")
    return {"name": "RS256 JWT Auth Rejections", "status": "PASS", "details": "All 6 auth rejection vectors verified"}


def main():
    print("=================================================================")
    print("  EMPIRICAL CHALLENGER STRESS HARNESS — OpenAI Gateway & Ingress ")
    print("=================================================================")
    results = []
    results.append(test_sse_streaming_chunk_formatting())
    results.append(test_rate_limiting_capacity_and_isolation())
    results.append(test_jwt_auth_rejections())

    print("\n-----------------------------------------------------------------")
    print(" SUMMARY OF STRESS TEST RESULTS:")
    all_passed = True
    for r in results:
        status_symbol = "🟢" if r["status"] == "PASS" else "🔴"
        print(f" {status_symbol} {r['name']}: {r['status']} ({r['details']})")
        if r["status"] != "PASS":
            all_passed = False
    print("-----------------------------------------------------------------")
    if all_passed:
        print("VERDICT: APPROVE")
    else:
        print("VERDICT: REJECT")


if __name__ == "__main__":
    main()
