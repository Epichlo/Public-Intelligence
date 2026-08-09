"""Unit and integration tests for Node Phase 4.8 Async KV-Cache Checkpointing."""

from node.models.sharding import KVCacheSnapshot

from experimental.node.kv_cache import KVCacheManager


def test_node_kv_cache_manager_create_snapshot() -> None:
    """Verify Node KVCacheManager snapshot creation and checksum validation."""
    mgr = KVCacheManager(node_id="node-test-1")
    snapshot = mgr.create_snapshot(
        task_id="node-task-1",
        sequence_id=32,
        start_layer=1,
        end_layer=16,
        cache_data=b"node_kv_bytes_data",
    )

    assert isinstance(snapshot, KVCacheSnapshot)
    assert snapshot.node_id == "node-test-1"
    assert snapshot.sequence_id == 32
    snapshot.verify_checksum()

    stored = mgr.get_latest_snapshot("node-task-1")
    assert stored is not None
    assert stored.checksum == snapshot.checksum


def test_node_kv_cache_manager_clear_snapshots() -> None:
    """Verify purging of task snapshots upon task completion."""
    mgr = KVCacheManager(node_id="node-test-1")
    mgr.create_snapshot("node-task-purge", 16, 1, 8, b"data1")
    mgr.create_snapshot("node-task-purge", 32, 1, 8, b"data2")

    assert mgr.get_latest_snapshot("node-task-purge") is not None
    mgr.clear_task_snapshots("node-task-purge")
    assert mgr.get_latest_snapshot("node-task-purge") is None
