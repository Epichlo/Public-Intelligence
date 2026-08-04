"""KVCacheManager handling background KV snapshot replication and checkpointing."""

import hashlib
import logging
import time

from node.models.sharding import KVCacheSnapshot

logger = logging.getLogger(__name__)


class KVCacheManager:
    """Manages local KV-cache state snapshots and gossip replication."""

    def __init__(self, node_id: str = "default-node") -> None:
        """Initialize KVCacheManager.

        Args:
            node_id: Identifier of local compute node.
        """
        self.node_id = node_id
        # Map: (task_id, sequence_id) -> KVCacheSnapshot
        self._snapshots: dict[tuple[str, int], KVCacheSnapshot] = {}

    def create_snapshot(
        self,
        task_id: str,
        sequence_id: int,
        start_layer: int,
        end_layer: int,
        cache_data: bytes,
    ) -> KVCacheSnapshot:
        """Create and record a KVCacheSnapshot with SHA-256 checksum verification.

        Args:
            task_id: Unique task identifier.
            sequence_id: Token position sequence index.
            start_layer: Starting layer index.
            end_layer: Ending layer index.
            cache_data: Raw binary cache payload.

        Returns:
            The created KVCacheSnapshot object.
        """
        checksum = hashlib.sha256(cache_data).hexdigest()
        snapshot = KVCacheSnapshot(
            task_id=task_id,
            sequence_id=sequence_id,
            node_id=self.node_id,
            start_layer=start_layer,
            end_layer=end_layer,
            cache_bytes=cache_data,
            checksum=checksum,
            timestamp=time.time(),
        )
        self._snapshots[(task_id, sequence_id)] = snapshot
        return snapshot

    def store_remote_snapshot(self, snapshot: KVCacheSnapshot) -> bool:
        """Verify checksum and store a remote snapshot received over Zenoh gossip.

        Args:
            snapshot: Incoming KVCacheSnapshot.

        Returns:
            True if snapshot checksum is valid and stored, False otherwise.
        """
        try:
            snapshot.verify_checksum()
        except ValueError as err:
            logger.warning("kv_snapshot_checksum_verification_failed: %s", err)
            return False

        self._snapshots[(snapshot.task_id, snapshot.sequence_id)] = snapshot
        return True

    def get_latest_snapshot(self, task_id: str) -> KVCacheSnapshot | None:
        """Retrieve the latest valid snapshot for a task ID.

        Args:
            task_id: Unique task identifier.

        Returns:
            Latest KVCacheSnapshot or None.
        """
        matching = [s for (t_id, _), s in self._snapshots.items() if t_id == task_id]
        if not matching:
            return None
        return max(matching, key=lambda s: s.sequence_id)

    def clear_task_snapshots(self, task_id: str) -> None:
        """Purge all stored snapshots for a task ID upon task completion.

        Args:
            task_id: Unique task identifier.
        """
        keys_to_delete = [k for k in self._snapshots if k[0] == task_id]
        for k in keys_to_delete:
            del self._snapshots[k]
