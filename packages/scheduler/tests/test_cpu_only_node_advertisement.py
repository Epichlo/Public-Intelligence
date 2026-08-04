"""The Scheduler accepts and correctly handles honest hardware (roadmap 1.2).

Every node used to register a hardcoded 16 GB "unknown" GPU, which meant
`GPUInfo.vram_total_gb`'s `gt=0` constraint was satisfied only because every node
lied to satisfy it. Now that nodes report real hardware, a machine with no GPU
must be representable -- and must be excluded from work it cannot do.
"""

import pytest
from pydantic import ValidationError

from scheduler.core.matchmaker import CapabilityMatchmaker
from scheduler.models.node import GPUInfo, Node
from scheduler.registry.node_registry import NodeRegistry


def _node(node_id: str, gpu: GPUInfo, models: list[str] | None = None) -> Node:
    return Node(
        node_id=node_id,
        hostname="host",
        ip_address="127.0.0.1",
        region="local",
        gpu=gpu,
        cpu_cores=8,
        ram_total_gb=32.0,
        available_models=models if models is not None else ["llama3"],
    )


def _cpu_only() -> GPUInfo:
    return GPUInfo(name="cpu-only", vram_total_gb=0.0, vram_available_gb=0.0)


def _rtx4090() -> GPUInfo:
    return GPUInfo(name="NVIDIA GeForce RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0)


def test_gpu_info_accepts_zero_vram() -> None:
    """A CPU-only host must be representable rather than forced to invent VRAM."""
    gpu = _cpu_only()

    assert gpu.vram_total_gb == 0.0
    assert gpu.vram_available_gb == 0.0


def test_gpu_info_still_rejects_negative_vram() -> None:
    """Relaxing gt=0 to ge=0 must not let negative capacity through."""
    with pytest.raises(ValidationError):
        GPUInfo(name="broken", vram_total_gb=-1.0, vram_available_gb=0.0)

    with pytest.raises(ValidationError):
        GPUInfo(name="broken", vram_total_gb=8.0, vram_available_gb=-1.0)


@pytest.mark.anyio
async def test_cpu_only_node_is_filtered_out_of_vram_tasks() -> None:
    """A node with no GPU must not be offered work with a VRAM floor.

    Under the old hardcoded 16 GB this node would have been considered eligible
    for anything up to 16 GB and would have failed at inference time instead.
    """
    registry = NodeRegistry()
    await registry.register(_node("cpu-node", _cpu_only()))
    await registry.register(_node("gpu-node", _rtx4090()))

    matchmaker = CapabilityMatchmaker(registry)
    eligible = matchmaker.filter_nodes(
        {"model_name": "llama3", "min_vram_gb": 8.0},
        await registry.list(),
    )

    assert [n.node_id for n in eligible] == ["gpu-node"]


@pytest.mark.anyio
async def test_cpu_only_node_is_still_eligible_without_a_vram_floor() -> None:
    """Reporting 0 GB excludes a node from VRAM-gated work, not from everything."""
    registry = NodeRegistry()
    await registry.register(_node("cpu-node", _cpu_only()))

    matchmaker = CapabilityMatchmaker(registry)
    eligible = matchmaker.filter_nodes({"model_name": "llama3"}, await registry.list())

    assert [n.node_id for n in eligible] == ["cpu-node"]


@pytest.mark.anyio
async def test_registration_accepts_a_cpu_only_node(client) -> None:  # type: ignore[no-untyped-def]
    """A CPU-only node registers over HTTP without a 422."""
    response = await client.post(
        "/nodes/register",
        json={
            "node_id": "cpu-node",
            "hostname": "host",
            "ip_address": "127.0.0.1",
            "region": "local",
            "gpu": {"name": "cpu-only", "vram_total_gb": 0.0, "vram_available_gb": 0.0},
            "cpu_cores": 4,
            "ram_total_gb": 8.0,
            "available_models": ["llama3"],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["gpu"]["vram_total_gb"] == 0.0
