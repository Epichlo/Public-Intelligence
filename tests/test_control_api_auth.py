"""Regression tests proving the Node's control and inference routes require auth.

Until 2026-08-02 every route on the Node was unauthenticated while the server
bound 0.0.0.0 by default. Anyone able to reach the port could stop the node
(`POST /api/v1/node/control`), read its sandbox logs, or spend its GPU
(`POST /infer`).

These tests fail if any protected route stops requiring `X-Network-Auth-Token`,
and they pin the fail-closed behaviour: a node with no token configured must
reject rather than serve.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from node.core.configuration import Settings, get_settings
from node.main import app

# Opt out of conftest's auth bypass -- this module must exercise the real thing.
pytestmark = pytest.mark.real_auth

TOKEN = "test-node-secret-token"

# (method, path, json body). Every one of these must require the credential.
PROTECTED_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v1/node/telemetry", None),
    ("POST", "/api/v1/node/control", {"action": "stop"}),
    ("GET", "/api/v1/sandbox/logs", None),
    ("GET", "/api/v1/sandbox/logs/stream?max_events=1", None),
    ("POST", "/infer", {"model": "llama3", "prompt": "hi"}),
    ("GET", "/models", None),
]

# Deliberately open: container HEALTHCHECK and liveness probes call these
# without credentials. Pinned so they are not locked down by accident.
OPEN_ROUTES: list[str] = ["/health", "/health/ready"]


def _client() -> TestClient:
    """Build a client that surfaces handler errors as 500 rather than raising.

    These tests assert only whether a request was turned away at the
    authentication layer. What a handler does afterwards is out of scope -- and
    other modules in this suite leave mocks on `app.state`, so an authenticated
    /infer can fail response validation. Letting that surface as a status keeps
    the assertion about auth instead of about leaked fixtures.
    """
    return TestClient(app, raise_server_exceptions=False)


def _settings(token: str | None) -> Settings:
    """Build a Settings instance carrying the given auth token."""
    return Settings(network_auth_token=token)


@pytest.fixture
def configured() -> Iterator[TestClient]:
    """Client for a node that has an auth token configured."""
    app.dependency_overrides[get_settings] = lambda: _settings(TOKEN)
    try:
        yield _client()
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def unconfigured() -> Iterator[TestClient]:
    """Client for a node with no auth token configured at all."""
    app.dependency_overrides[get_settings] = lambda: _settings(None)
    try:
        yield _client()
    finally:
        app.dependency_overrides.pop(get_settings, None)


def _call(client: TestClient, method: str, path: str, body: Any, headers: dict[str, str]):
    """Issue a request against a route regardless of verb."""
    if method == "POST":
        return client.post(path, json=body, headers=headers)
    return client.get(path, headers=headers)


@pytest.mark.parametrize(("method", "path", "body"), PROTECTED_ROUTES)
def test_missing_credential_is_rejected(
    configured: TestClient, method: str, path: str, body: Any
) -> None:
    """A request with no X-Network-Auth-Token must never reach the handler."""
    response = _call(configured, method, path, body, {})
    assert response.status_code in (401, 403), (
        f"UNAUTHENTICATED ACCESS: {method} {path} returned {response.status_code}"
    )


@pytest.mark.parametrize(("method", "path", "body"), PROTECTED_ROUTES)
def test_wrong_credential_is_rejected(
    configured: TestClient, method: str, path: str, body: Any
) -> None:
    """A request bearing the wrong token must be rejected."""
    response = _call(configured, method, path, body, {"X-Network-Auth-Token": "wrong"})
    assert response.status_code in (401, 403), (
        f"BAD CREDENTIAL ACCEPTED: {method} {path} returned {response.status_code}"
    )


@pytest.mark.parametrize(("method", "path", "body"), PROTECTED_ROUTES)
def test_unconfigured_node_fails_closed(
    unconfigured: TestClient, method: str, path: str, body: Any
) -> None:
    """A node with no token configured must reject, not serve openly.

    This is the deliberate difference from Scheduler's verify_auth_token, which
    returns successfully when no token is set. On a 0.0.0.0-bound control API
    that behaviour is the vulnerability itself.
    """
    response = _call(unconfigured, method, path, body, {"X-Network-Auth-Token": "anything"})
    assert response.status_code in (401, 403), (
        f"FAILED OPEN: {method} {path} served a request with no token configured "
        f"(status {response.status_code})"
    )


@pytest.mark.parametrize(("method", "path", "body"), PROTECTED_ROUTES)
def test_valid_credential_is_accepted(
    configured: TestClient, method: str, path: str, body: Any
) -> None:
    """Positive control: the correct token must still get through.

    Guards against 'fixing' this by rejecting everything. The handler may still
    fail downstream (no Ollama, no runtime), so this asserts only that the
    request was not turned away at the authentication layer.
    """
    response = _call(configured, method, path, body, {"X-Network-Auth-Token": TOKEN})
    assert response.status_code not in (401, 403), (
        f"valid credential rejected at {method} {path}: {response.text[:200]}"
    )


@pytest.mark.parametrize("path", OPEN_ROUTES)
def test_health_routes_stay_open(configured: TestClient, path: str) -> None:
    """Health probes must keep working without a credential."""
    response = configured.get(path)
    assert response.status_code not in (401, 403), (
        f"{path} now requires auth; container healthchecks and liveness probes "
        "call it without credentials"
    )
