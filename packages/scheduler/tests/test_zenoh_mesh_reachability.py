"""The router must learn which nodes are on the mesh, from traffic it actually receives.

Dispatch will only query a node over Zenoh if the registry says it has been seen there.
Nothing sets that flag today, so without these paths the mesh transport would never be
used and every request would keep dialling `ip_address`.

Each signal below is independent on purpose: a node that publishes heartbeats but whose
telemetry emitter failed, or one seen only via its liveliness token, is still reachable.
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest
import zenoh

from scheduler.core.mesh_auth import PURPOSE_HEARTBEAT, PURPOSE_TELEMETRY, seal
from scheduler.core.zenoh_router import ZenohRouter
from scheduler.models.node import GPUInfo, Node
from scheduler.registry.node_registry import NodeRegistry

NODE_ID = "node-on-the-mesh"


TOKEN = "per-install-credential-for-tests"


def _node(node_id: str = NODE_ID) -> Node:
    return Node(
        node_id=node_id,
        hostname="host",
        ip_address="127.0.0.1",
        region="local",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=8,
        ram_total_gb=32.0,
        available_models=["llama3"],
    )


def _router(registry: NodeRegistry) -> ZenohRouter:
    """A router with no Zenoh session -- these tests drive its callbacks directly."""
    config = zenoh.Config()
    config.insert_json5("scouting/multicast/enabled", "false")
    # Explicit IPv4 loopback listener -- see test_zenoh_integration.py. The zenoh
    # default is `tcp/[::]:0`, an IPv6 wildcard, which is EAFNOSUPPORT on an
    # IPv4-only host. Assertions unchanged; the environment assumption is now stated.
    config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:0"]')
    return ZenohRouter(registry, config=config)


def _telemetry_envelope(node_id: str, token: str = TOKEN) -> str:
    """Build a telemetry envelope the router will accept, as the Node emitter does.

    Sealed with the node's OWN credential since ROADMAP 2.7. This used to derive
    keys from a fleet-wide `TELEMETRY_SECRET_KEY` whose default was a constant
    published in this repository.
    """
    return seal(
        {"node_id": node_id, "timestamp": datetime.now(UTC).isoformat(), "gpu_utilization": 12.0},
        node_id=node_id,
        token=token,
        purpose=PURPOSE_TELEMETRY,
    )


class FakeLivelinessSample:
    """Stands in for a zenoh liveliness sample."""

    def __init__(self, node_id: str, kind: Any) -> None:
        self.key_expr = f"public-intelligence/net/liveliness/{node_id}"
        self.kind = kind


@pytest.mark.asyncio
async def test_zenoh_heartbeat_marks_the_node_reachable() -> None:
    """A heartbeat arriving over Zenoh proves the node holds a live session."""
    registry = NodeRegistry()
    await registry.set_node_token(NODE_ID, TOKEN)
    await registry.register(_node())
    router = _router(registry)

    # Sealed with the node's own credential since ROADMAP 2.7. A plain-JSON
    # heartbeat -- which is what this test used to send, and what the node used to
    # publish -- is now dropped.
    payload = seal(
        {
            "node_id": NODE_ID,
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "online",
            "queue_length": 0,
            "cpu_utilization": 10.0,
            "ram_available_gb": 8.0,
            "gpu_utilization": 0.0,
            "vram_available_gb": 4.0,
        },
        node_id=NODE_ID,
        token=TOKEN,
        purpose=PURPOSE_HEARTBEAT,
    )
    await router._process_heartbeat(payload, f"public-intelligence/net/{NODE_ID}/heartbeat")

    assert registry.is_mesh_reachable(NODE_ID) is True


@pytest.mark.asyncio
async def test_telemetry_marks_the_node_reachable() -> None:
    """Telemetry is a second independent signal, for a node whose heartbeat path failed."""
    registry = NodeRegistry()
    await registry.set_node_token(NODE_ID, TOKEN)
    await registry.register(_node())
    router = _router(registry)

    await router._process_telemetry(
        _telemetry_envelope(NODE_ID),
        f"public-intelligence/net/nodes/{NODE_ID}/telemetry",
    )

    assert registry.is_mesh_reachable(NODE_ID) is True


@pytest.mark.asyncio
async def test_rejected_telemetry_does_not_mark_the_node_reachable() -> None:
    """A forged envelope must not be able to make a node look reachable."""
    registry = NodeRegistry()
    await registry.register(_node())
    router = _router(registry)

    forged = json.dumps({"iv": "AAAA", "ciphertext": "BBBB", "signature": "0" * 64})
    await router._process_telemetry(forged, f"public-intelligence/net/nodes/{NODE_ID}/telemetry")

    assert registry.is_mesh_reachable(NODE_ID) is False


@pytest.mark.asyncio
async def test_liveliness_alone_no_longer_marks_the_node_reachable() -> None:
    """Reversed by ROADMAP 2.7, deliberately. This test used to assert the opposite.

    A liveliness token carries NO PAYLOAD, so there is nothing to sign, and the node
    id comes from a key expression the publisher chose. Marking reachability from it
    let anyone on the mesh point dispatch at a queryable that does not exist, costing
    `mesh_inference_first_reply_timeout_seconds` on every request before the HTTP
    fallback. Reachability now comes only from a VERIFIED heartbeat or telemetry,
    which arrives within one interval and actually proves the session.
    """
    registry = NodeRegistry()
    await registry.set_node_token(NODE_ID, TOKEN)
    await registry.register(_node())
    router = _router(registry)
    router._loop = asyncio.get_running_loop()

    router._on_liveliness(FakeLivelinessSample(NODE_ID, zenoh.SampleKind.PUT))
    await asyncio.sleep(0.05)

    assert registry.is_mesh_reachable(NODE_ID) is False


@pytest.mark.asyncio
async def test_liveliness_delete_still_evicts_the_node() -> None:
    """Regression guard: adding PUT handling must not break the deathrattle path."""
    registry = NodeRegistry()
    await registry.register(_node())
    registry.mark_mesh_reachable(NODE_ID)
    router = _router(registry)
    router._loop = asyncio.get_running_loop()

    router._on_liveliness(FakeLivelinessSample(NODE_ID, zenoh.SampleKind.DELETE))
    for _ in range(20):
        if not await registry.exists(NODE_ID):
            break
        await asyncio.sleep(0.01)

    assert await registry.exists(NODE_ID) is False
    assert registry.is_mesh_reachable(NODE_ID) is False


@pytest.mark.asyncio
async def test_heartbeat_from_an_unregistered_node_does_not_mark_it() -> None:
    """Marking a node the registry does not know would leave an entry nothing purges."""
    registry = NodeRegistry()
    router = _router(registry)

    payload = json.dumps(
        {
            "node_id": "stranger",
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "online",
            "queue_length": 0,
            "cpu_utilization": 10.0,
            "ram_available_gb": 8.0,
            "gpu_utilization": 0.0,
            "vram_available_gb": 4.0,
        }
    )
    await router._process_heartbeat(payload, "public-intelligence/net/stranger/heartbeat")

    assert registry.is_mesh_reachable("stranger") is False
