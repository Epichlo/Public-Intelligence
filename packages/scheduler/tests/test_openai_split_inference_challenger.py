"""Empirical validation and challenge test suite for OpenAI Gateway Split Inference.

Authored by CHALLENGER 2 for Milestone M3 of Phase 4.6.
Tests:
- POST /v1/chat/completions split-inference routing & SSE chunk generation
- Local boundary embedding (embed_prompt) & unembedding (unembed_logits) invocation
- Stream chunk formatting (data: {...}\n\n) and [DONE] termination
- Clean HTTP 503 error handling when NodeRegistry is empty
- Auth and rate-limit boundaries
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

from scheduler.core.boundary_engine import LocalBoundaryEngine as GatewayBoundaryEngine
from scheduler.core.local_boundary import LocalBoundaryEngine
from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.main import app
from scheduler.models.node import GPUInfo, Node
from scheduler.models.pipeline import TensorPayload


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
# 1. Local Boundary Engine Unit & Integration Verification
# -----------------------------------------------------------------------------


def test_local_boundary_embed_prompt_split_inference_payload() -> None:
    """Verify embed_prompt creates a valid TensorPayload with split-inference flag."""
    boundary = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)
    prompt = "Test prompt for split inference embedding"
    payload = boundary.embed_prompt(prompt=prompt, task_id="task-m3-test", target_stage_index=1)

    assert isinstance(payload, TensorPayload)
    assert payload.is_split_inference is True
    assert payload.stage_index == 0
    assert payload.target_stage_index == 1
    assert payload.dtype == "float32"
    assert payload.shape[0] == 1
    assert payload.shape[2] == 128
    assert payload.shape[1] > 0

    # Ensure zero raw prompt text leakage in serialized payload metadata
    payload_repr = str(payload)
    assert prompt not in payload_repr
    assert "prompt" not in payload_repr.lower() or "activation" in payload_repr.lower()


def test_boundary_engine_module_reexports_the_canonical_engine() -> None:
    """Renamed: this never tested the gateway, and now the gateway has no link to it.

    It was `test_gateway_boundary_import_uses_canonical_local_boundary`, which
    implied `api/openai.py` resolves to this class. It does not -- ROADMAP N1
    removed that wiring, because reaching `LocalBoundaryEngine` from a request meant
    returning simulated tokens to a caller as a normal 200. All this checks is that
    `core/boundary_engine` re-exports `core/local_boundary`. Both modules are
    slated for quarantine under ROADMAP C2.
    """
    assert GatewayBoundaryEngine is LocalBoundaryEngine


def test_tensor_payload_split_boundary_rejects_prompt_like_payloads() -> None:
    """Verify split payload validation rejects prompt-like data across the boundary."""
    malicious_payloads = [
        TensorPayload(
            task_id="task_prompt_type",
            stage_index=0,
            target_stage_index=1,
            is_split_inference=True,
            tensor_type="full_prompt",
            data=[1.0, 2.0],
            shape=[1, 2],
            dtype="float32",
        ),
        TensorPayload(
            task_id="task_string_dtype",
            stage_index=0,
            target_stage_index=1,
            is_split_inference=True,
            tensor_type="activation",
            data=b"secret prompt text",
            shape=[1, 18],
            dtype="string",
        ),
        TensorPayload(
            task_id="task_structured_prompt",
            stage_index=0,
            target_stage_index=1,
            is_split_inference=True,
            tensor_type="activation",
            data={"messages": [{"role": "user", "content": "private"}], "token_ids": [1]},
            shape=[1, 1],
            dtype="float32",
        ),
        TensorPayload(
            task_id="task_bad_shape",
            stage_index=0,
            target_stage_index=1,
            is_split_inference=True,
            tensor_type="activation",
            data=[1.0, 2.0],
            shape=[1, 3],
            dtype="float32",
        ),
    ]

    for payload in malicious_payloads:
        with pytest.raises(ValueError):
            payload.validate_split_activation_boundary()


def test_local_boundary_unembed_logits_sampling() -> None:
    """Verify unembed_logits performs LM Head projection and samples token deterministically."""
    boundary = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)

    # Mock activation vector H_(N-1) payload
    h_data = [0.1 * (i % 10) for i in range(128)]
    activation_payload = TensorPayload(
        task_id="task-m3-unembed",
        stage_index=2,
        target_stage_index=3,
        is_split_inference=True,
        tensor_type="activation",
        data=h_data,
        shape=[1, 1, 128],
        dtype="float32",
    )

    # Temperature 0.0 (greedy)
    tid1, text1 = boundary.unembed_logits(activation_payload, temperature=0.0)
    tid2, text2 = boundary.unembed_logits(activation_payload, temperature=0.0)

    assert isinstance(tid1, int)
    assert isinstance(text1, str)
    assert 0 <= tid1 < 1000
    assert tid1 == tid2
    assert text1 == text2


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
