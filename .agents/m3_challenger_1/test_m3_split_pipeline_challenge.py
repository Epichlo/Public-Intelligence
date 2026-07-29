"""Empirical Challenge Test Suite for Milestone M3 (Matchmaker Allocation & OpenAI Gateway Split Streaming).

Tests requirements for `SchedulingEngine.schedule_split_inference_pipeline`:
1. Method existence on `SchedulingEngine`.
2. Stage 0 structure: `node_id="client_local"`, `is_local_boundary=True`, `stage_type=StageType.CLIENT_EMBEDDING`, `layer_range=(0,0)`.
3. Stages 1..K-1 structure: partition intermediate layers 1..total_layers-1 across registered compute nodes with `is_local_boundary=False` and `stage_type=StageType.REMOTE_HIDDEN`.
4. Stage K structure: `node_id="client_local"`, `is_local_boundary=True`, `stage_type=StageType.CLIENT_LM_HEAD`, `layer_range=(total_layers, total_layers)`.
"""

import sys
from pathlib import Path
import pytest

# Add Scheduler/src to path
scheduler_src = str(Path("/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Scheduler/src").resolve())
if scheduler_src not in sys.path:
    sys.path.insert(0, scheduler_src)

from scheduler.core.engine import SchedulingEngine
from scheduler.core.matchmaker import CapabilityMatchmaker
from scheduler.models.node import GPUInfo, Node
from scheduler.registry.node_registry import NodeRegistry

try:
    from scheduler.models.pipeline import StageType
except ImportError:
    StageType = None


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


def test_stage_type_enum_exists() -> None:
    """Verify that StageType enum exists in scheduler.models.pipeline."""
    assert StageType is not None, "StageType enum is missing from scheduler.models.pipeline"
    assert hasattr(StageType, "CLIENT_EMBEDDING"), "StageType.CLIENT_EMBEDDING is missing"
    assert hasattr(StageType, "REMOTE_HIDDEN"), "StageType.REMOTE_HIDDEN is missing"
    assert hasattr(StageType, "CLIENT_LM_HEAD"), "StageType.CLIENT_LM_HEAD is missing"


def test_schedule_split_inference_pipeline_exists() -> None:
    """Verify that schedule_split_inference_pipeline method exists on SchedulingEngine."""
    assert hasattr(SchedulingEngine, "schedule_split_inference_pipeline"), (
        "SchedulingEngine has no method 'schedule_split_inference_pipeline'"
    )


@pytest.mark.asyncio
async def test_schedule_split_inference_pipeline_execution(make_node) -> None:
    """Verify split inference pipeline allocation across 3-tier boundary architecture."""
    registry = NodeRegistry()
    node1 = make_node("remote-node-1", vram_total_gb=16.0, vram_avail_gb=16.0)
    node2 = make_node("remote-node-2", vram_total_gb=16.0, vram_avail_gb=16.0)
    await registry.local_register(node1)
    await registry.local_register(node2)

    strategy = CapabilityMatchmaker(registry)
    engine = SchedulingEngine(registry, strategy)

    total_layers = 32
    task = {
        "task_id": "split-task-1",
        "model": "llama3-70b",
        "total_layers": total_layers,
        "vram_per_layer_gb": 1.0,
    }

    assert hasattr(engine, "schedule_split_inference_pipeline"), "Method schedule_split_inference_pipeline is missing"
    schedule_fn = getattr(engine, "schedule_split_inference_pipeline")
    tx_hash, stages = await schedule_fn(task)

    # 3-tier structure: Stage 0 (Client Local Embedding), Stages 1..K-1 (Remote Host Pipeline), Stage K (Client Local LM Head)
    assert len(stages) >= 3, f"Expected at least 3 stages (Stage 0, Remote Stage(s), Stage K), got {len(stages)}"

    # Stage 0: Client Local Embedding
    stage_0 = stages[0]
    assert stage_0.node_id == "client_local", f"Expected Stage 0 node_id='client_local', got '{stage_0.node_id}'"
    assert stage_0.is_local_boundary is True, f"Expected Stage 0 is_local_boundary=True, got {stage_0.is_local_boundary}"
    assert stage_0.stage_type == getattr(StageType, "CLIENT_EMBEDDING", "client_embedding")
    assert stage_0.layer_range.start_layer == 0
    assert stage_0.layer_range.end_layer == 0

    # Stages 1..K-1: Remote Hidden Layers
    remote_stages = stages[1:-1]
    for idx, r_stage in enumerate(remote_stages, start=1):
        assert r_stage.node_id != "client_local", f"Remote Stage {idx} must not be client_local"
        assert r_stage.is_local_boundary is False, f"Remote Stage {idx} must have is_local_boundary=False"
        assert r_stage.stage_type == getattr(StageType, "REMOTE_HIDDEN", "remote_hidden")

    # Intermediate layer coverage: Layers 1 .. total_layers - 1
    remote_start = remote_stages[0].layer_range.start_layer
    remote_end = remote_stages[-1].layer_range.end_layer
    assert remote_start == 1, f"Remote stages must start at layer 1, got {remote_start}"
    assert remote_end == total_layers - 1, f"Remote stages must end at layer {total_layers - 1}, got {remote_end}"

    # Stage K: Client Local LM Head
    stage_k = stages[-1]
    assert stage_k.node_id == "client_local", f"Expected Stage K node_id='client_local', got '{stage_k.node_id}'"
    assert stage_k.is_local_boundary is True, f"Expected Stage K is_local_boundary=True, got {stage_k.is_local_boundary}"
    assert stage_k.stage_type == getattr(StageType, "CLIENT_LM_HEAD", "client_lm_head")
    assert stage_k.layer_range.start_layer == total_layers
    assert stage_k.layer_range.end_layer == total_layers
