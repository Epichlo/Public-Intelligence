"""Tests for pipeline scheduling and model layer sharding across cluster nodes."""

import pytest

from scheduler.core.engine import SchedulingEngine
from scheduler.core.matchmaker import CapabilityMatchmaker
from scheduler.models.node import GPUInfo, Node
from scheduler.models.pipeline import LayerRange, PipelineConfig, PipelineStage
from scheduler.registry.node_registry import NodeRegistry


@pytest.fixture
def make_node():
    """Fixture factory to create mock nodes with specified VRAM and models."""

    def _create_node(
        node_id: str,
        vram_total_gb: float = 24.0,
        vram_avail_gb: float = 20.0,
        models: list[str] | None = None,
    ) -> Node:
        return Node(
            node_id=node_id,
            hostname=f"host-{node_id}",
            ip_address="127.0.0.1",
            region="us-east",
            gpu=GPUInfo(
                name="RTX 4090",
                vram_total_gb=vram_total_gb,
                vram_available_gb=vram_avail_gb,
            ),
            cpu_cores=8,
            ram_total_gb=32.0,
            available_models=models or ["llama3-70b"],
        )

    return _create_node


@pytest.mark.asyncio
async def test_schedule_pipeline_single_node(make_node) -> None:
    """Verify pipeline scheduling on a single node cluster when node has sufficient VRAM."""
    registry = NodeRegistry()
    node1 = make_node("node-1", vram_total_gb=40.0, vram_avail_gb=40.0)
    await registry.local_register(node1)

    strategy = CapabilityMatchmaker(registry)
    engine = SchedulingEngine(registry, strategy)

    task = {
        "task_id": "task-pipeline-1",
        "model": "llama3-70b",
        "total_layers": 32,
        "vram_per_layer_gb": 1.0,
    }

    tx_hash, stages = await engine.schedule_pipeline(task)

    assert isinstance(tx_hash, str)
    assert len(tx_hash) == 64
    assert len(stages) == 1
    assert isinstance(stages[0], PipelineStage)
    assert stages[0].stage_index == 0
    assert stages[0].total_stages == 1
    assert stages[0].is_first_stage is True
    assert stages[0].is_last_stage is True
    assert stages[0].layer_range.start_layer == 0
    assert stages[0].layer_range.end_layer == 31
    assert stages[0].num_layers == 32
    assert stages[0].node_id == "node-1"


@pytest.mark.asyncio
async def test_schedule_pipeline_two_nodes(make_node) -> None:
    """Verify pipeline chain allocation across 2 nodes when VRAM must be shared."""
    registry = NodeRegistry()
    node1 = make_node("node-1", vram_total_gb=16.0, vram_avail_gb=16.0)
    node2 = make_node("node-2", vram_total_gb=16.0, vram_avail_gb=16.0)
    await registry.local_register(node1)
    await registry.local_register(node2)

    strategy = CapabilityMatchmaker(registry)
    engine = SchedulingEngine(registry, strategy)

    task = {
        "task_id": "task-pipeline-2",
        "model": "llama3-70b",
        "total_layers": 32,
        "vram_per_layer_gb": 1.0,
    }

    tx_hash, stages = await engine.schedule_pipeline(task)

    assert isinstance(tx_hash, str)
    assert len(stages) == 2

    # Stage 0 check
    assert isinstance(stages[0], PipelineStage)
    assert stages[0].stage_index == 0
    assert stages[0].total_stages == 2
    assert stages[0].is_first_stage is True
    assert stages[0].is_last_stage is False
    assert stages[0].layer_range.start_layer == 0
    assert stages[0].layer_range.end_layer == 15
    assert stages[0].node_id == "node-1"

    # Stage 1 check
    assert isinstance(stages[1], PipelineStage)
    assert stages[1].stage_index == 1
    assert stages[1].total_stages == 2
    assert stages[1].is_first_stage is False
    assert stages[1].is_last_stage is True
    assert stages[1].layer_range.start_layer == 16
    assert stages[1].layer_range.end_layer == 31
    assert stages[1].node_id == "node-2"

    # Verify total layers sum
    total_layers_allocated = sum(s.num_layers for s in stages)
    assert total_layers_allocated == 32


@pytest.mark.asyncio
async def test_schedule_pipeline_three_plus_nodes(make_node) -> None:
    """Verify pipeline chain allocation across 3 nodes."""
    registry = NodeRegistry()
    node1 = make_node("node-1", vram_total_gb=10.0, vram_avail_gb=10.0)
    node2 = make_node("node-2", vram_total_gb=10.0, vram_avail_gb=10.0)
    node3 = make_node("node-3", vram_total_gb=10.0, vram_avail_gb=10.0)
    await registry.local_register(node1)
    await registry.local_register(node2)
    await registry.local_register(node3)

    strategy = CapabilityMatchmaker(registry)
    engine = SchedulingEngine(registry, strategy)

    task = {
        "task_id": "task-pipeline-3",
        "model": "llama3-70b",
        "total_layers": 30,
        "vram_per_layer_gb": 1.0,
    }

    tx_hash, stages = await engine.schedule_pipeline(task)

    assert isinstance(tx_hash, str)
    assert len(stages) == 3
    assert stages[0].layer_range == LayerRange(start_layer=0, end_layer=9)
    assert stages[1].layer_range == LayerRange(start_layer=10, end_layer=19)
    assert stages[2].layer_range == LayerRange(start_layer=20, end_layer=29)

    assert stages[0].is_first_stage is True
    assert stages[1].is_first_stage is False
    assert stages[1].is_last_stage is False
    assert stages[2].is_last_stage is True


@pytest.mark.asyncio
async def test_schedule_pipeline_insufficient_vram(make_node) -> None:
    """Verify ValueError is raised when total cluster VRAM is less than required for all layers."""
    registry = NodeRegistry()
    node1 = make_node("node-1", vram_total_gb=10.0, vram_avail_gb=10.0)
    await registry.local_register(node1)

    strategy = CapabilityMatchmaker(registry)
    engine = SchedulingEngine(registry, strategy)

    task = {
        "task_id": "task-pipeline-fail",
        "model": "llama3-70b",
        "total_layers": 32,
        "vram_per_layer_gb": 1.0,
    }

    with pytest.raises(ValueError, match="Insufficient VRAM"):
        await engine.schedule_pipeline(task)


@pytest.mark.asyncio
async def test_boundary_layer_checks_and_pipeline_config(make_node) -> None:
    """Verify exact boundary layer alignment and validation using PipelineConfig."""
    registry = NodeRegistry()
    node1 = make_node("node-1", vram_total_gb=10.0, vram_avail_gb=10.0)
    node2 = make_node("node-2", vram_total_gb=10.0, vram_avail_gb=10.0)
    await registry.local_register(node1)
    await registry.local_register(node2)

    strategy = CapabilityMatchmaker(registry)
    engine = SchedulingEngine(registry, strategy)

    task = {
        "task_id": "task-config-check",
        "model": "llama3-70b",
        "total_layers": 20,
        "vram_per_layer_gb": 1.0,
    }

    tx_hash, stages = await engine.schedule_pipeline(task)

    config = PipelineConfig(
        task_id="task-config-check",
        model_id="llama3-70b",
        total_layers=20,
        stages=stages,
    )

    assert isinstance(tx_hash, str)
    assert config.num_stages == 2
    assert config.stages[0].layer_range.start_layer == 0
    assert config.stages[-1].layer_range.end_layer == 19
