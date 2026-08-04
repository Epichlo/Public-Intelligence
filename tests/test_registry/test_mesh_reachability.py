"""The registry must record which nodes have been seen on the Zenoh mesh.

Dispatch uses this to decide whether to query a node over the mesh or dial it over HTTP.
It is deliberately an *observed* signal -- set only when traffic has actually arrived from
that node -- rather than something a node asserts about itself at registration, which it
would have no way to know at that point and could get wrong.
"""

import pytest

from scheduler.models.node import GPUInfo, Node
from scheduler.registry.node_registry import NodeRegistry

NODE_ID = "node-mesh-reach"


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


@pytest.mark.asyncio
async def test_nodes_are_not_mesh_reachable_by_default() -> None:
    """Registering over HTTP says nothing about mesh reachability."""
    registry = NodeRegistry()
    await registry.register(_node())

    assert registry.is_mesh_reachable(NODE_ID) is False


@pytest.mark.asyncio
async def test_marking_makes_a_node_mesh_reachable() -> None:
    registry = NodeRegistry()
    await registry.register(_node())

    registry.mark_mesh_reachable(NODE_ID)

    assert registry.is_mesh_reachable(NODE_ID) is True


@pytest.mark.asyncio
async def test_unknown_node_is_not_mesh_reachable() -> None:
    """A node that was never registered must not be dispatched to."""
    registry = NodeRegistry()

    assert registry.is_mesh_reachable("never-heard-of-it") is False


@pytest.mark.asyncio
async def test_unregister_purges_mesh_reachability() -> None:
    """Stale reachability would send work to a node that has gone away."""
    registry = NodeRegistry()
    await registry.register(_node())
    registry.mark_mesh_reachable(NODE_ID)

    await registry.local_unregister(NODE_ID)

    assert registry.is_mesh_reachable(NODE_ID) is False


@pytest.mark.asyncio
async def test_deathrattle_unregister_purges_mesh_reachability() -> None:
    """The liveliness-driven eviction path must purge it too, not just the API path."""
    registry = NodeRegistry()
    await registry.register(_node())
    registry.mark_mesh_reachable(NODE_ID)

    await registry.local_unregister_node(NODE_ID)

    assert registry.is_mesh_reachable(NODE_ID) is False


@pytest.mark.asyncio
async def test_clear_purges_mesh_reachability() -> None:
    registry = NodeRegistry()
    await registry.register(_node())
    registry.mark_mesh_reachable(NODE_ID)

    await registry.clear()

    assert registry.is_mesh_reachable(NODE_ID) is False


@pytest.mark.asyncio
async def test_reachability_is_not_serialised_into_api_responses() -> None:
    """It is registry state, not part of the Node model, so it cannot leak or be forged."""
    registry = NodeRegistry()
    node = _node()
    await registry.register(node)
    registry.mark_mesh_reachable(NODE_ID)

    listed = await registry.list()

    fields = set(listed[0].model_dump().keys())
    assert not [f for f in fields if "mesh" in f or "reachab" in f], (
        f"mesh reachability became part of the Node model, so a node could assert it "
        f"at registration or read another node's: {sorted(fields)}"
    )
