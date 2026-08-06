"""Regression tests: the Scheduler must authenticate when proxying to a node.

The Node's `/infer` requires `X-Network-Auth-Token` and fails closed. The
Scheduler proxied to it with no headers at all, so every real inference request
returned 401 while all three suites stayed green -- Scheduler tests mock httpx,
Node tests bypass auth, and the E2E never crosses the wire.

These tests pin that the header is sent, and that it carries the token the node
supplied at registration rather than a fleet-wide secret.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.core.config import get_settings
from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.main import app
from scheduler.models.node import GPUInfo, Node

NODE_ID = "node-auth-1"
NODE_TOKEN = "node-1-secret-token"


@pytest.fixture(scope="module")
def key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    """RSA key pair for signing gateway JWTs."""
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


@pytest.fixture
def client(key_pair: tuple[rsa.RSAPrivateKey, str]) -> TestClient:
    """Scheduler client with one node registered and consensus stubbed out."""
    _, public_pem = key_pair
    app.state.jwt_public_key = public_pem
    app.state.rate_limiter = TokenBucketLimiter(capacity=50, refill_rate=50.0)

    consensus = MagicMock()
    consensus.is_active.return_value = False
    app.state.registry.consensus_engine = consensus

    app.state.registry._nodes.clear()
    app.state.registry._heartbeats.clear()
    app.state.registry._telemetry.clear()
    if hasattr(app.state.registry, "_node_tokens"):
        app.state.registry._node_tokens.clear()

    app.state.registry._nodes[NODE_ID] = Node(
        node_id=NODE_ID,
        hostname="host-1",
        ip_address="10.0.0.5",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3"],
    )
    return TestClient(app)


def bearer(private_key: rsa.RSAPrivateKey) -> dict[str, str]:
    """Valid gateway credential."""
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


def _ok_response() -> MagicMock:
    """Minimal successful /infer response from a node."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"response": "hello", "model": "llama3"}
    resp.text = ""
    return resp


def test_registration_captures_the_node_token(client: TestClient) -> None:
    """The token a node presents at registration must be retained for later use."""
    body = {
        "node_id": "node-reg-1",
        "hostname": "h",
        "ip_address": "10.0.0.9",
        "region": "r",
        "gpu": {"name": "RTX 4090", "vram_total_gb": 24.0, "vram_available_gb": 20.0},
        "cpu_cores": 8,
        "ram_total_gb": 32.0,
        "available_models": ["llama3"],
    }
    response = client.post(
        "/nodes/register", json=body, headers={"X-Network-Auth-Token": "reg-token-xyz"}
    )
    assert response.status_code in (200, 201), response.text

    stored = app.state.registry.get_node_token("node-reg-1")
    assert stored == "reg-token-xyz", (
        "the Scheduler did not retain the node's credential from registration"
    )


def test_registration_does_not_leak_the_token(client: TestClient) -> None:
    """A node's credential must never appear in an API response."""
    body = {
        "node_id": "node-reg-2",
        "hostname": "h",
        "ip_address": "10.0.0.10",
        "region": "r",
        "gpu": {"name": "RTX 4090", "vram_total_gb": 24.0, "vram_available_gb": 20.0},
        "cpu_cores": 8,
        "ram_total_gb": 32.0,
        "available_models": ["llama3"],
    }
    register = client.post(
        "/nodes/register", json=body, headers={"X-Network-Auth-Token": "leaky-token"}
    )
    assert "leaky-token" not in register.text

    listed = client.get("/nodes")
    assert "leaky-token" not in listed.text, "node credential leaked via GET /nodes"


def test_proxy_sends_the_node_credential(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """A non-streaming completion must carry the target node's token upstream."""
    private_key, _ = key_pair
    asyncio.run(app.state.registry.set_node_token(NODE_ID, NODE_TOKEN))

    captured: dict[str, Any] = {}

    async def fake_post(url: str, **kwargs: Any) -> MagicMock:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return _ok_response()

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
        response = client.post(
            "/v1/chat/completions",
            json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
            headers=bearer(private_key),
        )

    assert response.status_code == 200, response.text
    headers = captured.get("headers") or {}
    assert headers.get("X-Network-Auth-Token") == NODE_TOKEN, (
        "Scheduler proxied to the node without its credential; the node's /infer "
        f"fails closed, so this request would 401. Sent headers: {headers}"
    )


def test_streaming_proxy_sends_the_node_credential(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """The SSE streaming path must carry the credential too, not just JSON."""
    private_key, _ = key_pair
    asyncio.run(app.state.registry.set_node_token(NODE_ID, NODE_TOKEN))

    captured: dict[str, Any] = {}

    class FakeStream:
        """Async context manager standing in for httpx's streaming response."""

        def __init__(self, **kwargs: Any) -> None:
            captured["headers"] = kwargs.get("headers")
            self.status_code = 200

        async def __aenter__(self) -> "FakeStream":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def aiter_lines(self):
            yield '{"response": "hi", "done": true}'

    def fake_stream(self: Any, method: str, url: str, **kwargs: Any) -> FakeStream:
        return FakeStream(**kwargs)

    with (
        patch("httpx.AsyncClient.stream", new=fake_stream),
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
        response.read()

    headers = captured.get("headers") or {}
    assert headers.get("X-Network-Auth-Token") == NODE_TOKEN, (
        f"streaming proxy omitted the node credential. Sent headers: {headers}"
    )


def test_unregister_purges_the_token(client: TestClient) -> None:
    """A departed node's credential must not linger in the registry."""
    asyncio.run(app.state.registry.set_node_token(NODE_ID, NODE_TOKEN))
    assert app.state.registry.get_node_token(NODE_ID) == NODE_TOKEN

    asyncio.run(app.state.registry.local_unregister_node(NODE_ID))
    assert app.state.registry.get_node_token(NODE_ID) is None, (
        "node credential survived unregistration"
    )


def test_reregistration_refreshes_a_rotated_token(client: TestClient) -> None:
    """A node re-registering with a new credential must overwrite the old one.

    Regression guard. The credential was recorded only after a successful
    registration, so a node that re-registered -- returning 409 because its record
    still existed -- left the Scheduler holding the previous token. Every dispatch
    to that node then 401'd, with nothing logged to say why.
    """
    body = {
        "node_id": "node-rotate",
        "hostname": "h",
        "ip_address": "10.0.0.11",
        "region": "r",
        "gpu": {"name": "RTX 4090", "vram_total_gb": 24.0, "vram_available_gb": 20.0},
        "cpu_cores": 8,
        "ram_total_gb": 32.0,
        "available_models": ["llama3"],
    }

    first = client.post("/nodes/register", json=body, headers={"X-Network-Auth-Token": "TOKEN-V1"})
    assert first.status_code in (200, 201)
    assert app.state.registry.get_node_token("node-rotate") == "TOKEN-V1"

    # Node restarted without a graceful unregister and its token had rotated.
    again = client.post("/nodes/register", json=body, headers={"X-Network-Auth-Token": "TOKEN-V2"})
    assert again.status_code == 409, "re-registration should still report the conflict"
    assert app.state.registry.get_node_token("node-rotate") == "TOKEN-V2", (
        "Scheduler kept the stale credential after the node rotated it; every "
        "dispatch to this node would 401 until it was evicted"
    )


def test_proxy_falls_back_to_the_fleet_wide_token(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """With no per-node credential, a configured fleet-wide token is used.

    Covers the compatibility path for deployments that predate per-node tokens.
    """
    private_key, _ = key_pair
    asyncio.run(app.state.registry.set_node_token(NODE_ID, None))
    assert app.state.registry.get_node_token(NODE_ID) is None

    captured: dict[str, Any] = {}

    async def fake_post(url: str, **kwargs: Any) -> MagicMock:
        captured["headers"] = kwargs.get("headers")
        return _ok_response()

    settings = get_settings()
    original = settings.network_auth_token
    object.__setattr__(settings, "network_auth_token", "fleet-wide-token")
    try:
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
            response = client.post(
                "/v1/chat/completions",
                json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
                headers=bearer(private_key),
            )
    finally:
        object.__setattr__(settings, "network_auth_token", original)

    assert response.status_code == 200, response.text
    headers = captured.get("headers") or {}
    assert headers.get("X-Network-Auth-Token") == "fleet-wide-token", (
        f"fleet-wide fallback not applied. Sent headers: {headers}"
    )
