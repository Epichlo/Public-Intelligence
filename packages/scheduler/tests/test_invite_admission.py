"""Registration requires an invite code once any exist (decision D4).

`docs/decisions/D4-sybil-resistance.md` decided this and `docs/OPERATING.md` told
operators it was **not implemented** -- which was accurate and is what this closes.

The property that needs the most care is the fallback. Requiring a code
unconditionally would lock every existing deployment out of its own fleet on upgrade,
so with no codes issued registration stays open. That is a silent hole unless
something shouts, which is why `warn_if_open` has its own test: the failure mode here
is not "the check is missing", it is "the check is off and nobody knows".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scheduler.core.config import Settings, get_settings
from scheduler.core.invites import InviteRegistry, generate_code, hash_code
from scheduler.main import create_app
from scheduler.models.node import GPUInfo, Node

TOKEN = "fleet-token"


def _node(node_id: str = "node-1") -> dict[str, object]:
    return Node(
        node_id=node_id,
        hostname="h",
        ip_address="10.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=8,
        ram_total_gb=32.0,
        available_models=["llama3"],
    ).model_dump(mode="json")


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(network_auth_token=TOKEN)
    return TestClient(app)


def _register(client: TestClient, node_id: str = "node-1", code: str | None = None) -> object:
    headers = {"X-Network-Auth-Token": TOKEN}
    if code is not None:
        headers["X-Invite-Code"] = code
    return client.post("/nodes/register", json=_node(node_id), headers=headers)


# --- the fallback, and its warning -----------------------------------------


def test_with_no_codes_issued_registration_stays_open(client: TestClient) -> None:
    """Upgrading must not lock an existing operator out of their own fleet."""
    assert _register(client).status_code == 201


def test_an_open_deployment_says_so_loudly_at_startup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The whole safety of the fallback rests on this.

    An admission check that is off by default is only acceptable if being in that
    state is impossible to miss. Without the warning this is a silent hole with a
    decision record claiming otherwise.
    """
    registry = InviteRegistry()
    with caplog.at_level("WARNING"):
        registry.warn_if_open()

    assert "invite_admission_disabled" in caplog.text
    assert "ANY caller" in caplog.text


async def test_issuing_one_code_switches_enforcement_on() -> None:
    registry = InviteRegistry()
    assert registry.enforcing is False

    await registry.issue(label="alice")
    assert registry.enforcing is True


# --- enforcement -----------------------------------------------------------


async def test_registration_without_a_code_is_refused_once_codes_exist(
    client: TestClient,
) -> None:
    """403, and the node is not admitted."""
    await client.app.state.invites.issue(label="alice")

    response = _register(client)

    assert response.status_code == 403, response.text
    assert client.app.state.registry._nodes == {}


async def test_a_valid_code_admits_the_node(client: TestClient) -> None:
    code, _ = await client.app.state.invites.issue(label="alice")

    assert _register(client, code=code).status_code == 201


async def test_a_wrong_code_is_refused(client: TestClient) -> None:
    await client.app.state.invites.issue(label="alice")

    assert _register(client, code=generate_code()).status_code == 403


async def test_a_single_use_code_admits_exactly_one_node(client: TestClient) -> None:
    """Single-use has to mean single-use, or a leaked code admits a fleet."""
    code, _ = await client.app.state.invites.issue(label="alice")

    assert _register(client, "node-1", code=code).status_code == 201
    assert _register(client, "node-2", code=code).status_code == 403


async def test_a_batch_code_admits_exactly_max_uses(client: TestClient) -> None:
    code, _ = await client.app.state.invites.issue(label="lab", max_uses=2)

    assert _register(client, "node-1", code=code).status_code == 201
    assert _register(client, "node-2", code=code).status_code == 201
    assert _register(client, "node-3", code=code).status_code == 403


async def test_a_failed_registration_does_not_consume_a_use(client: TestClient) -> None:
    """A 409 must not burn the code.

    Otherwise a node retrying after a transient conflict -- which ROADMAP 1.6 made
    routine, since a node re-registers whenever its heartbeat 404s -- would spend
    its operator's invite and lock itself out.
    """
    code, invite = await client.app.state.invites.issue(label="alice", max_uses=2)

    assert _register(client, "node-1", code=code).status_code == 201
    assert _register(client, "node-1", code=code).status_code == 409

    assert invite.uses == 1, "the conflicting re-registration consumed an invite use"


# --- revocation ------------------------------------------------------------


async def test_revoking_stops_future_registrations(client: TestClient) -> None:
    code, _ = await client.app.state.invites.issue(label="alice", max_uses=5)
    assert _register(client, "node-1", code=code).status_code == 201

    assert await client.app.state.invites.revoke(code) is True
    assert _register(client, "node-2", code=code).status_code == 403


async def test_revoking_does_not_evict_nodes_already_admitted(client: TestClient) -> None:
    """Deliberate. Conflating the two makes revocation too dangerous to use.

    Eviction already exists as `DELETE /nodes/{id}` and reports what it did
    (ROADMAP 2.5). Revocation is about the future.
    """
    code, _ = await client.app.state.invites.issue(label="alice", max_uses=5)
    _register(client, "node-1", code=code)

    await client.app.state.invites.revoke(code)

    assert "node-1" in client.app.state.registry._nodes


async def test_revoking_reports_whether_it_changed_anything() -> None:
    """Same distinction ROADMAP 2.5 made eviction report: did it, or was it already?"""
    registry = InviteRegistry()
    code, _ = await registry.issue()

    assert await registry.revoke(code) is True
    assert await registry.revoke(code) is False, "a second revoke must report no change"
    assert await registry.revoke(generate_code()) is False


# --- what is stored --------------------------------------------------------


async def test_the_code_itself_is_never_stored() -> None:
    """A bearer credential at rest is a bearer credential leaked with the database."""
    registry = InviteRegistry()
    code, invite = await registry.issue(label="alice")

    assert code not in invite.model_dump_json()
    assert invite.code_hash == hash_code(code)


async def test_the_operator_summary_exposes_no_code_or_hash() -> None:
    """The hash is not the code, but it is still a verifier -- and nothing needs it.

    A summary endpoint that returns hashes lets anyone who reads it check candidate
    codes offline.
    """
    registry = InviteRegistry()
    code, invite = await registry.issue(label="alice")

    rendered = str(registry.summary())
    assert code not in rendered
    assert invite.code_hash not in rendered
    assert "alice" in rendered
