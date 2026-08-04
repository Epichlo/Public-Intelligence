"""Unit tests for split-inference pipeline scheduling engine."""

import pytest

from scheduler.core.engine import SchedulingEngine
from scheduler.core.matchmaker import CapabilityMatchmaker
from scheduler.core.strategy import SchedulingStrategy
from scheduler.models.node import GPUInfo, Node
from scheduler.models.pipeline import StageType, TaskProposal
from scheduler.registry.node_registry import NodeRegistry


@pytest.fixture
def registry() -> NodeRegistry:
    """Fixture providing an empty NodeRegistry instance."""
    return NodeRegistry()


@pytest.fixture
def strategy(registry: NodeRegistry) -> SchedulingStrategy:
    """Fixture providing a CapabilityMatchmaker strategy instance."""
    return CapabilityMatchmaker(registry=registry)


@pytest.fixture
def engine(registry: NodeRegistry, strategy: SchedulingStrategy) -> SchedulingEngine:
    """Fixture providing a SchedulingEngine instance."""
    return SchedulingEngine(registry=registry, strategy=strategy)


@pytest.fixture
def sample_node() -> Node:
    """Fixture providing a sample compute node."""
    return Node(
        node_id="remote-node-1",
        hostname="remote-host-1",
        ip_address="192.168.1.50",
        region="us-east",
        gpu=GPUInfo(
            name="NVIDIA A100",
            vram_total_gb=40.0,
            vram_available_gb=32.0,
        ),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama2", "mistral-7b"],
    )


@pytest.fixture
def sample_node_2() -> Node:
    """Fixture providing a second sample compute node."""
    return Node(
        node_id="remote-node-2",
        hostname="remote-host-2",
        ip_address="192.168.1.51",
        region="us-east",
        gpu=GPUInfo(
            name="NVIDIA RTX 4090",
            vram_total_gb=24.0,
            vram_available_gb=16.0,
        ),
        cpu_cores=12,
        ram_total_gb=32.0,
        available_models=["llama2", "mistral-7b"],
    )


@pytest.mark.asyncio
async def test_schedule_split_inference_pipeline_construction(
    engine: SchedulingEngine, registry: NodeRegistry, sample_node: Node
) -> None:
    """Test 3-tier asymmetric split-inference stage construction."""
    await registry.register(sample_node)

    task = TaskProposal(
        task_id="task-split-1",
        model_id="llama2",
        total_layers=32,
        vram_per_layer_gb=0.5,
    )

    stages = await engine.schedule_split_inference_pipeline(task, total_layers=32)

    # 3-tier pipeline: Stage 0 (Client Embedding), Stage 1 (Remote Hidden),
    # Stage 2 (Client LM Head)
    assert len(stages) == 3

    # Stage 0: Client Local Embedding
    assert stages[0].stage_index == 0
    assert stages[0].total_stages == 3
    assert stages[0].node_id == "client_local"
    assert stages[0].is_local_boundary is True
    assert stages[0].stage_type in (StageType.CLIENT_EMBEDDING, "client_embedding")
    assert stages[0].is_split_inference is True
    assert stages[0].layer_range.start_layer == 0
    assert stages[0].layer_range.end_layer == 0

    # Stage 1: Remote Host Pipeline
    assert stages[1].stage_index == 1
    assert stages[1].total_stages == 3
    assert stages[1].node_id == "remote-node-1"
    assert stages[1].is_local_boundary is False
    assert stages[1].stage_type in (StageType.REMOTE_HIDDEN, "remote_hidden")
    assert stages[1].is_split_inference is True
    assert stages[1].layer_range.start_layer == 1
    assert stages[1].layer_range.end_layer == 31

    # Stage 2: Client Local LM Head
    assert stages[2].stage_index == 2
    assert stages[2].total_stages == 3
    assert stages[2].node_id == "client_local"
    assert stages[2].is_local_boundary is True
    assert stages[2].stage_type in (StageType.CLIENT_LM_HEAD, "client_lm_head")
    assert stages[2].is_split_inference is True
    assert stages[2].layer_range.start_layer == 32
    assert stages[2].layer_range.end_layer == 32


@pytest.mark.asyncio
async def test_schedule_split_inference_pipeline_multi_node(
    engine: SchedulingEngine,
    registry: NodeRegistry,
    sample_node: Node,
    sample_node_2: Node,
) -> None:
    """Test partitioning intermediate layers across multiple compute nodes."""
    await registry.register(sample_node)
    await registry.register(sample_node_2)

    # Set constrained VRAM capacity so layers split across 2 nodes
    sample_node.gpu.vram_available_gb = 10.0
    sample_node_2.gpu.vram_available_gb = 10.0

    task_dict = {
        "task_id": "task-split-multi",
        "model_id": "llama2",
        "total_layers": 32,
        "vram_per_layer_gb": 0.6,
    }

    stages = await engine.schedule_split_inference_pipeline(task_dict, total_layers=32)

    assert len(stages) == 4  # Stage 0 (Local), Remote 1, Remote 2, Stage 3 (Local)

    # Verify boundary placement
    assert stages[0].is_local_boundary is True
    assert stages[-1].is_local_boundary is True

    # Verify intermediate stages are remote
    for r_stage in stages[1:-1]:
        assert r_stage.is_local_boundary is False
        assert r_stage.is_split_inference is True
        assert r_stage.stage_type in (StageType.REMOTE_HIDDEN, "remote_hidden")

    # Verify layer continuity across intermediate stages
    assert stages[1].layer_range.start_layer == 1
    assert stages[1].layer_range.end_layer + 1 == stages[2].layer_range.start_layer
    assert stages[2].layer_range.end_layer == 31


@pytest.mark.asyncio
async def test_schedule_split_inference_pipeline_invalid_layers(
    engine: SchedulingEngine, registry: NodeRegistry, sample_node: Node
) -> None:
    """Test ValueError raised when total_layers < 2."""
    await registry.register(sample_node)
    with pytest.raises(ValueError, match="total_layers must be at least 2"):
        await engine.schedule_split_inference_pipeline({"model_id": "llama2"}, total_layers=1)


@pytest.mark.asyncio
async def test_schedule_split_inference_pipeline_no_nodes(engine: SchedulingEngine) -> None:
    """Test ValueError raised when no active nodes are available."""
    with pytest.raises(ValueError, match="No active nodes available"):
        await engine.schedule_split_inference_pipeline({"model_id": "llama2"}, total_layers=32)
