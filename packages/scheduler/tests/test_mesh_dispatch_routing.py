"""The gateway must actually dispatch over the mesh for a mesh-reachable node.

This is the test that would have caught ROADMAP 1.1 being broken. Every existing green
test proxies over HTTP to `ip_address`, which is `127.0.0.1` for every installer-provisioned
node -- so the Scheduler dialled itself and no remote node ever served a request.

The assertions here are deliberately negative as well as positive: it is not enough that the
mesh client was called, HTTP must *not* have been dialled. A path that tried the mesh and
then quietly fell back to a loopback address would satisfy a weaker test while leaving the
bug in place.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.core.mesh_inference_client import MeshNodeError, MeshUnavailableError
from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.main import app
from scheduler.models.heartbeat import Heartbeat
from scheduler.models.node import GPUInfo, Node, NodeStatus

NODE_ID = "node-mesh-dispatch"
NODE_TOKEN = "dispatch-node-token"


@pytest.fixture(scope="module")
def key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_key, public_pem


class FakeMeshStream:
    def __init__(self, chunks: list[str], fail_after: Exception | None = None) -> None:
        self._chunks = list(chunks)
        self._fail_after = fail_after

    def __aiter__(self) -> "FakeMeshStream":
        return self

    async def __anext__(self) -> str:
        if self._chunks:
            return self._chunks.pop(0)
        if self._fail_after is not None:
            raise self._fail_after
        raise StopAsyncIteration


class FakeMeshClient:
    """Records what it was asked to do and returns a scripted outcome."""

    def __init__(
        self,
        *,
        result: dict[str, str] | None = None,
        chunks: list[str] | None = None,
        raises: Exception | None = None,
        stream_fail_after: Exception | None = None,
    ) -> None:
        self.result = result or {"model": "llama3", "response": "from the mesh"}
        self.chunks = chunks if chunks is not None else ["mesh ", "tokens"]
        self.raises = raises
        self.stream_fail_after = stream_fail_after
        self.calls: list[dict[str, Any]] = []

    async def infer(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append({"kind": "infer", **kwargs})
        if self.raises is not None:
            raise self.raises
        return self.result

    async def open_stream(self, **kwargs: Any) -> FakeMeshStream:
        self.calls.append({"kind": "stream", **kwargs})
        if self.raises is not None:
            raise self.raises
        return FakeMeshStream(self.chunks, self.stream_fail_after)


def _register_node(mesh_reachable: bool) -> None:
    registry = app.state.registry
    registry._nodes.clear()
    registry._heartbeats.clear()
    registry._telemetry.clear()
    registry._node_tokens.clear()
    registry._mesh_nodes.clear()

    registry._nodes[NODE_ID] = Node(
        node_id=NODE_ID,
        hostname="host-1",
        # The value every installer-provisioned node registers. Dialling it is the bug.
        ip_address="127.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3"],
    )
    registry.set_node_token(NODE_ID, NODE_TOKEN)
    # `/infer` selects through `Scheduler.select_node`, which ignores nodes with no
    # heartbeat, so one is needed for that route to reach dispatch at all.
    registry._heartbeats[NODE_ID] = Heartbeat(
        node_id=NODE_ID,
        timestamp=datetime.now(UTC),
        status=NodeStatus.ONLINE,
        queue_length=0,
        cpu_utilization=10.0,
        ram_available_gb=32.0,
        gpu_utilization=5.0,
        vram_available_gb=20.0,
    )
    if mesh_reachable:
        registry.mark_mesh_reachable(NODE_ID)


@pytest.fixture
def client(key_pair: tuple[rsa.RSAPrivateKey, str]) -> TestClient:
    _, public_pem = key_pair
    app.state.jwt_public_key = public_pem
    app.state.rate_limiter = TokenBucketLimiter(capacity=50, refill_rate=50.0)

    consensus = MagicMock()
    consensus.is_active.return_value = False
    app.state.registry.consensus_engine = consensus

    yield TestClient(app)

    app.state.mesh_client = None


def bearer(private_key: rsa.RSAPrivateKey) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": "u",
            "tenant_id": "tenant-a",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        private_key,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _http_ok() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"response": "from http", "model": "llama3"}
    resp.text = ""
    return resp


class _FakeHTTPStream:
    def __init__(self, **kwargs: Any) -> None:
        self.status_code = 200

    async def __aenter__(self) -> "_FakeHTTPStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def aiter_lines(self):
        yield '{"response": "from http"}'


def test_mesh_reachable_node_is_served_over_the_mesh(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """The whole point of 1.1: no HTTP dial for a node that lives on the mesh."""
    private_key, _ = key_pair
    _register_node(mesh_reachable=True)
    mesh = FakeMeshClient(result={"model": "llama3", "response": "served over zenoh"})
    app.state.mesh_client = mesh

    http_post = AsyncMock(side_effect=lambda *a, **k: _http_ok())
    with patch("httpx.AsyncClient.post", new=http_post):
        response = client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
            headers=bearer(private_key),
        )

    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "served over zenoh"
    assert http_post.await_count == 0, (
        "the Scheduler dialled HTTP for a mesh-reachable node; that dial goes to "
        "127.0.0.1, which is the Scheduler itself"
    )
    assert mesh.calls[0]["node_id"] == NODE_ID
    assert mesh.calls[0]["token"] == NODE_TOKEN


def test_node_not_on_the_mesh_still_uses_http(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """Containerised and same-host deployments must keep working."""
    private_key, _ = key_pair
    _register_node(mesh_reachable=False)
    mesh = FakeMeshClient()
    app.state.mesh_client = mesh

    http_post = AsyncMock(side_effect=lambda *a, **k: _http_ok())
    with patch("httpx.AsyncClient.post", new=http_post):
        response = client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
            headers=bearer(private_key),
        )

    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "from http"
    assert mesh.calls == [], "queried the mesh for a node never seen on it"
    assert http_post.await_count == 1


def test_mesh_silence_falls_back_to_http(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """Reachability is observed, not proof the queryable exists. Silence must not 502."""
    private_key, _ = key_pair
    _register_node(mesh_reachable=True)
    app.state.mesh_client = FakeMeshClient(raises=MeshUnavailableError("no queryable answered"))

    http_post = AsyncMock(side_effect=lambda *a, **k: _http_ok())
    with patch("httpx.AsyncClient.post", new=http_post):
        response = client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
            headers=bearer(private_key),
        )

    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "from http"
    assert http_post.await_count == 1, "mesh went silent and nothing fell back to HTTP"


def test_node_error_over_the_mesh_does_not_fall_back(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """The node answered. Retrying over HTTP would hide a real 404 behind a vague error."""
    private_key, _ = key_pair
    _register_node(mesh_reachable=True)
    app.state.mesh_client = FakeMeshClient(
        raises=MeshNodeError("model 'llama3' not found", status=404)
    )

    http_post = AsyncMock(side_effect=lambda *a, **k: _http_ok())
    with patch("httpx.AsyncClient.post", new=http_post):
        response = client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
            headers=bearer(private_key),
        )

    assert response.status_code == 404, response.text
    assert "not found" in response.text
    assert http_post.await_count == 0, "fell back to HTTP after the node reported an error"


def test_streaming_is_served_over_the_mesh(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    private_key, _ = key_pair
    _register_node(mesh_reachable=True)
    app.state.mesh_client = FakeMeshClient(chunks=["mesh ", "stream ", "works"])

    http_stream = MagicMock(side_effect=lambda *a, **k: _FakeHTTPStream())
    with (
        patch("httpx.AsyncClient.stream", new=http_stream),
        client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "llama3",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            headers=bearer(private_key),
        ) as response,
    ):
        body = "".join(response.iter_text())

    assert "mesh " in body and "stream " in body and "works" in body
    assert http_stream.call_count == 0, "streamed over HTTP for a mesh-reachable node"


def test_streaming_falls_back_to_http_before_the_first_chunk(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """Fallback is only safe while nothing has been sent, so it must happen here."""
    private_key, _ = key_pair
    _register_node(mesh_reachable=True)
    app.state.mesh_client = FakeMeshClient(raises=MeshUnavailableError("silence"))

    http_stream = MagicMock(side_effect=lambda *a, **k: _FakeHTTPStream())
    with (
        patch("httpx.AsyncClient.stream", new=http_stream),
        client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "llama3",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            headers=bearer(private_key),
        ) as response,
    ):
        body = "".join(response.iter_text())

    assert "from http" in body
    assert http_stream.call_count == 1, "streaming did not fall back to HTTP"


def test_streaming_node_error_before_any_chunk_is_reported_not_retried(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """A model the host has not pulled must surface as a 404, not a fallback attempt."""
    private_key, _ = key_pair
    _register_node(mesh_reachable=True)
    app.state.mesh_client = FakeMeshClient(
        raises=MeshNodeError("model 'llama3' not found", status=404)
    )

    http_stream = MagicMock(side_effect=lambda *a, **k: _FakeHTTPStream())
    with patch("httpx.AsyncClient.stream", new=http_stream):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "llama3",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            headers=bearer(private_key),
        )

    assert response.status_code == 404, response.text
    assert http_stream.call_count == 0


def test_schedule_infer_route_uses_the_mesh(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """`/infer` is a second proxy-to-node path and must not be left on HTTP alone.

    Scope on ROADMAP 0.1 grew for exactly this reason: fixing only `openai.py` shipped
    half a feature.
    """
    _register_node(mesh_reachable=True)
    mesh = FakeMeshClient(result={"model": "llama3", "response": "mesh infer"})
    app.state.mesh_client = mesh

    http_post = AsyncMock(side_effect=lambda *a, **k: _http_ok())
    with patch("httpx.AsyncClient.post", new=http_post):
        response = client.post("/infer", json={"model": "llama3", "prompt": "hello"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["node_id"] == NODE_ID
    assert body["result"]["response"] == "mesh infer"
    assert http_post.await_count == 0, "/infer dialled HTTP for a mesh-reachable node"


def test_schedule_infer_falls_back_to_http(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    _register_node(mesh_reachable=True)
    app.state.mesh_client = FakeMeshClient(raises=MeshUnavailableError("silence"))

    http_post = AsyncMock(side_effect=lambda *a, **k: _http_ok())
    with patch("httpx.AsyncClient.post", new=http_post):
        response = client.post("/infer", json={"model": "llama3", "prompt": "hello"})

    assert response.status_code == 200, response.text
    assert response.json()["result"]["response"] == "from http"
    assert http_post.await_count == 1
