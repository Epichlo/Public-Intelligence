"""Integration tests for OpenAI REST API Gateway and Telemetry Endpoints."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.main import app
from scheduler.models.node import GPUInfo, Node


@pytest.fixture(scope="module")
def key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    """Generate an RSA key pair for signing and verifying JWTs in tests."""
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


@pytest.fixture(autouse=True)
def setup_test_app(key_pair: tuple[rsa.RSAPrivateKey, str]) -> MagicMock:
    """Configure FastAPI app state with test keys, mock consensus engine, and mock node."""
    _, public_key_pem = key_pair
    app.state.jwt_public_key = public_key_pem

    # Reset rate limiter
    app.state.rate_limiter = TokenBucketLimiter(capacity=5, refill_rate=0.5)

    # Set up mock consensus engine
    mock_consensus = MagicMock()
    mock_consensus.is_active.return_value = True
    mock_consensus.propose = AsyncMock()
    app.state.registry.consensus_engine = mock_consensus

    # Reset registry state
    app.state.registry._nodes.clear()
    app.state.registry._heartbeats.clear()
    app.state.registry._telemetry.clear()

    # Register test node with model "llama3"
    mock_node = Node(
        node_id="test-node",
        hostname="localhost",
        ip_address="127.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=8,
        ram_total_gb=32.0,
        available_models=["llama3"],
    )
    app.state.registry._nodes["test-node"] = mock_node

    return mock_consensus


def generate_token(
    private_key: rsa.RSAPrivateKey, tenant_id: str | None, expired: bool = False
) -> str:
    """Generate a signed JWT for testing."""
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


def test_openai_chat_completion_non_streaming(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Verify non-streaming POST /v1/chat/completions translates request and returns valid JSON."""
    private_key, _ = key_pair
    token = generate_token(private_key, tenant_id="tenant-A")
    client = TestClient(app)

    request_payload = {
        "model": "llama3",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
        ],
        "stream": False,
        "temperature": 0.7,
    }

    mock_node_response = httpx.Response(
        status_code=200,
        json={"model": "llama3", "response": "Hello there! How can I assist you today?"},
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_response

        response = client.post(
            "/v1/chat/completions",
            json=request_payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    res_json = response.json()
    assert res_json["object"] == "chat.completion"
    assert res_json["model"] == "llama3"
    assert res_json["choices"][0]["message"]["role"] == "assistant"
    assert (
        res_json["choices"][0]["message"]["content"] == "Hello there! How can I assist you today?"
    )
    assert res_json["usage"]["prompt_tokens"] > 0
    assert res_json["usage"]["completion_tokens"] > 0
    assert res_json["usage"]["total_tokens"] > 0


def test_openai_chat_completion_streaming(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Verify streaming POST /v1/chat/completions yields OpenAI SSE chunks."""
    private_key, _ = key_pair
    token = generate_token(private_key, tenant_id="tenant-B")
    client = TestClient(app)

    request_payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Count to 3"}],
        "stream": True,
    }

    stream_lines = [
        'data: {"response": "1, "}\n',
        'data: {"response": "2, "}\n',
        'data: {"response": "3"}\n',
    ]

    async def mock_aiter_lines() -> AsyncGenerator[str, None]:
        for line in stream_lines:
            yield line

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.aiter_lines = mock_aiter_lines

    class MockStreamContext:
        async def __aenter__(self):
            return mock_response

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch.object(httpx.AsyncClient, "stream", return_value=MockStreamContext()):
        response = client.post(
            "/v1/chat/completions",
            json=request_payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body_text = response.text

    assert "chat.completion.chunk" in body_text
    assert '"role":"assistant"' in body_text
    assert '"content":"1, "' in body_text
    assert '"content":"2, "' in body_text
    assert '"content":"3"' in body_text
    assert "data: [DONE]" in body_text


def test_openai_chat_completion_unauthorized() -> None:
    """Verify unauthorized or missing JWT returns HTTP 401."""
    client = TestClient(app)
    request_payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Hi"}],
    }

    # 1. No auth header
    resp_no_header = client.post("/v1/chat/completions", json=request_payload)
    assert resp_no_header.status_code in (401, 422)

    # 2. Malformed token
    resp_invalid = client.post(
        "/v1/chat/completions",
        json=request_payload,
        headers={"Authorization": "Bearer badtoken"},
    )
    assert resp_invalid.status_code == 401


def test_openai_chat_completion_rate_limit(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Verify multi-tenant rate limiting exhausts quota and returns 429."""
    private_key, _ = key_pair
    token = generate_token(private_key, tenant_id="rate-limit-tenant")
    client = TestClient(app)

    request_payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Ping"}],
        "stream": False,
    }

    mock_node_response = httpx.Response(
        status_code=200,
        json={"model": "llama3", "response": "Pong"},
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_response

        # Exhaust capacity (5 requests)
        for i in range(5):
            res = client.post(
                "/v1/chat/completions",
                json=request_payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 200, f"Request {i + 1} failed"

        # 6th request should fail with 429
        res_429 = client.post(
            "/v1/chat/completions",
            json=request_payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_429.status_code == 429
        assert "Rate limit exceeded" in res_429.json()["detail"]


def test_openai_models_endpoints() -> None:
    """Verify GET /v1/models and GET /v1/models/{model_id}."""
    client = TestClient(app)

    # List models
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    res_json = resp.json()
    assert res_json["object"] == "list"
    model_ids = [m["id"] for m in res_json["data"]]
    assert "llama3" in model_ids

    # Get existing model detail
    resp_detail = client.get("/v1/models/llama3")
    assert resp_detail.status_code == 200
    assert resp_detail.json()["id"] == "llama3"

    # Get non-existent model detail
    resp_404 = client.get("/v1/models/nonexistent-model")
    assert resp_404.status_code == 404


def test_telemetry_endpoints() -> None:
    """Verify GET /nodes/{node_id}/telemetry and GET /nodes/telemetry."""
    client = TestClient(app)

    # Set mock telemetry data in registry
    app.state.registry._telemetry["test-node"] = {
        "node_id": "test-node",
        "cpu_utilization": 22.5,
        "ram_used_bytes": 8589934592,
        "ram_total_bytes": 17179869184,
        "gpu_utilization": 45.0,
        "vram_used_bytes": 4294967296,
        "vram_total_bytes": 8589934592,
        "wan_connected": True,
    }

    # Test single node telemetry
    resp_node = client.get("/nodes/test-node/telemetry")
    assert resp_node.status_code == 200
    data = resp_node.json()
    assert data["node_id"] == "test-node"
    assert data["cpu_utilization"] == 22.5

    # Test missing node telemetry
    resp_404 = client.get("/nodes/unknown-node/telemetry")
    assert resp_404.status_code == 404

    # Test list all telemetry
    resp_all = client.get("/nodes/telemetry")
    assert resp_all.status_code == 200
    all_data = resp_all.json()
    assert "test-node" in all_data
    assert all_data["test-node"]["cpu_utilization"] == 22.5
