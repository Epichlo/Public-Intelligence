"""Gateway behaviour for `POST /v1/chat/completions`: SSE format, 503s, errors.

The title says "Split Inference" for historical reasons and no longer describes the
file. The boundary-engine unit tests it used to also contain moved to
`experimental/scheduler/tests/` under ROADMAP C2, along with the modules they cover;
the gateway tests here are shipping behaviour and stayed.

What remains: streaming chunk format (`data: {...}\n\n` and `[DONE]`), 503 when the
registry is empty, node-error propagation mid-stream, and the non-streaming path.
Split inference itself is refused with 501 -- that is
`test_split_inference_refused.py` (ROADMAP N1).
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
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
    """Generate RSA key pair for JWT signing and verification."""
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
    private_key: rsa.RSAPrivateKey, tenant_id: str | None = "test-tenant", expired: bool = False
) -> str:
    """Generate a signed JWT for testing."""
    payload: dict[str, Any] = {
        "sub": "client-user",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=10)
        if not expired
        else datetime.now(UTC) - timedelta(minutes=10),
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id

    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture(autouse=True)
def setup_app_state(key_pair: tuple[rsa.RSAPrivateKey, str]) -> None:
    """Setup app state with test keys, mock consensus, and default test node."""
    _, public_key_pem = key_pair
    app.state.jwt_public_key = public_key_pem
    app.state.rate_limiter = TokenBucketLimiter(capacity=5, refill_rate=0.5)

    mock_consensus = MagicMock()
    mock_consensus.is_active.return_value = True
    mock_consensus.propose = AsyncMock()
    app.state.registry.consensus_engine = mock_consensus

    app.state.registry._nodes.clear()
    app.state.registry._heartbeats.clear()
    app.state.registry._telemetry.clear()

    test_node = Node(
        node_id="node-split-1",
        hostname="localhost",
        ip_address="127.0.0.1",
        region="us-west",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3", "mock-model"],
    )
    app.state.registry._nodes["node-split-1"] = test_node


# -----------------------------------------------------------------------------
# 2. Empty Registry HTTP 503 Verification
# -----------------------------------------------------------------------------


def test_openai_completion_empty_registry_returns_503(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Verify POST /v1/chat/completions returns HTTP 503 when NodeRegistry contains 0 nodes."""
    private_key, _ = key_pair
    token = generate_token(private_key, tenant_id="tenant-empty")

    # Clear all registered nodes
    app.state.registry._nodes.clear()

    client = TestClient(app)
    req_body = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Hello empty cluster"}],
        "stream": False,
    }

    response = client.post(
        "/v1/chat/completions",
        json=req_body,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    err_detail = response.json().get("detail", "")
    assert "No suitable compute node available" in err_detail or "No node available" in err_detail


def test_openai_completion_empty_registry_streaming_returns_503(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Verify streaming request returns HTTP 503 when NodeRegistry is empty."""
    private_key, _ = key_pair
    token = generate_token(private_key, tenant_id="tenant-empty-stream")

    # Clear nodes and disable scheduling engine fallback
    app.state.registry._nodes.clear()

    client = TestClient(app)
    req_body = {
        "model": "nonexistent-model",
        "messages": [{"role": "user", "content": "Stream test"}],
        "stream": True,
    }

    response = client.post(
        "/v1/chat/completions",
        json=req_body,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503


# -----------------------------------------------------------------------------
# 3. SSE Stream Formatting & Chunk Generation Verification
# -----------------------------------------------------------------------------


def test_openai_streaming_sse_chunk_format_and_termination(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Verify streaming response outputs strictly compliant OpenAI SSE chunk format."""
    private_key, _ = key_pair
    token = generate_token(private_key, tenant_id="tenant-sse-format")
    client = TestClient(app)

    request_payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Tell me a joke"}],
        "stream": True,
    }

    stream_lines = [
        'data: {"response": "Why "}\n',
        'data: {"response": "did "}\n',
        'data: {"response": "the "}\n',
        'data: {"response": "robot "}\n',
        'data: {"response": "cross?"}\n',
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
    assert "text/event-stream" in response.headers.get("content-type", "")

    raw_text = response.text

    # Verify SSE chunk lines start with "data: " and end with double newlines
    sse_blocks = [b.strip() for b in raw_text.split("\n\n") if b.strip()]
    assert len(sse_blocks) >= 3  # Initial role, content chunks, final stop, [DONE]

    # Verify initial role chunk
    first_block = sse_blocks[0]
    assert first_block.startswith("data: {")
    assert '"object":"chat.completion.chunk"' in first_block
    assert '"role":"assistant"' in first_block

    # Verify token content chunks
    assert '"content":"Why "' in raw_text
    assert '"content":"cross?"' in raw_text

    # Verify final termination markers
    last_block = sse_blocks[-1]
    assert last_block == "data: [DONE]"

    stop_block = sse_blocks[-2]
    assert '"finish_reason":"stop"' in stop_block


def test_openai_streaming_node_error_propagation(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Verify compute node connection error during SSE streaming emits formatted error chunk."""
    private_key, _ = key_pair
    token = generate_token(private_key, tenant_id="tenant-stream-err")
    client = TestClient(app)

    request_payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Trigger stream error"}],
        "stream": True,
    }

    class FailingStreamContext:
        async def __aenter__(self):
            raise httpx.ConnectError("Connection refused by compute node")

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch.object(httpx.AsyncClient, "stream", return_value=FailingStreamContext()):
        response = client.post(
            "/v1/chat/completions",
            json=request_payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

    body_text = response.text
    assert "Stream Error" in body_text or "Connection refused" in body_text
    assert '"finish_reason":"error"' in body_text
    assert "data: [DONE]" in body_text


# -----------------------------------------------------------------------------
# 4. Auth & Non-streaming Operations Verification
# -----------------------------------------------------------------------------


def test_openai_non_streaming_completion_success(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Verify non-streaming POST /v1/chat/completions succeeds with full usage token count."""
    private_key, _ = key_pair
    token = generate_token(private_key, tenant_id="tenant-non-stream")
    client = TestClient(app)

    request_payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "What is 2+2?"}],
        "stream": False,
    }

    mock_node_resp = httpx.Response(
        status_code=200,
        json={"model": "llama3", "response": "2 + 2 = 4"},
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_resp

        response = client.post(
            "/v1/chat/completions",
            json=request_payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    res_json = response.json()
    assert res_json["object"] == "chat.completion"
    assert res_json["choices"][0]["message"]["content"] == "2 + 2 = 4"
    assert res_json["usage"]["prompt_tokens"] > 0
    assert res_json["usage"]["completion_tokens"] > 0
    assert res_json["usage"]["total_tokens"] > 0
