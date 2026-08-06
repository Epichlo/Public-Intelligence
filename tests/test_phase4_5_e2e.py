"""Phase 4.5 End-to-End Integration Test Suite.

Requirements-Driven Dual-Track Testing:
- Tier 1: Feature Coverage (Node telemetry emission, OpenAI REST Gateway non-streaming & SSE streaming, models endpoint)
- Tier 2: Boundary & Corner Cases (invalid JWT auth, rate limit capacity exhaustion, missing model, invalid control action)
- Tier 3: Cross-Feature Combinations (simultaneous telemetry updates, rate limit refill, streaming SSE chat completions)
- Tier 4: Real-World Workload Simulation (requester prompt submission & host node start/stop lifecycle)
"""

import time
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

# Node imports
from node.core.configuration import Settings as NodeSettings
from node.core.configuration import get_settings as node_get_settings
from node.core.runtime import sandbox_log_buffer
from node.main import app as node_app

# Scheduler imports
from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.main import app as scheduler_app
from scheduler.models.node import GPUInfo
from scheduler.models.node import Node as SchedulerNode

# -----------------------------------------------------------------------------
# Fixtures & Helpers
# -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsa_key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    """Generate an RSA key pair for signing and verifying JWTs in E2E tests."""
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
    tenant_id: str | None = "e2e-tenant",
    expired: bool = False,
) -> str:
    """Helper function to generate signed RS256 JWT tokens."""
    now = datetime.now(UTC)
    payload = {
        "sub": "e2e-test-user",
        "iat": now,
        "exp": now - timedelta(minutes=10) if expired else now + timedelta(minutes=10),
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id

    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture
def scheduler_client(rsa_key_pair: tuple[rsa.RSAPrivateKey, str]) -> TestClient:
    """Configure Scheduler FastAPI app state with test keys, mock consensus engine, and fresh registry."""
    _, public_key_pem = rsa_key_pair
    scheduler_app.state.jwt_public_key = public_key_pem
    scheduler_app.state.rate_limiter = TokenBucketLimiter(capacity=5, refill_rate=0.5)

    # Mock consensus engine
    mock_consensus = MagicMock()
    mock_consensus.is_active.return_value = True
    mock_consensus.propose = AsyncMock()
    scheduler_app.state.registry.consensus_engine = mock_consensus

    # Reset registry state
    scheduler_app.state.registry._nodes.clear()
    scheduler_app.state.registry._heartbeats.clear()
    scheduler_app.state.registry._telemetry.clear()

    # Register test node with model "llama3"
    test_node = SchedulerNode(
        node_id="node-e2e-1",
        hostname="localhost",
        ip_address="127.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3", "mistral-7b"],
    )
    scheduler_app.state.registry._nodes["node-e2e-1"] = test_node

    return TestClient(scheduler_app)


NODE_AUTH_TOKEN = "e2e-node-auth-token"


@pytest.fixture
def node_client() -> Generator[TestClient, None, None]:
    """Provide TestClient for Node local control and telemetry API.

    The Node's control and inference routes require `X-Network-Auth-Token`. This
    fixture configures a real token and sends it on every request rather than
    overriding the dependency, so the end-to-end path exercises authentication
    for real instead of stubbing it out.
    """
    mock_rt = MagicMock()
    mock_rt.is_running = False
    mock_rt.settings = MagicMock()
    mock_rt.settings.node_id = "test-node-e2e"
    mock_rt.zenoh_client = MagicMock()
    mock_rt.zenoh_client.is_connected.return_value = True

    async def mock_start() -> None:
        mock_rt.is_running = True

    async def mock_stop() -> None:
        mock_rt.is_running = False

    mock_rt.start = AsyncMock(side_effect=mock_start)
    mock_rt.stop = AsyncMock(side_effect=mock_stop)

    node_app.state.runtime = mock_rt
    sandbox_log_buffer.clear()

    node_app.dependency_overrides[node_get_settings] = lambda: NodeSettings(
        network_auth_token=NODE_AUTH_TOKEN
    )
    try:
        yield TestClient(node_app, headers={"X-Network-Auth-Token": NODE_AUTH_TOKEN})
    finally:
        node_app.dependency_overrides.pop(node_get_settings, None)


# -----------------------------------------------------------------------------
# Tier 1: Feature Coverage Tests
# -----------------------------------------------------------------------------


def test_tier1_node_telemetry_emission_and_api(
    node_client: TestClient, scheduler_client: TestClient
) -> None:
    """Tier 1: Verify local Node telemetry endpoint and Scheduler decrypted telemetry ingest."""
    # 1. Local Node Telemetry endpoint check
    local_resp = node_client.get("/api/v1/node/telemetry")
    assert local_resp.status_code == 200
    local_data = local_resp.json()
    assert "node_id" in local_data
    assert "cpu_utilization" in local_data
    assert "ram_used_bytes" in local_data
    assert "vram_total_bytes" in local_data
    assert "wan_connected" in local_data
    assert local_data["status"] in ("ready", "stopped")

    # 2. Inject simulated decrypted telemetry into Scheduler NodeRegistry
    emitted_telemetry = {
        "node_id": "node-e2e-1",
        "cpu_utilization": 35.2,
        "ram_used_bytes": 17179869184,
        "ram_total_bytes": 68719476736,
        "gpu_utilization": 62.8,
        "vram_used_bytes": 8589934592,
        "vram_total_bytes": 25769803776,
        "wan_connected": True,
        "timestamp": time.time(),
    }
    scheduler_app.state.registry._telemetry["node-e2e-1"] = emitted_telemetry

    # 3. Query Scheduler single-node telemetry endpoint
    node_tele_resp = scheduler_client.get("/nodes/node-e2e-1/telemetry")
    assert node_tele_resp.status_code == 200
    node_tele_data = node_tele_resp.json()
    assert node_tele_data["node_id"] == "node-e2e-1"
    assert node_tele_data["cpu_utilization"] == 35.2
    assert node_tele_data["gpu_utilization"] == 62.8
    assert node_tele_data["wan_connected"] is True

    # 4. Query Scheduler list-all telemetry endpoint
    all_tele_resp = scheduler_client.get("/nodes/telemetry")
    assert all_tele_resp.status_code == 200
    all_tele_data = all_tele_resp.json()
    assert "node-e2e-1" in all_tele_data
    assert all_tele_data["node-e2e-1"]["vram_used_bytes"] == 8589934592


def test_tier1_openai_gateway_chat_completion_non_streaming(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, str],
    scheduler_client: TestClient,
) -> None:
    """Tier 1: Verify non-streaming POST /v1/chat/completions returns valid ChatCompletionResponse JSON."""
    private_key, _ = rsa_key_pair
    token = generate_jwt(private_key, tenant_id="tenant-tier1-nonstream")

    payload = {
        "model": "llama3",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is Public Intelligence?"},
        ],
        "stream": False,
        "temperature": 0.7,
    }

    mock_node_resp = httpx.Response(
        status_code=200,
        json={
            "model": "llama3",
            "response": "Public Intelligence is a decentralized P2P compute network.",
        },
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_resp
        response = scheduler_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    res_json = response.json()

    assert res_json["id"].startswith("chatcmpl-")
    assert res_json["object"] == "chat.completion"
    assert res_json["model"] == "llama3"

    choices = res_json["choices"]
    assert len(choices) == 1
    assert choices[0]["index"] == 0
    assert choices[0]["message"]["role"] == "assistant"
    assert (
        choices[0]["message"]["content"]
        == "Public Intelligence is a decentralized P2P compute network."
    )
    assert choices[0]["finish_reason"] == "stop"

    usage = res_json["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


def test_tier1_openai_gateway_chat_completion_sse_streaming(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, str],
    scheduler_client: TestClient,
) -> None:
    """Tier 1: Verify streaming POST /v1/chat/completions returns properly formatted SSE chunks."""
    private_key, _ = rsa_key_pair
    token = generate_jwt(private_key, tenant_id="tenant-tier1-stream")

    payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Stream response test"}],
        "stream": True,
    }

    stream_lines = [
        'data: {"response": "Public "}\n',
        'data: {"response": "Intelligence "}\n',
        'data: {"response": "Nodes"}\n',
    ]

    async def mock_aiter_lines() -> AsyncGenerator[str, None]:
        for line in stream_lines:
            yield line

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.aiter_lines = mock_aiter_lines

    class MockStreamContext:
        async def __aenter__(self) -> MagicMock:
            return mock_response

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    with patch.object(httpx.AsyncClient, "stream", return_value=MockStreamContext()):
        response = scheduler_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body_text = response.text

    assert "chat.completion.chunk" in body_text
    assert '"role":"assistant"' in body_text
    assert '"content":"Public "' in body_text
    assert '"content":"Intelligence "' in body_text
    assert '"content":"Nodes"' in body_text
    assert '"finish_reason":"stop"' in body_text
    assert "data: [DONE]" in body_text


def test_tier1_openai_gateway_models_endpoints(
    scheduler_client: TestClient,
) -> None:
    """Tier 1: Verify GET /v1/models and GET /v1/models/{model_id} model listing."""
    # 1. List all models
    resp_list = scheduler_client.get("/v1/models")
    assert resp_list.status_code == 200
    list_json = resp_list.json()

    assert list_json["object"] == "list"
    models_data = list_json["data"]
    model_ids = [m["id"] for m in models_data]

    assert "llama3" in model_ids
    assert "mistral-7b" in model_ids

    # 2. Get specific model detail
    resp_detail = scheduler_client.get("/v1/models/llama3")
    assert resp_detail.status_code == 200
    detail_json = resp_detail.json()
    assert detail_json["id"] == "llama3"
    assert detail_json["object"] == "model"
    assert detail_json["owned_by"] == "public-intelligence"


# -----------------------------------------------------------------------------
# Tier 2: Boundary & Corner Case Tests
# -----------------------------------------------------------------------------


def test_tier2_boundary_invalid_jwt_auth(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, str],
    scheduler_client: TestClient,
) -> None:
    """Tier 2: Verify auth failure conditions (missing header, bad signature, missing tenant_id, expired token)."""
    private_key, _ = rsa_key_pair
    payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Auth check"}],
    }

    # Case 1: Missing Authorization Header -> 401 or 422
    resp_no_auth = scheduler_client.post("/v1/chat/completions", json=payload)
    assert resp_no_auth.status_code in (401, 422)

    # Case 2: Malformed JWT token string -> 401
    resp_malformed = scheduler_client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer malformed.jwt.token"},
    )
    assert resp_malformed.status_code == 401
    assert "JWT signature verification failed" in resp_malformed.json()["detail"]

    # Case 3: JWT missing 'tenant_id' claim -> 401
    token_no_tenant = generate_jwt(private_key, tenant_id=None)
    resp_no_tenant = scheduler_client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {token_no_tenant}"},
    )
    assert resp_no_tenant.status_code == 401
    assert "Missing 'tenant_id'" in resp_no_tenant.json()["detail"]

    # Case 4: Expired JWT token -> 401
    token_expired = generate_jwt(private_key, tenant_id="tenant-exp", expired=True)
    resp_expired = scheduler_client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {token_expired}"},
    )
    assert resp_expired.status_code == 401
    assert "JWT signature verification failed" in resp_expired.json()["detail"]


def test_tier2_boundary_rate_limit_exhaustion(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, str],
    scheduler_client: TestClient,
) -> None:
    """Tier 2: Verify multi-tenant TokenBucketLimiter quota exhaustion triggers HTTP 429."""
    private_key, _ = rsa_key_pair
    token = generate_jwt(private_key, tenant_id="quota-burst-tenant")

    payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Ping"}],
        "stream": False,
    }

    mock_node_resp = httpx.Response(
        status_code=200,
        json={"model": "llama3", "response": "Pong"},
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_node_resp

        # Exhaust capacity (5 tokens)
        for i in range(5):
            res = scheduler_client.post(
                "/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 200, f"Request {i + 1} should pass"

        # 6th request must fail with 429 Too Many Requests
        res_429 = scheduler_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_429.status_code == 429
        assert "Rate limit exceeded" in res_429.json()["detail"]


def test_tier2_boundary_missing_model_and_invalid_payload(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, str],
    scheduler_client: TestClient,
) -> None:
    """Tier 2: Verify missing model error handling (HTTP 503 / 404) and invalid payload schema (HTTP 422)."""
    private_key, _ = rsa_key_pair
    token = generate_jwt(private_key, tenant_id="tenant-boundary")

    # 1. Request chat completion for non-existent model -> HTTP 503
    missing_model_payload = {
        "model": "gpt-99-nonexistent",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    resp_503 = scheduler_client.post(
        "/v1/chat/completions",
        json=missing_model_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_503.status_code == 503
    assert (
        "No node available" in resp_503.json()["detail"]
        or "No suitable compute node" in resp_503.json()["detail"]
    )

    # 2. Get specific model detail for non-existent model -> HTTP 404
    resp_404 = scheduler_client.get("/v1/models/gpt-99-nonexistent")
    assert resp_404.status_code == 404
    assert "not found among active nodes" in resp_404.json()["detail"]

    # 3. Invalid Pydantic schema (missing required 'messages' field) -> HTTP 422
    invalid_schema_payload = {
        "model": "llama3",
    }
    resp_422 = scheduler_client.post(
        "/v1/chat/completions",
        json=invalid_schema_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_422.status_code == 422


def test_tier2_boundary_invalid_node_control_action(
    node_client: TestClient, scheduler_client: TestClient
) -> None:
    """Tier 2: Verify invalid action error handling on Node control API and missing node telemetry."""
    # 1. Invalid control action (e.g. 'restart') -> HTTP 400
    resp_invalid_ctrl = node_client.post(
        "/api/v1/node/control",
        json={"action": "restart"},
    )
    assert resp_invalid_ctrl.status_code == 400
    assert "Invalid action" in resp_invalid_ctrl.json()["detail"]

    # 2. Query telemetry for non-existent node ID on Scheduler -> HTTP 404
    resp_missing_tele = scheduler_client.get("/nodes/nonexistent-node-99/telemetry")
    assert resp_missing_tele.status_code == 404
    assert "Telemetry not found" in resp_missing_tele.json()["detail"]


# -----------------------------------------------------------------------------
# Tier 3: Cross-Feature Combination Tests
# -----------------------------------------------------------------------------


def test_tier3_cross_feature_simultaneous_telemetry_rate_limit_refill_and_streaming(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, str],
    scheduler_client: TestClient,
) -> None:
    """Tier 3: Concurrent cross-feature interaction testing.

    Tests node telemetry updates, rate limiter capacity exhaustion & refill,
    and streaming SSE completions.
    """
    private_key, _ = rsa_key_pair

    # Configure rate limiter with capacity=2
    limiter = TokenBucketLimiter(capacity=2, refill_rate=0.5)
    scheduler_app.state.rate_limiter = limiter

    # Register multi-node topology with active telemetry
    node1 = SchedulerNode(
        node_id="node-cross-1",
        hostname="host1",
        ip_address="127.0.0.1",
        region="us-east",
        cpu_cores=16,
        ram_total_gb=64.0,
        gpu=GPUInfo(name="A100", vram_total_gb=80.0, vram_available_gb=60.0),
        available_models=["llama3"],
    )
    node2 = SchedulerNode(
        node_id="node-cross-2",
        hostname="host2",
        ip_address="127.0.0.2",
        region="us-west",
        cpu_cores=16,
        ram_total_gb=64.0,
        gpu=GPUInfo(name="H100", vram_total_gb=80.0, vram_available_gb=70.0),
        available_models=["llama3"],
    )
    scheduler_app.state.registry._nodes["node-cross-1"] = node1
    scheduler_app.state.registry._nodes["node-cross-2"] = node2

    scheduler_app.state.registry._telemetry["node-cross-1"] = {
        "node_id": "node-cross-1",
        "cpu_utilization": 15.0,
        "ram_used_bytes": 1000000,
        "ram_total_bytes": 8000000,
        "gpu_utilization": 20.0,
        "vram_used_bytes": 2000000,
        "vram_total_bytes": 8000000,
        "wan_connected": True,
    }
    scheduler_app.state.registry._telemetry["node-cross-2"] = {
        "node_id": "node-cross-2",
        "cpu_utilization": 25.0,
        "ram_used_bytes": 2000000,
        "ram_total_bytes": 8000000,
        "gpu_utilization": 30.0,
        "vram_used_bytes": 3000000,
        "vram_total_bytes": 8000000,
        "wan_connected": True,
    }

    token_tenant_a = generate_jwt(private_key, tenant_id="tenant-cross-A")
    token_tenant_b = generate_jwt(private_key, tenant_id="tenant-cross-B")

    # Step 1: Tenant A consumes its 2 tokens
    payload = {"model": "llama3", "messages": [{"role": "user", "content": "Ping"}]}
    mock_post_resp = httpx.Response(200, json={"model": "llama3", "response": "Pong"})

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_post_resp

        r1 = scheduler_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token_tenant_a}"},
        )
        r2 = scheduler_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token_tenant_a}"},
        )
        assert r1.status_code == 200
        assert r2.status_code == 200

        # Step 2: Tenant A 3rd request fails (429)
        r3 = scheduler_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token_tenant_a}"},
        )
        assert r3.status_code == 429

    # Step 3: Concurrently, Tenant B sends SSE streaming chat completion request
    stream_payload = {
        "model": "llama3",
        "messages": [{"role": "user", "content": "Concurrent stream"}],
        "stream": True,
    }

    async def mock_stream_lines() -> AsyncGenerator[str, None]:
        yield 'data: {"response": "Concurrent "}\n'
        yield 'data: {"response": "Stream"}\n'

    mock_stream_resp = MagicMock()
    mock_stream_resp.status_code = 200
    mock_stream_resp.aiter_lines = mock_stream_lines

    class MockStreamCtx:
        async def __aenter__(self) -> MagicMock:
            return mock_stream_resp

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    with patch.object(httpx.AsyncClient, "stream", return_value=MockStreamCtx()):
        r_stream = scheduler_client.post(
            "/v1/chat/completions",
            json=stream_payload,
            headers={"Authorization": f"Bearer {token_tenant_b}"},
        )
        assert r_stream.status_code == 200
        assert "text/event-stream" in r_stream.headers["content-type"]
        assert "Concurrent " in r_stream.text

    # Step 4: Refill tokens for Tenant A by updating last_updated timestamp backward
    limiter.last_updated["tenant-cross-A"] = time.time() - 10.0

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_post_resp
        r_refilled = scheduler_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token_tenant_a}"},
        )
        assert r_refilled.status_code == 200

    # Step 5: Verify telemetry for both nodes remains available and consistent
    r_tele = scheduler_client.get("/nodes/telemetry")
    assert r_tele.status_code == 200
    tele_data = r_tele.json()
    assert tele_data["node-cross-1"]["cpu_utilization"] == 15.0
    assert tele_data["node-cross-2"]["gpu_utilization"] == 30.0


# -----------------------------------------------------------------------------
# Tier 4: Real-World Workload Tests
# -----------------------------------------------------------------------------


def test_tier4_real_world_requester_prompt_and_node_lifecycle(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, str],
    node_client: TestClient,
    scheduler_client: TestClient,
) -> None:
    """Tier 4: End-to-end simulation of interactive requester prompt submission and host node start/stop lifecycle."""
    private_key, _ = rsa_key_pair
    token = generate_jwt(private_key, tenant_id="realworld-requester")

    # Step 1: Initial host node check -> Node runtime is stopped
    initial_tele = node_client.get("/api/v1/node/telemetry")
    assert initial_tele.status_code == 200
    assert initial_tele.json()["status"] == "stopped"

    # Step 2: Host starts Node runtime via Host Control API
    start_resp = node_client.post(
        "/api/v1/node/control",
        json={"action": "start"},
    )
    assert start_resp.status_code == 200
    start_data = start_resp.json()
    assert start_data["status"] == "ok"
    assert start_data["action"] == "start"
    assert start_data["runtime_running"] is True

    # Step 3: Register live Host Node in Scheduler registry serving model "llama3"
    live_host_node = SchedulerNode(
        node_id="node-host-live",
        hostname="live-host.local",
        ip_address="127.0.0.1",
        region="us-east",
        cpu_cores=16,
        ram_total_gb=64.0,
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=22.0),
        available_models=["llama3"],
    )
    scheduler_app.state.registry._nodes["node-host-live"] = live_host_node

    # Step 4: Requester submits prompt via OpenAI REST Gateway with SSE streaming
    request_payload = {
        "model": "llama3",
        "messages": [
            {"role": "system", "content": "You are a live compute node assistant."},
            {"role": "user", "content": "Simulate live workload execution."},
        ],
        "stream": True,
    }

    stream_tokens = [
        'data: {"response": "Real-world "}\n',
        'data: {"response": "workload "}\n',
        'data: {"response": "executed successfully."}\n',
    ]

    async def mock_node_stream() -> AsyncGenerator[str, None]:
        for t in stream_tokens:
            yield t

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = mock_node_stream

    class MockStreamContextManager:
        async def __aenter__(self) -> MagicMock:
            return mock_resp

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    with patch.object(httpx.AsyncClient, "stream", return_value=MockStreamContextManager()):
        gateway_resp = scheduler_client.post(
            "/v1/chat/completions",
            json=request_payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert gateway_resp.status_code == 200
    assert "text/event-stream" in gateway_resp.headers["content-type"]
    stream_output = gateway_resp.text

    assert "chat.completion.chunk" in stream_output
    assert '"content":"Real-world "' in stream_output
    assert '"content":"workload "' in stream_output
    assert '"content":"executed successfully."' in stream_output
    assert "data: [DONE]" in stream_output

    # Step 5: Simulate Docker sandbox container log generation & verify log stream API
    sandbox_log_buffer.add_log(
        "Docker sandbox container task execution started: task_id=chatcmpl-e2e",
        stream="stdout",
        branch="main",
    )
    sandbox_log_buffer.add_log(
        "Docker sandbox execution finished cleanly: exit_code=0",
        stream="stdout",
        branch="main",
    )

    logs_resp = node_client.get("/api/v1/sandbox/logs?limit=10")
    assert logs_resp.status_code == 200
    logs_data = logs_resp.json()
    assert len(logs_data["logs"]) >= 2
    assert "task execution started" in logs_data["logs"][-2]
    assert "finished cleanly" in logs_data["logs"][-1]

    # Verify log streaming SSE endpoint
    logs_stream_resp = node_client.get("/api/v1/sandbox/logs/stream?max_events=2")
    assert logs_stream_resp.status_code == 200
    assert "text/event-stream" in logs_stream_resp.headers["content-type"]
    assert "task execution started" in logs_stream_resp.text

    # Step 6: Host stops Node runtime via Host Control API
    stop_resp = node_client.post(
        "/api/v1/node/control",
        json={"action": "stop"},
    )
    assert stop_resp.status_code == 200
    stop_data = stop_resp.json()
    assert stop_data["status"] == "ok"
    assert stop_data["action"] == "stop"
    assert stop_data["runtime_running"] is False

    # Step 7: Unregister node from Scheduler registry -> verify subsequent prompt returns 503
    scheduler_app.state.registry._nodes.clear()

    with patch.object(httpx.AsyncClient, "stream", return_value=MockStreamContextManager()):
        stopped_gateway_resp = scheduler_client.post(
            "/v1/chat/completions",
            json=request_payload,
            headers={"Authorization": f"Bearer {token}"},
        )
    assert stopped_gateway_resp.status_code == 503
    assert "No suitable compute node" in stopped_gateway_resp.json()["detail"]
