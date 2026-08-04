"""Heartbeat metrics actually drive filtering and selection (roadmap 1.3).

Nodes report `vram_available_gb 0.0`, `cpu 15.0`, `gpu_utilization 0.0` and
`queue_length 0` on every heartbeat, hardcoded as placeholders. Two consequences
are asserted here, because both are live defects rather than hypotheticals:

- `matchmaker.py` prefers the heartbeat's `vram_available_gb` over the registered
  value, so a node with a real GPU is excluded from any task with a VRAM floor.
- `algorithm.py` scores on all four, so with constants every node ties and
  selection degenerates to registration order.

These are Scheduler-side tests: they take heartbeats as input and assert the
Scheduler does the right thing with honest ones. What makes the Node *send* honest
ones is covered in `Node/tests/test_heartbeat_metrics.py`.
"""

from datetime import UTC, datetime

import pytest

from scheduler.core.matchmaker import CapabilityMatchmaker
from scheduler.models.heartbeat import Heartbeat
from scheduler.models.node import GPUInfo, Node, NodeStatus
from scheduler.registry.node_registry import NodeRegistry
from scheduler.scheduler.algorithm import Scheduler as SchedulingAlgorithm


def _node(node_id: str, vram_total: float = 24.0) -> Node:
    return Node(
        node_id=node_id,
        hostname="host",
        ip_address="127.0.0.1",
        region="local",
        gpu=GPUInfo(
            name="NVIDIA GeForce RTX 4090",
            vram_total_gb=vram_total,
            vram_available_gb=vram_total,
        ),
        cpu_cores=8,
        ram_total_gb=32.0,
        available_models=["llama3"],
    )


def _heartbeat(
    node_id: str,
    *,
    vram_available_gb: float,
    cpu_utilization: float = 10.0,
    gpu_utilization: float = 0.0,
    queue_length: int = 0,
) -> Heartbeat:
    return Heartbeat(
        node_id=node_id,
        timestamp=datetime.now(UTC),
        queue_length=queue_length,
        cpu_utilization=cpu_utilization,
        ram_available_gb=16.0,
        gpu_utilization=gpu_utilization,
        vram_available_gb=vram_available_gb,
        status=NodeStatus.ONLINE,
    )


@pytest.mark.anyio
async def test_placeholder_vram_excludes_a_real_gpu_node() -> None:
    """Reproduces the live 1.3 defect: 0.0 in the heartbeat hides a 24 GB card.

    This is what nodes send today. The node registered 24 GB total and 24 GB free,
    so it can obviously serve an 8 GB task -- but the heartbeat wins and it matches
    nothing.
    """
    registry = NodeRegistry()
    await registry.register(_node("gpu-node"))
    await registry.update_heartbeat(_heartbeat("gpu-node", vram_available_gb=0.0))

    eligible = CapabilityMatchmaker(registry).filter_nodes(
        {"model_name": "llama3", "min_vram_gb": 8.0},
        await registry.list(),
    )

    assert eligible == [], "precondition for 1.3 no longer holds; update this test"


@pytest.mark.anyio
async def test_honest_vram_heartbeat_keeps_a_capable_node_eligible() -> None:
    """With a measured figure, the same node is correctly offered the work."""
    registry = NodeRegistry()
    await registry.register(_node("gpu-node"))
    await registry.update_heartbeat(_heartbeat("gpu-node", vram_available_gb=20.0))

    eligible = CapabilityMatchmaker(registry).filter_nodes(
        {"model_name": "llama3", "min_vram_gb": 8.0},
        await registry.list(),
    )

    assert [n.node_id for n in eligible] == ["gpu-node"]


@pytest.mark.anyio
async def test_honest_vram_still_excludes_a_node_that_is_genuinely_full() -> None:
    """Real numbers must exclude as well as include, or the filter is decorative."""
    registry = NodeRegistry()
    await registry.register(_node("busy-node"))
    await registry.update_heartbeat(_heartbeat("busy-node", vram_available_gb=1.5))

    eligible = CapabilityMatchmaker(registry).filter_nodes(
        {"model_name": "llama3", "min_vram_gb": 8.0},
        await registry.list(),
    )

    assert eligible == []


@pytest.mark.anyio
async def test_placeholder_metrics_hide_real_load_from_selection() -> None:
    """Reproduces the second half of the defect, via selection rather than internals.

    `saturated-node` is registered first and is genuinely the worse choice. Because
    both nodes send the same placeholder heartbeat, the scores tie and the stable
    `min` returns the first-registered node -- so the Scheduler routes to the
    saturated one. Real load is invisible to it.
    """
    registry = NodeRegistry()
    await registry.register(_node("saturated-node"))
    await registry.register(_node("idle-node"))

    # Exactly what runtime._collect_heartbeat_metrics returns today, for both.
    for node_id in ("saturated-node", "idle-node"):
        await registry.update_heartbeat(
            _heartbeat(
                node_id,
                vram_available_gb=0.0,
                cpu_utilization=15.0,
                gpu_utilization=0.0,
                queue_length=0,
            )
        )

    selected = await SchedulingAlgorithm(registry).select_node("llama3")

    assert selected.node_id == "saturated-node", (
        "precondition for 1.3 no longer holds; update this test"
    )


@pytest.mark.anyio
async def test_idle_node_is_selected_over_a_loaded_one() -> None:
    """The point of 1.3: measured load must actually steer selection."""
    registry = NodeRegistry()
    await registry.register(_node("idle-node"))
    await registry.register(_node("loaded-node"))

    await registry.update_heartbeat(
        _heartbeat(
            "idle-node",
            vram_available_gb=22.0,
            cpu_utilization=5.0,
            gpu_utilization=2.0,
            queue_length=0,
        )
    )
    await registry.update_heartbeat(
        _heartbeat(
            "loaded-node",
            vram_available_gb=3.0,
            cpu_utilization=90.0,
            gpu_utilization=95.0,
            queue_length=4,
        )
    )

    selected = await SchedulingAlgorithm(registry).select_node("llama3")

    assert selected.node_id == "idle-node"
