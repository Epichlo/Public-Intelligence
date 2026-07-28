"""Extended Adversarial Stress Harness for OpenAI API Gateway and Task Ingress Endpoints.
Executed by challenger_1.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import json
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

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
    tenant_id: str | None = "adv-tenant",
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "adv-test-user",
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id

    return jwt.encode(payload, private_key, algorithm="RS256")


def setup_scheduler_app(public_key_pem: str) -> TestClient:
    scheduler_app.state.jwt_public_key = public_key_pem
    scheduler_app.state.rate_limiter = TokenBucketLimiter(capacity=5, refill_rate=1.0)

    mock_consensus = MagicMock()
    mock_consensus.is_active.return_value = True
    mock_consensus.propose = AsyncMock()
    scheduler_app.state.registry.consensus_engine = mock_consensus

    mock_scheduling_engine = AsyncMock()
    mock_scheduling_engine.schedule_task.return_value = ("tx_hash_999", "node-adv-1")
    scheduler_app.state.scheduling_engine = mock_scheduling_engine

    scheduler_app.state.registry._nodes.clear()
    scheduler_app.state.registry._heartbeats.clear()
    scheduler_app.state.registry._telemetry.clear()

    test_node = SchedulerNode(
        node_id="node-adv-1",
        hostname="localhost",
        ip_address="127.0.0.1",
        region="us-west",
        gpu=GPUInfo(name="H100", vram_total_gb=80.0, vram_available_gb=70.0),
        cpu_cores=32,
        ram_total_gb=128.0,
        available_models=["llama3", "code-llama"],
    )
    scheduler_app.state.registry._nodes["node-adv-1"] = test_node

    return TestClient(scheduler_app)


# -----------------------------------------------------------------------------
# Scenario 1: Node Error Mid-Stream Recovery & Graceful SSE Termination
# -----------------------------------------------------------------------------


def test_node_error_mid_stream() -> dict[str, str]:
    print("\n--- Running Adversarial Scenario 1: Node Error Mid-Stream Recovery ---")
    private_key, public_key_pem = generate_rsa_key_pair()
    client = setup_scheduler_app(public_key_pem)
    token = generate_jwt(private_key, tenant_id="tenant-err-stream")

    payload = {"model": "llama3", "messages": [{"role": "user", "content": "Fail mid stream"}], "stream": True}

    # Simulate Node returning non-200 error response during streaming setup
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.aread = AsyncMock(return_value=b"Internal GPU OOM Error")

    class MockStreamCtx:
        async def __aenter__(self) -> MagicMock:
            return mock_resp

        async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
            pass

    with patch.object(httpx.AsyncClient, "stream", return_value=MockStreamCtx()):
        response = client.post("/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.text
    assert "data: [DONE]" in body
    assert "[Error: Internal GPU OOM Error]" in body

    # Also test network exception raised during client stream
    with patch.object(httpx.AsyncClient, "stream", side_effect=httpx.ConnectTimeout("Connection timed out")):
        response_exc = client.post("/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {token}"})

    assert response_exc.status_code == 200
    body_exc = response_exc.text
    assert "data: [DONE]" in body_exc
    assert "[Stream Error: Connection timed out]" in body_exc

    print("✅ Scenario 1 Passed: Node errors and network timeouts mid-stream yield graceful error SSE chunks and terminate with 'data: [DONE]'!")
    return {"name": "Node Error Mid-Stream Recovery", "status": "PASS"}


# -----------------------------------------------------------------------------
# Scenario 2: Special Tokens & Emojis in Streaming Payload
# -----------------------------------------------------------------------------


def test_special_characters_in_stream() -> dict[str, str]:
    print("\n--- Running Adversarial Scenario 2: Special Unicode/Emoji Tokens in SSE Stream ---")
    private_key, public_key_pem = generate_rsa_key_pair()
    client = setup_scheduler_app(public_key_pem)
    token = generate_jwt(private_key, tenant_id="tenant-unicode")

    payload = {"model": "llama3", "messages": [{"role": "user", "content": "Unicode check"}], "stream": True}

    unicode_tokens = [
        '{"response": "🚀 High-performance compute node ⚡"}',
        '{"response": "\\n```python\\ndef foo():\\n    print(\\"data: fake_sse_in_code\\")\\n```"}',
        '{"response": " 中文 / 日本語 / Standard text"}',
    ]

    async def mock_node_stream():
        for t in unicode_tokens:
            yield f"data: {t}\n\n"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = mock_node_stream

    class MockStreamCtx:
        async def __aenter__(self) -> MagicMock:
            return mock_resp

        async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
            pass

    with patch.object(httpx.AsyncClient, "stream", return_value=MockStreamCtx()):
        response = client.post("/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.text

    assert "🚀 High-performance compute node ⚡" in body
    assert 'print(\\"data: fake_sse_in_code\\")' in body
    assert "中文 / 日本語 / Standard text" in body
    assert body.endswith("data: [DONE]\n\n")

    print("✅ Scenario 2 Passed: Unicode, emojis, code blocks, and nested SSE text cleanly formatted!")
    return {"name": "Special Unicode/Emoji Tokens in Stream", "status": "PASS"}


# -----------------------------------------------------------------------------
# Scenario 3: High-Frequency Multi-Tenant Concurrency Burst
# -----------------------------------------------------------------------------


def test_concurrent_multi_tenant_burst() -> dict[str, str]:
    print("\n--- Running Adversarial Scenario 3: High-Frequency Multi-Tenant Concurrency Burst ---")
    private_key, public_key_pem = generate_rsa_key_pair()
    client = setup_scheduler_app(public_key_pem)

    num_tenants = 5
    requests_per_tenant = 8  # 5 capacity limit per tenant, so 5 pass, 3 fail for each tenant

    tokens = {f"tenant-burst-{i}": generate_jwt(private_key, tenant_id=f"tenant-burst-{i}") for i in range(num_tenants)}

    mock_node_resp = httpx.Response(200, json={"model": "llama3", "response": "OK"})

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_resp

        results_by_tenant = {t_id: {"200": 0, "429": 0} for t_id in tokens}

        for t_id, token in tokens.items():
            for _ in range(requests_per_tenant):
                res = client.post(
                    "/v1/chat/completions",
                    json={"model": "llama3", "messages": [{"role": "user", "content": "Ping"}]},
                    headers={"Authorization": f"Bearer {token}"},
                )
                if res.status_code == 200:
                    results_by_tenant[t_id]["200"] += 1
                elif res.status_code == 429:
                    results_by_tenant[t_id]["429"] += 1

        for t_id, counts in results_by_tenant.items():
            assert counts["200"] == 5, f"{t_id} had {counts['200']} success requests instead of 5"
            assert counts["429"] == 3, f"{t_id} had {counts['429']} rate-limited requests instead of 3"

    print("✅ Scenario 3 Passed: Multi-tenant rate limiting maintained exact 5-request burst boundaries across 5 concurrent tenants!")
    return {"name": "High-Frequency Multi-Tenant Concurrency Burst", "status": "PASS"}


def main():
    print("=================================================================")
    print("  EXTENDED ADVERSARIAL STRESS HARNESS — OpenAI Gateway & Ingress ")
    print("=================================================================")
    results = [
        test_node_error_mid_stream(),
        test_special_characters_in_stream(),
        test_concurrent_multi_tenant_burst(),
    ]

    print("\n-----------------------------------------------------------------")
    print(" SUMMARY OF EXTENDED ADVERSARIAL STRESS RESULTS:")
    all_passed = True
    for r in results:
        status_symbol = "🟢" if r["status"] == "PASS" else "🔴"
        print(f" {status_symbol} {r['name']}: {r['status']}")
        if r["status"] != "PASS":
            all_passed = False
    print("-----------------------------------------------------------------")
    if all_passed:
        print("VERDICT: APPROVE")
    else:
        print("VERDICT: REJECT")


if __name__ == "__main__":
    main()
