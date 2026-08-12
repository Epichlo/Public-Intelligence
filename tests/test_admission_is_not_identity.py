"""Two nodes registering against one Scheduler must not end up sharing a key.

ROADMAP W7 / decision D9. `POST /nodes/register` read one header and used it twice:
`verify_auth_token` compared it against the fleet secret, and `register_node` stored
it as *that node's own* credential. Both cannot hold. If it must equal the fleet
secret to be admitted, then every node's "per-node" credential IS the fleet secret.

That is not a tidiness complaint. ROADMAP 2.7 keyed every state-changing mesh message
on the node's own credential specifically so one host could not forge messages as
another -- its own summary says it closes "the insider case a fleet-wide secret never
could". With a fleet token configured, which every real deployment needs or `/nodes`
and `/metrics` serve anyone, that property silently did not hold.

The first test below is the one that was false before D9. The rest exist because the
obvious fix -- store the new header instead of the old one -- breaks every node that
has already registered.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scheduler.registry.node_registry import NodeRegistry

FLEET_TOKEN = "fleet-secret-shared-by-every-host"


def _node_payload(node_id: str) -> dict[str, object]:
    return {
        "node_id": node_id,
        "hostname": "localhost",
        "ip_address": "127.0.0.1",
        "region": "local",
        "gpu": {"name": "cpu-only", "vram_total_gb": 0.0, "vram_available_gb": 0.0},
        "cpu_cores": 4,
        "ram_total_gb": 16.0,
        "available_models": ["llama3.2:1b"],
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A Scheduler with a fleet token set -- the configuration that has the bug.

    The teardown is not tidiness. `get_settings` is `lru_cache`d, so clearing it and
    then constructing settings under a fleet token leaves that cached object in place
    for the rest of the process -- and `monkeypatch` restoring the env var does not
    touch the cache. Without the clear on the way out, five later tests in
    `tests/test_phase4_5_e2e.py` failed with 401s that had nothing to do with them.
    """
    monkeypatch.setenv("SCHEDULER_NETWORK_AUTH_TOKEN", FLEET_TOKEN)
    monkeypatch.setenv("SCHEDULER_DATABASE_PATH", "")

    from scheduler.core.config import get_settings
    from scheduler.main import create_app

    get_settings.cache_clear()
    try:
        yield TestClient(create_app())
    finally:
        get_settings.cache_clear()


def _stored_credential(client: TestClient, node_id: str) -> str | None:
    """What the Scheduler retained for this node -- the value under test.

    `TestClient.app` is typed as a bare ASGI callable, which has no `.state`, so the
    cast is what lets mypy see the registry. Read through the real registry rather
    than the response body on purpose: the credential is deliberately not echoed
    back, so a test that read the response would pass against a Scheduler that
    stored nothing at all.
    """
    app = cast(FastAPI, client.app)
    registry: NodeRegistry = app.state.registry
    return registry.get_node_token(node_id)


def _register(client: TestClient, node_id: str, credential: str | None) -> int:
    headers = {"X-Network-Auth-Token": FLEET_TOKEN}
    if credential is not None:
        headers["X-Node-Credential"] = credential
    response = client.post("/nodes/register", json=_node_payload(node_id), headers=headers)
    return response.status_code


def test_two_nodes_do_not_share_one_credential(client: TestClient) -> None:
    """The property D9 exists to restore, and the one that was false.

    Both hosts present the fleet token to be admitted -- they must, it is the
    admission check -- and each presents its own credential separately. What the
    Scheduler retains must be the latter.
    """
    assert _register(client, "node-a", "secret-belonging-to-a") == 201
    assert _register(client, "node-b", "secret-belonging-to-b") == 201

    assert _stored_credential(client, "node-a") == "secret-belonging-to-a"
    assert _stored_credential(client, "node-b") == "secret-belonging-to-b"


def test_the_stored_credential_is_never_the_fleet_token(client: TestClient) -> None:
    """Stated separately because it is the actual security claim.

    A node whose stored key equals the fleet secret can be impersonated by anyone
    holding that secret -- which is every other host.
    """
    assert _register(client, "node-a", "secret-belonging-to-a") == 201

    assert _stored_credential(client, "node-a") != FLEET_TOKEN


def test_admission_still_requires_the_fleet_token(client: TestClient) -> None:
    """Separating the two meanings must not weaken the check that remains.

    A node presenting only its own credential is not admitted: knowing a secret you
    invented is not evidence of anything.
    """
    response = client.post(
        "/nodes/register",
        json=_node_payload("node-impostor"),
        headers={"X-Node-Credential": "i-made-this-up"},
    )
    assert response.status_code == 401


def test_a_node_that_sends_no_credential_still_registers(client: TestClient) -> None:
    """Backwards compatibility, deliberately kept -- see D9's "cost, stated".

    Every host registered before D9 sends only the admission header. Refusing them
    would strand a running fleet, so the old behaviour survives as a fallback: the
    admission token is stored, exactly as it was.
    """
    assert _register(client, "node-legacy", None) == 201

    assert _stored_credential(client, "node-legacy") == FLEET_TOKEN


@pytest.mark.anyio
async def test_the_node_client_sends_two_different_secrets() -> None:
    """The Scheduler half is useless if the node never sends the new header.

    Exercised rather than grepped. W9 measured what a source-reading assertion is
    worth: with the bug reintroduced, four of five file-reading checks still passed
    and only the one that constructed the object caught it. So this drives a real
    `SchedulerClient` and reads the headers it actually put on the wire.
    """
    from unittest.mock import AsyncMock

    import httpx
    from node.clients.scheduler import SchedulerClient
    from node.core.configuration import Settings

    settings = Settings(
        node_id="node-a",
        scheduler_url="http://scheduler:8080",
        network_auth_token="secret-belonging-to-a",
        fleet_token=FLEET_TOKEN,
    )
    transport = AsyncMock()
    request = httpx.Request("DELETE", "http://scheduler:8080/nodes/node-a")
    transport.request.return_value = httpx.Response(200, request=request)

    await SchedulerClient(settings, client=transport).unregister("node-a")

    headers = transport.request.call_args.kwargs["headers"]
    assert headers["X-Network-Auth-Token"] == FLEET_TOKEN
    assert headers["X-Node-Credential"] == "secret-belonging-to-a"


@pytest.mark.anyio
async def test_one_secret_configured_still_sends_it_as_both() -> None:
    """The other half of the fallback, from the node's side.

    An operator who sets only `NODE_NETWORK_AUTH_TOKEN` -- every install before D9,
    and every install against a Scheduler with no fleet token -- must still be
    admitted. `fleet_token` unset means "reuse the one secret I have", not "send
    nothing and get a 401".
    """
    from unittest.mock import AsyncMock

    import httpx
    from node.clients.scheduler import SchedulerClient
    from node.core.configuration import Settings

    settings = Settings(
        node_id="node-legacy",
        scheduler_url="http://scheduler:8080",
        network_auth_token="the-only-secret-i-have",
    )
    transport = AsyncMock()
    request = httpx.Request("DELETE", "http://scheduler:8080/nodes/node-legacy")
    transport.request.return_value = httpx.Response(200, request=request)

    await SchedulerClient(settings, client=transport).unregister("node-legacy")

    headers = transport.request.call_args.kwargs["headers"]
    assert headers["X-Network-Auth-Token"] == "the-only-secret-i-have"
    assert headers["X-Node-Credential"] == "the-only-secret-i-have"
