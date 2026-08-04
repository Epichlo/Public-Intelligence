"""Builders for Scheduler test data.

Every test used to construct `Node(node_id=..., hostname=..., ip_address=...,
region=..., gpu=GPUInfo(...), cpu_cores=..., ram_total_gb=..., available_models=[])`
by hand -- eight arguments, of which usually one mattered. Two separate `_node()`
helpers were written in two different test files within a day of each other because
there was nowhere shared to put one.

The point is not brevity, it is that the *intent* of a test becomes readable:

    make_node(vram=0)                 # a CPU-only node
    make_heartbeat("n1", vram=0.0)    # the placeholder heartbeat 1.3 removed
    make_heartbeat("n1", busy=True)   # a saturated node

versus eight keyword arguments in which the significant one is not signposted.

It also means adding a required field to `Node` is a one-line fix here rather than
a sweep across every test file.
"""

from datetime import UTC, datetime

from scheduler.models.heartbeat import Heartbeat
from scheduler.models.node import GPUInfo, Node, NodeStatus

__all__ = ["make_gpu", "make_heartbeat", "make_node"]


def make_gpu(
    vram: float = 24.0, available: float | None = None, name: str | None = None
) -> GPUInfo:
    """A GPU with `vram` GB total.

    `vram=0` yields the honest cpu-only profile: name "cpu-only", no capacity.
    That case is representable only because roadmap 1.2 relaxed `gt=0` to `ge=0`.
    """
    if vram <= 0:
        return GPUInfo(name=name or "cpu-only", vram_total_gb=0.0, vram_available_gb=0.0)
    return GPUInfo(
        name=name or "NVIDIA GeForce RTX 4090",
        vram_total_gb=vram,
        vram_available_gb=vram if available is None else available,
    )


def make_node(
    node_id: str = "test-node",
    *,
    vram: float = 24.0,
    models: list[str] | None = None,
    cpu_cores: int = 8,
    ram_total_gb: float = 32.0,
    ip_address: str = "127.0.0.1",
    region: str = "local",
) -> Node:
    """A registered node. Override only what the test is actually about."""
    return Node(
        node_id=node_id,
        hostname=f"{node_id}.local",
        ip_address=ip_address,
        region=region,
        gpu=make_gpu(vram),
        cpu_cores=cpu_cores,
        ram_total_gb=ram_total_gb,
        available_models=["llama3"] if models is None else models,
    )


def make_heartbeat(
    node_id: str = "test-node",
    *,
    vram: float = 20.0,
    cpu: float = 10.0,
    gpu: float = 5.0,
    queue: int = 0,
    ram: float = 16.0,
    busy: bool = False,
    status: NodeStatus = NodeStatus.ONLINE,
) -> Heartbeat:
    """A heartbeat. `busy=True` is a saturated node, for scoring tests.

    Note `status` has no counterpart on the Node's own Heartbeat model -- the
    Scheduler requires it and `build_heartbeat_payload` injects it. See
    specs/real-heartbeat-metrics.md; a node reporting a real status is a known gap.
    """
    if busy:
        vram, cpu, gpu, queue = 1.0, 95.0, 98.0, 8
    return Heartbeat(
        node_id=node_id,
        timestamp=datetime.now(UTC),
        queue_length=queue,
        cpu_utilization=cpu,
        ram_available_gb=ram,
        gpu_utilization=gpu,
        vram_available_gb=vram,
        status=status,
    )
