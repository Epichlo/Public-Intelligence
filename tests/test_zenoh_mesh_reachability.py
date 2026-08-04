"""The router must learn which nodes are on the mesh, from traffic it actually receives.

Dispatch will only query a node over Zenoh if the registry says it has been seen there.
Nothing sets that flag today, so without these paths the mesh transport would never be
used and every request would keep dialling `ip_address`.

Each signal below is independent on purpose: a node that publishes heartbeats but whose
telemetry emitter failed, or one seen only via its liveliness token, is still reachable.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from typing import Any

import pytest
import zenoh
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scheduler.core.zenoh_router import ZenohRouter
from scheduler.models.node import GPUInfo, Node
from scheduler.registry.node_registry import NodeRegistry

NODE_ID = "node-on-the-mesh"


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
    return ZenohRouter(registry, config=config)


def _telemetry_envelope(node_id: str) -> str:
    """Build a telemetry envelope the router will accept, as the Node emitter does."""
    secret = os.environ.get("TELEMETRY_SECRET_KEY", "pi_telemetry_secure_default_secret_key")
    enc_key = hashlib.sha256(secret.encode() + b"-encryption").digest()
    hmac_key = hashlib.sha256(secret.encode() + b"-hmac").digest()

    plaintext = json.dumps(
        {"node_id": node_id, "timestamp": datetime.now(UTC).isoformat(), "gpu_utilization": 12.0}
    )
    iv = os.urandom(12)
    ciphertext = AESGCM(enc_key).encrypt(iv, plaintext.encode(), None)
    iv_b64 = base64.b64encode(iv).decode()
    ct_b64 = base64.b64encode(ciphertext).decode()
    sig = hmac.new(hmac_key, f"{iv_b64}:{ct_b64}".encode(), hashlib.sha256).hexdigest()
    return json.dumps({"iv": iv_b64, "ciphertext": ct_b64, "signature": sig})


class FakeLivelinessSample:
    """Stands in for a zenoh liveliness sample."""

    def __init__(self, node_id: str, kind: Any) -> None:
        self.key_expr = f"public-intelligence/net/liveliness/{node_id}"
        self.kind = kind


@pytest.mark.asyncio
async def test_zenoh_heartbeat_marks_the_node_reachable() -> None:
    """A heartbeat arriving over Zenoh proves the node holds a live session."""
    registry = NodeRegistry()
    await registry.register(_node())
    router = _router(registry)

    payload = json.dumps(
        {
            "node_id": NODE_ID,
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "online",
            "queue_length": 0,
            "cpu_utilization": 10.0,
            "ram_available_gb": 8.0,
            "gpu_utilization": 0.0,
            "vram_available_gb": 4.0,
        }
    )
    await router._process_heartbeat(payload, f"public-intelligence/net/{NODE_ID}/heartbeat")

    assert registry.is_mesh_reachable(NODE_ID) is True


@pytest.mark.asyncio
async def test_telemetry_marks_the_node_reachable() -> None:
    """Telemetry is a second independent signal, for a node whose heartbeat path failed."""
    registry = NodeRegistry()
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
    await router._process_telemetry(
        forged, f"public-intelligence/net/nodes/{NODE_ID}/telemetry"
    )

    assert registry.is_mesh_reachable(NODE_ID) is False


@pytest.mark.asyncio
async def test_liveliness_token_marks_the_node_reachable() -> None:
    """A liveliness PUT is the earliest signal, arriving before the first heartbeat."""
    registry = NodeRegistry()
    await registry.register(_node())
    router = _router(registry)
    router._loop = asyncio.get_running_loop()

    router._on_liveliness(FakeLivelinessSample(NODE_ID, zenoh.SampleKind.PUT))
    for _ in range(20):
        if registry.is_mesh_reachable(NODE_ID):
            break
        await asyncio.sleep(0.01)

    assert registry.is_mesh_reachable(NODE_ID) is True


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
