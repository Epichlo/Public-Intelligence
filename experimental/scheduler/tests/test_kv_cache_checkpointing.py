"""Unit and integration tests for Phase 4.8 Async KV-Cache Checkpointing
& Dynamic State Rerouting."""

import pytest
from scheduler.core.engine import SchedulingEngine
from scheduler.core.kv_cache import KVCacheManager
from scheduler.core.matchmaker import CapabilityMatchmaker
from scheduler.models.node import GPUInfo, Node
from scheduler.models.pipeline import KVCacheSnapshot, LayerRange, PipelineStage, StageType
from scheduler.registry.node_registry import NodeRegistry


def test_kv_cache_manager_create_and_verify_snapshot() -> None:
    """Verify creation, SHA-256 checksum calculation, and storage of KVCacheSnapshot."""
    manager = KVCacheManager(node_id="node-kv-1")
    raw_cache = b"\x00\x01\x02\x03\x04\x05\x06\x07kv_cache_tensor_bytes"

    snapshot = manager.create_snapshot(
        task_id="task-kv-100",
        sequence_id=16,
        start_layer=1,
        end_layer=15,
        cache_data=raw_cache,
    )

    assert isinstance(snapshot, KVCacheSnapshot)
    assert snapshot.task_id == "task-kv-100"
    assert snapshot.sequence_id == 16
    assert snapshot.checksum != ""
    snapshot.verify_checksum()

    latest = manager.get_latest_snapshot("task-kv-100")
    assert latest is not None
    assert latest.checksum == snapshot.checksum


def test_kv_cache_manager_corrupted_snapshot_rejection() -> None:
    """Verify rejection of corrupted snapshot with mismatched checksum."""
    manager = KVCacheManager(node_id="node-kv-1")
    bad_snapshot = KVCacheSnapshot(
        task_id="task-bad",
        sequence_id=8,
        node_id="node-bad",
        start_layer=0,
        end_layer=5,
        cache_bytes=b"actual_data",
        checksum="invalid_hash_string",
    )

    assert manager.store_remote_snapshot(bad_snapshot) is False
    assert manager.get_latest_snapshot("task-bad") is None


@pytest.mark.asyncio
async def test_scheduling_engine_restitch_pipeline_on_eviction() -> None:
    """Test dynamic pipeline restitching when a node drop occurs, transferring to backup node."""
    registry = NodeRegistry()
    strategy = CapabilityMatchmaker(registry=registry)
    engine = SchedulingEngine(registry, strategy)

    node1 = Node(
        node_id="node-failed",
        hostname="host-1",
        ip_address="192.168.1.10",
        region="us-west",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=24.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3"],
    )
    node2 = Node(
        node_id="node-backup",
        hostname="host-2",
        ip_address="192.168.1.11",
        region="us-west",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=24.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3"],
    )

    await registry.register(node1)
    await registry.register(node2)

    manager = KVCacheManager(node_id="node-failed")
    snapshot = manager.create_snapshot("task-restitch-1", 16, 1, 31, b"valid_kv_cache_data")

    stages = [
        PipelineStage(
            stage_index=0,
            total_stages=3,
            layer_range=LayerRange(start_layer=0, end_layer=0),
            node_id="client_local",
            model_id="llama3",
            is_local_boundary=True,
            stage_type=StageType.CLIENT_EMBEDDING,
            is_split_inference=True,
        ),
        PipelineStage(
            stage_index=1,
            total_stages=3,
            layer_range=LayerRange(start_layer=1, end_layer=31),
            node_id="node-failed",
            model_id="llama3",
            is_local_boundary=False,
            stage_type=StageType.REMOTE_HIDDEN,
            is_split_inference=True,
        ),
        PipelineStage(
            stage_index=2,
            total_stages=3,
            layer_range=LayerRange(start_layer=32, end_layer=32),
            node_id="client_local",
            model_id="llama3",
            is_local_boundary=True,
            stage_type=StageType.CLIENT_LM_HEAD,
            is_split_inference=True,
        ),
    ]

    restitched = await engine.restitch_pipeline_on_eviction(
        task_id="task-restitch-1",
        failed_node_id="node-failed",
        kv_snapshot=snapshot,
        pipeline_stages=stages,
    )

    assert len(restitched) == 3
    assert restitched[1].node_id == "node-backup"
    assert restitched[1].stage_index == 1
