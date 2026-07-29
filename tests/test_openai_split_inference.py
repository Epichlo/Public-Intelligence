"""Integration unit tests for OpenAI Split-Inference Gateway routing and streaming."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.core.config import get_settings
from scheduler.core.engine import SchedulingEngine
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


@pytest.fixture
def valid_token(key_pair: tuple[rsa.RSAPrivateKey, str]) -> str:
    """Generate a valid RS256 JWT token for authentication."""
    private_key, _ = key_pair
    payload = {
        "tenant_id": "tenant-split-test",
        "sub": "user-split-123",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture(autouse=True)
def setup_test_app(key_pair: tuple[rsa.RSAPrivateKey, str]) -> None:
    """Configure FastAPI app state with test keys, scheduling engine, and test nodes."""
    _, public_key_pem = key_pair
    app.state.jwt_public_key = public_key_pem
    app.state.rate_limiter = TokenBucketLimiter(capacity=10, refill_rate=1.0)

    # Set up node registry and scheduling engine
    app.state.registry._nodes.clear()
    app.state.registry._heartbeats.clear()
    app.state.registry._telemetry.clear()

    from scheduler.core.matchmaker import CapabilityMatchmaker

    strategy = CapabilityMatchmaker(registry=app.state.registry)
    engine = SchedulingEngine(registry=app.state.registry, strategy=strategy)
    app.state.scheduling_engine = engine

    # Register test compute node
    test_node = Node(
        node_id="split-node-1",
        hostname="split-host-1",
        ip_address="127.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="NVIDIA RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=32.0,
        available_models=["llama3", "mistral-7b"],
    )
    app.state.registry._nodes[test_node.node_id] = test_node


def test_create_chat_completion_split_inference_non_streaming(valid_token: str) -> None:
    """Test POST /v1/chat/completions with split_inference=True non-streaming mode."""
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {valid_token}"}
    payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Hello split inference"}],
        "split_inference": True,
        "stream": False,
    }

    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert data["object"] == "chat.completion"
    assert data["model"] == "llama3"
    assert len(data["choices"]) == 1
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert isinstance(data["choices"][0]["message"]["content"], str)
    assert data["usage"]["total_tokens"] > 0


def test_create_chat_completion_split_inference_streaming(valid_token: str) -> None:
    """Test POST /v1/chat/completions with split_inference=True streaming SSE mode."""
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {valid_token}"}
    payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Stream split inference test"}],
        "split_inference": True,
        "stream": True,
    }

    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

    lines = response.text.split("\n\n")
    data_lines = [line.strip() for line in lines if line.strip().startswith("data: ")]

    assert len(data_lines) >= 3
    assert "chat.completion.chunk" in data_lines[0]
    assert "data: [DONE]" in data_lines[-1]


def test_create_chat_completion_split_inference_header_trigger(valid_token: str) -> None:
    """Test POST /v1/chat/completions triggered by X-Split-Inference header."""
    client = TestClient(app)
    headers = {
        "Authorization": f"Bearer {valid_token}",
        "X-Split-Inference": "true",
    }
    payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Header triggered split inference"}],
        "stream": False,
    }

    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["role"] == "assistant"


def test_create_chat_completion_split_inference_remote_timeout(valid_token: str) -> None:
    """Test HTTP 504 Gateway Timeout when remote split stage fails to respond within timeout."""

    class DummyStreamRouter:
        async def send_tensor_payload(self, payload: Any) -> None:
            pass

    class DummyZenohSession:
        def declare_subscriber(self, topic: str, callback: Any) -> Any:
            return self

        def undeclare(self) -> None:
            pass

    client = TestClient(app)
    app.state.stream_router = DummyStreamRouter()
    app.state.zenoh_session = DummyZenohSession()
    orig_timeout = getattr(get_settings(), "split_inference_timeout_seconds", 5.0)
    get_settings().split_inference_timeout_seconds = 0.02

    try:
        headers = {"Authorization": f"Bearer {valid_token}"}
        payload = {
            "model": "llama3",
            "messages": [{"role": "user", "content": "Timeout split test"}],
            "split_inference": True,
        }
        response = client.post("/v1/chat/completions", json=payload, headers=headers)
        assert response.status_code == 504
        assert "Gateway Timeout" in response.json()["detail"]
    finally:
        get_settings().split_inference_timeout_seconds = orig_timeout
        app.state.stream_router = None
        app.state.zenoh_session = None


def test_create_chat_completion_split_inference_remote_validation_failure(
    valid_token: str,
) -> None:
    """Test HTTP 502 Bad Gateway when remote split stage returns invalid payload."""
    from scheduler.models.pipeline import TensorPayload

    class DummyStreamRouter:
        async def send_tensor_payload(self, payload: Any) -> None:
            pass

    class DummyZenohSession:
        def declare_subscriber(self, topic: str, callback: Any) -> Any:

            class DummySample:
                def __init__(self) -> None:
                    invalid = TensorPayload(
                        task_id="task-invalid",
                        stage_index=1,
                        target_stage_index=2,
                        is_split_inference=True,
                        tensor_type="prompt_text",
                        data=["leaked prompt"],
                    )
                    self.payload = invalid.to_framed_bytes()

            callback(DummySample())
            return self

        def undeclare(self) -> None:
            pass

    client = TestClient(app)
    app.state.stream_router = DummyStreamRouter()
    app.state.zenoh_session = DummyZenohSession()
    orig_timeout = getattr(get_settings(), "split_inference_timeout_seconds", 5.0)
    get_settings().split_inference_timeout_seconds = 1.0

    try:
        headers = {"Authorization": f"Bearer {valid_token}"}
        payload = {
            "model": "llama3",
            "messages": [{"role": "user", "content": "Validation failure test"}],
            "split_inference": True,
        }
        response = client.post("/v1/chat/completions", json=payload, headers=headers)
        assert response.status_code == 502
        assert "Bad Gateway" in response.json()["detail"]
    finally:
        get_settings().split_inference_timeout_seconds = orig_timeout
        app.state.stream_router = None
        app.state.zenoh_session = None
