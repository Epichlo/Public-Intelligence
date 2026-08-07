"""What the Scheduler tells a stranger (ROADMAP 2.6).

Most of the API answered anyone who could reach it, including `/nodes/telemetry`,
which returns live decrypted metrics for the entire fleet -- the same data ROADMAP
2.7 had just spent a protocol change protecting in transit.

The last test in this file is the one with lasting value: every gap fixed here
existed because a route was added without anyone asking what guarded it, and a
table in a spec cannot notice the next one.

See specs/authenticate-the-read-surface.md.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from scheduler.core.config import Settings, get_settings
from scheduler.main import create_app
from scheduler.models.node import GPUInfo, Node

TOKEN = "network-token-for-tests"

# Routes that answer without a credential, ON PURPOSE. Anything unguarded and not
# on this list fails `test_no_route_is_unauthenticated_by_accident`.
DELIBERATELY_PUBLIC = {
    # Liveness and readiness probes. Render calls these with no credential, and a
    # health check that needs a secret reports "unhealthy" when the secret is wrong.
    ("GET", "/health"),
    ("GET", "/health/ready"),
    # Marketplace discovery: a set of model NAMES aggregated across the fleet. Not
    # which node has what, not hardware, not addresses. A developer deciding whether
    # to obtain a credential should be able to see what the network can serve.
    ("GET", "/v1/models"),
    ("GET", "/v1/models/{model_id}"),
}

GUARDED_READS = [
    "/nodes",
    "/nodes/node-1",
    "/nodes/telemetry",
    "/nodes/node-1/telemetry",
    "/status",
]


@pytest.fixture
def settings() -> Settings:
    return Settings(network_auth_token=TOKEN)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture
def client_with_node(client: TestClient) -> TestClient:
    """A client whose registry holds one node, so 200s are reachable."""
    node = Node(
        node_id="node-1",
        hostname="node-1.local",
        ip_address="127.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3"],
    )
    response = client.post(
        "/nodes/register", json=node.model_dump(), headers={"X-Network-Auth-Token": TOKEN}
    )
    assert response.status_code == 201
    client.app.state.registry._telemetry["node-1"] = {"cpu_utilization": 12.0}
    return client


# --- the fleet is no longer public ------------------------------------------


@pytest.mark.parametrize("path", GUARDED_READS)
def test_a_fleet_read_without_a_credential_is_refused(
    client_with_node: TestClient, path: str
) -> None:
    """Hostnames, addresses, GPU models, catalogues and live metrics.

    Their siblings in the same routers -- register, update-models, unregister --
    were already guarded. Three protected routes and two open ones in one file is
    not a policy, it is an oversight with a pattern.
    """
    assert client_with_node.get(path).status_code == 401


@pytest.mark.parametrize("path", GUARDED_READS)
def test_the_same_read_works_with_a_credential(client_with_node: TestClient, path: str) -> None:
    """Closing a route is only correct if the legitimate caller still gets through."""
    response = client_with_node.get(path, headers={"X-Network-Auth-Token": TOKEN})

    assert response.status_code == 200


def test_fleet_telemetry_is_the_one_that_mattered_most(client_with_node: TestClient) -> None:
    """`/nodes/telemetry` returns the whole `_telemetry` dict for every node.

    ROADMAP 2.6's own line did not mention it. Authenticating the mesh so that only
    a node can report its own metrics, while serving those same metrics to anyone
    over HTTP, would have been half a fix.
    """
    refused = client_with_node.get("/nodes/telemetry")
    allowed = client_with_node.get("/nodes/telemetry", headers={"X-Network-Auth-Token": TOKEN})

    assert refused.status_code == 401
    assert allowed.json()["node-1"]["cpu_utilization"] == 12.0


def test_the_autonomous_orchestrator_and_its_webhook_are_gone() -> None:
    """ROADMAP 2.10. Both were deleted rather than made honest.

    `AutonomousOrchestrator.execute_mission` returned `verification_passed=True` and
    a PR body reading "Closed-loop tri-factor verification (pytest, ruff, mypy)
    passed cleanly" -- for a stub that formatted strings and ran none of them. Its
    only caller was `POST /v1/webhooks/github`, which `create_app` never mounted.

    The prior question was whether either belonged in v1 at all, and ROADMAP's own
    "deliberately not in v1" list already answered it: the autonomous agent
    orchestrator is on that list. So the fix was deletion, not a truthful stub.
    Making the claim accurate would have left ~170 lines of unreachable code whose
    purpose is a feature this product has decided not to have.

    This test is the ratchet: it fails if either module comes back.
    """
    for module in (
        "scheduler.core.autonomous_orchestrator",
        "scheduler.api.webhooks",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)

    assert not any(getattr(r, "path", "").startswith("/v1/webhooks") for r in create_app().routes)


# --- what stays public, and why ---------------------------------------------


@pytest.mark.parametrize("path", ["/health", "/health/ready"])
def test_probes_still_answer_without_a_credential(client: TestClient, path: str) -> None:
    """Deliberate. A probe that needs a secret reports unhealthy when it is wrong."""
    assert client.get(path).status_code == 200


def test_model_discovery_stays_public_as_a_decision(client_with_node: TestClient) -> None:
    """DELIBERATE, not an omission -- which is why it has a test rather than a gap.

    The product is a marketplace. What this returns is a set of model NAMES
    aggregated across the fleet: not which node has what, not hardware, not
    addresses. That is a materially smaller disclosure than `/nodes`, which is why
    the two are treated differently. If that judgement is ever reversed, this test
    is what has to be changed on purpose.
    """
    response = client_with_node.get("/v1/models")

    assert response.status_code == 200
    assert [m["id"] for m in response.json()["data"]] == ["llama3"]


# --- the ratchet ------------------------------------------------------------


def _guards_of(dependant: object) -> set[str]:
    """Auth dependencies anywhere in a route's dependency tree.

    Module-level rather than a closure inside the walk loop: defining it in the loop
    made it bind a loop variable (ruff B023), which is the shape of bug where a
    later refactor silently collects the wrong route's guards.
    """
    guards: set[str] = set()
    for sub in getattr(dependant, "dependencies", []):
        name = getattr(getattr(sub, "call", None), "__name__", "")
        if name in {"verify_auth_token", "verify_jwt"}:
            guards.add(name)
        guards |= _guards_of(sub)
    return guards


def _mounted_routes(app: object) -> list[tuple[str, str, set[str]]]:
    """Return (method, path, guards) for every route reachable from `app`.

    FastAPI 0.141 keeps included routers as `_IncludedRouter` wrappers rather than
    flattening them into `app.routes`, so a naive walk over `app.routes` finds only
    the four default docs routes. The first version of this test did exactly that,
    found nothing, and PASSED -- an inventory test that inventories nothing is worse
    than no test, because it reads like coverage. Hence `original_router`, and hence
    the sanity assertion in the caller.
    """
    collected: list[tuple[str, str, set[str]]] = []

    def walk_routes(routes: object) -> None:
        for route in routes or []:  # type: ignore[union-attr]
            inner = getattr(route, "original_router", None)
            if inner is not None:
                walk_routes(getattr(inner, "routes", []))
                continue

            path = getattr(route, "path", None)
            dependant = getattr(route, "dependant", None)
            if not path or dependant is None:
                continue

            guards = _guards_of(dependant)
            for method in (getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}:
                collected.append((method, path, guards))

    walk_routes(getattr(app, "routes", []))
    return collected


def test_the_route_inventory_actually_finds_routes() -> None:
    """Guards the guard. Without this, a FastAPI internals change silently
    turns the ratchet below into a no-op that always passes -- which is exactly
    what happened when this file was first written.
    """
    found = {(m, p) for m, p, _ in _mounted_routes(create_app())}

    assert ("GET", "/nodes") in found, f"route inventory looks broken; found {sorted(found)}"
    assert ("POST", "/v1/chat/completions") in found
    assert len(found) > 10


def test_no_route_is_unauthenticated_by_accident() -> None:
    """Every gap fixed here existed because nobody asked what guarded a new route.

    A list in a spec cannot notice the next one. This walks the real dependency
    tree of every mounted route and fails if an unguarded one appears that is not
    on `DELIBERATELY_PUBLIC` -- so adding a public route becomes a decision someone
    writes down, rather than a default nobody sees.
    """
    unguarded = sorted(
        (m, p)
        for m, p, guards in _mounted_routes(create_app())
        if not guards and (m, p) not in DELIBERATELY_PUBLIC
    )

    assert not unguarded, (
        "These routes take no authentication dependency and are not on the "
        f"DELIBERATELY_PUBLIC allowlist: {unguarded}. Either guard them, or add "
        "them to the allowlist with a comment saying why they are public."
    )
