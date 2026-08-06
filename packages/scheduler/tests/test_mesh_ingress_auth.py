"""Nothing unauthenticated may change registry state (ROADMAP 2.7).

Zenoh links are plaintext and the bootstrap router is public, so reaching the mesh
is not a privilege. Before this, all three ingress paths were forgeable:

  telemetry  -- signed with a key whose default is published in this repo
  heartbeat  -- plain JSON, no signature at all
  liveliness -- no payload to sign, and a DELETE unregistered whatever node id the
                publisher named

See specs/authenticated-mesh-ingress.md.
"""

import json
import time
from datetime import UTC, datetime

import pytest

from scheduler.core.mesh_auth import PURPOSE_HEARTBEAT, PURPOSE_TELEMETRY, seal
from scheduler.core.zenoh_router import ZenohRouter
from scheduler.models.node import GPUInfo, Node
from scheduler.registry.node_registry import NodeRegistry

NODE_ID = "node-1"
TOKEN = "per-install-credential-abc123"
OLD_SHARED_KEY = "pi_telemetry_secure_default_secret_key"

HEARTBEAT_TOPIC = f"public-intelligence/net/{NODE_ID}/heartbeat"
TELEMETRY_TOPIC = f"public-intelligence/net/nodes/{NODE_ID}/telemetry"


def make_node(node_id: str = NODE_ID) -> Node:
    return Node(
        node_id=node_id,
        hostname=f"{node_id}.local",
        ip_address="127.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3"],
    )


def heartbeat_payload(node_id: str = NODE_ID) -> dict:
    return {
        "node_id": node_id,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "status": "online",
        "queue_length": 2,
        "cpu_utilization": 12.0,
        "ram_available_gb": 40.0,
        "gpu_utilization": 30.0,
        "vram_available_gb": 18.0,
    }


def telemetry_payload(node_id: str = NODE_ID, **extra) -> dict:
    return {
        "node_id": node_id,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "cpu_utilization": 5.0,
        "ram_usage_bytes": 1024,
        **extra,
    }


@pytest.fixture
async def registry() -> NodeRegistry:
    """A registry holding one registered node and its credential."""
    reg = NodeRegistry()
    await reg.set_node_token(NODE_ID, TOKEN)
    await reg.register(make_node())
    return reg


@pytest.fixture
def router(registry: NodeRegistry) -> ZenohRouter:
    """A router bound to that registry. No Zenoh session is opened."""
    return ZenohRouter(registry)


# --- telemetry --------------------------------------------------------------


@pytest.mark.anyio
async def test_telemetry_signed_with_the_nodes_own_token_is_accepted(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    raw = seal(
        telemetry_payload(reliability_score=0.9),
        node_id=NODE_ID,
        token=TOKEN,
        purpose=PURPOSE_TELEMETRY,
    )

    await router._process_telemetry(raw, TELEMETRY_TOPIC)

    assert registry._telemetry[NODE_ID]["reliability_score"] == 0.9
    assert registry.is_mesh_reachable(NODE_ID)


@pytest.mark.anyio
async def test_telemetry_signed_with_the_old_published_key_is_rejected(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    """The whole point of 2.7. That constant is in this repo's git history.

    `reliability_score` is what `matchmaker.score_nodes` ranks on, so accepting
    this is accepting "send every request to my node".
    """
    raw = seal(
        telemetry_payload(reliability_score=999.0),
        node_id=NODE_ID,
        token=OLD_SHARED_KEY,
        purpose=PURPOSE_TELEMETRY,
    )

    await router._process_telemetry(raw, TELEMETRY_TOPIC)

    assert NODE_ID not in registry._telemetry


@pytest.mark.anyio
async def test_unsigned_telemetry_is_rejected(router: ZenohRouter, registry: NodeRegistry) -> None:
    await router._process_telemetry(json.dumps(telemetry_payload()), TELEMETRY_TOPIC)

    assert NODE_ID not in registry._telemetry


# --- heartbeats -------------------------------------------------------------


@pytest.mark.anyio
async def test_heartbeat_signed_with_the_nodes_own_token_is_accepted(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    raw = seal(heartbeat_payload(), node_id=NODE_ID, token=TOKEN, purpose=PURPOSE_HEARTBEAT)

    await router._process_heartbeat(raw, HEARTBEAT_TOPIC)

    stored = await registry.get_heartbeat(NODE_ID)
    assert stored is not None
    assert stored.queue_length == 2


@pytest.mark.anyio
async def test_a_plain_json_heartbeat_is_rejected(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    """This is what the node used to publish and the Scheduler used to accept.

    `filter_nodes` compares the heartbeat's `vram_available_gb` against a task's
    `min_vram_gb`, so forging one moves a node in or out of every dispatch.
    """
    await router._process_heartbeat(json.dumps(heartbeat_payload()), HEARTBEAT_TOPIC)

    assert await registry.get_heartbeat(NODE_ID) is None


@pytest.mark.anyio
async def test_a_heartbeat_for_a_purpose_it_was_not_sealed_for_is_rejected(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    """Separate subkeys per purpose: a telemetry envelope is not a heartbeat."""
    raw = seal(heartbeat_payload(), node_id=NODE_ID, token=TOKEN, purpose=PURPOSE_TELEMETRY)

    await router._process_heartbeat(raw, HEARTBEAT_TOPIC)

    assert await registry.get_heartbeat(NODE_ID) is None


# --- identity binding -------------------------------------------------------


@pytest.mark.anyio
async def test_a_valid_envelope_replayed_on_another_nodes_topic_is_rejected(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    """A host holds its own credential, so it can mint envelopes -- for itself.

    What actually stops this is STRUCTURAL: the Scheduler derives the key from the
    node that OWNS THE TOPIC, so an envelope minted with node-1's credential can
    never open under node-2's. The node id in the AEAD associated data and the
    explicit field check are defence in depth on top of that -- verified by
    mutation: removing both of them together leaves this test green, because the
    key lookup alone rejects the envelope. They guard against a future change that
    reintroduced shared keys, not against today's attacker.
    """
    await registry.set_node_token("node-2", "a-different-credential")
    await registry.register(make_node("node-2"))

    raw = seal(
        telemetry_payload(node_id=NODE_ID), node_id=NODE_ID, token=TOKEN, purpose=PURPOSE_TELEMETRY
    )

    await router._process_telemetry(raw, "public-intelligence/net/nodes/node-2/telemetry")

    assert "node-2" not in registry._telemetry


@pytest.mark.anyio
async def test_messages_for_an_unknown_node_are_dropped_not_raised(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    """The Scheduler has no key for a node it has never registered.

    After 1.6 that node re-registers on a jittered backoff, so the window is
    bounded and self-healing. Accepting unverifiable data to cover it would reopen
    the hole this change closes.
    """
    raw = seal(
        telemetry_payload(node_id="ghost"),
        node_id="ghost",
        token="whatever",
        purpose=PURPOSE_TELEMETRY,
    )

    await router._process_telemetry(raw, "public-intelligence/net/nodes/ghost/telemetry")

    assert "ghost" not in registry._telemetry
    assert not registry.is_mesh_reachable("ghost")


# --- liveliness may no longer evict -----------------------------------------


@pytest.mark.anyio
async def test_a_liveliness_deathrattle_cannot_evict_a_live_node(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    """The most severe of the three holes.

    `node_id` came from `parts[3]` of a key expression the PUBLISHER chose, and a
    DELETE called `unregister_node`. Declaring a liveliness token for someone
    else's node id and dropping it evicted that host from the network.
    """
    raw = seal(heartbeat_payload(), node_id=NODE_ID, token=TOKEN, purpose=PURPOSE_HEARTBEAT)
    await router._process_heartbeat(raw, HEARTBEAT_TOPIC)

    await router._process_deathrattle(NODE_ID, f"public-intelligence/net/liveliness/{NODE_ID}")

    assert await registry.exists(NODE_ID), "an unauthenticated signal evicted a live node"


@pytest.mark.anyio
async def test_liveliness_alone_does_not_make_a_node_mesh_reachable(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    """Marking reachability from an unsigned signal costs a real request.

    Dispatch prefers the mesh for a node it believes is there, then waits
    `mesh_inference_first_reply_timeout_seconds` for a queryable that does not
    exist before falling back to HTTP.
    """
    await router._process_liveliness_alive(NODE_ID, f"public-intelligence/net/liveliness/{NODE_ID}")

    assert not registry.is_mesh_reachable(NODE_ID)


# --- eviction is time-based and authenticated -------------------------------


@pytest.mark.anyio
async def test_a_node_with_no_recent_verified_heartbeat_is_swept(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    """This is the mechanism ROADMAP 2.5 claimed already existed. It did not."""
    router.node_stale_after_seconds = 0.0

    await router._sweep_stale_nodes()

    assert not await registry.exists(NODE_ID)


@pytest.mark.anyio
async def test_a_node_heartbeating_normally_survives_the_sweep(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    router.node_stale_after_seconds = 90.0
    raw = seal(heartbeat_payload(), node_id=NODE_ID, token=TOKEN, purpose=PURPOSE_HEARTBEAT)
    await router._process_heartbeat(raw, HEARTBEAT_TOPIC)

    await router._sweep_stale_nodes()

    assert await registry.exists(NODE_ID)


@pytest.mark.anyio
async def test_a_deathrattle_makes_the_sweep_evict_a_node_that_really_is_gone(
    router: ZenohRouter, registry: NodeRegistry
) -> None:
    """An unauthenticated signal may accelerate a check, never perform a write.

    A node with no recent verified heartbeat is gone either way; the deathrattle
    only means the sweep reaches that conclusion now rather than at its next tick.
    """
    router.node_stale_after_seconds = 60.0
    router._last_verified_heartbeat[NODE_ID] = time.monotonic() - 3600.0

    await router._process_deathrattle(NODE_ID, f"public-intelligence/net/liveliness/{NODE_ID}")

    assert not await registry.exists(NODE_ID)


# --- the old shared secret is gone ------------------------------------------


def test_the_fleet_wide_secret_is_no_longer_used_anywhere() -> None:
    """A setting that no longer does anything is worse than no setting.

    An operator who set `TELEMETRY_SECRET_KEY` would believe they had configured
    something. Removed from both services and every install path.

    Matches USE -- an env lookup `"TELEMETRY_SECRET_KEY"` or an env-file assignment
    `TELEMETRY_SECRET_KEY=` -- not the bare name, because several files now explain
    in prose what this used to be and why it went. Forbidding the name would delete
    the explanation. Same reasoning as the archived-repo check in
    tests/test_installer_paths.py.
    """
    import re as _re
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    used = _re.compile(r'"TELEMETRY_SECRET_KEY"|TELEMETRY_SECRET_KEY\s*=')
    targets = [
        *(repo_root / "packages").rglob("*.py"),
        repo_root / "install.sh",
        repo_root / "install.ps1",
        repo_root / "docker-compose.test.yml",
    ]

    offenders = sorted(
        str(p.relative_to(repo_root))
        for p in targets
        if p.is_file()
        and ".venv" not in p.parts
        and p.name != Path(__file__).name
        and used.search(p.read_text(encoding="utf-8"))
    )

    assert not offenders, f"TELEMETRY_SECRET_KEY is still used in: {offenders}"
