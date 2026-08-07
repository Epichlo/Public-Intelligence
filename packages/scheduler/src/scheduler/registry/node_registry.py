"""Node registry: in-memory reads, optionally written through to durable storage."""

from __future__ import annotations

import asyncio
import builtins
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scheduler.models.heartbeat import Heartbeat
    from scheduler.models.node import Node
    from scheduler.persistence import SchedulerStore

logger = logging.getLogger(__name__)


class NodeRegistry:
    """Registry of compute nodes, held in memory and optionally persisted.

    Stores Node objects keyed by node_id in insertion order.
    Also tracks runtime Heartbeat state for each node.
    Provides CRUD operations for node management.
    Contains no scheduler logic or networking.

    **The dicts remain the only read path.** When a store is attached, mutations are
    additionally written through to it and `load()` refills the dicts at startup;
    nothing reads from the store on a lookup. Reading through would put I/O on the
    hot path of every dispatch and every `filter_nodes` call -- `matchmaker.py`
    reaches straight into `_heartbeats` and `_telemetry` synchronously -- so the
    read-through design would have meant rewriting the matchmaker and the
    dispatcher to persist a node list. See specs/scheduler-persistence.md.

    With no store this is exactly the class it was before persistence existed,
    which is why `NodeRegistry()` still appears unchanged throughout the tests.
    """

    def __init__(self, store: SchedulerStore | None = None) -> None:
        """Build a registry, optionally backed by durable storage.

        Args:
            store: Where to write nodes and their credentials so they survive a
                restart. `None` means in-memory only -- every restart starts empty,
                which is the behaviour this class had before ROADMAP 2.1.
        """
        self._lock = asyncio.Lock()
        self._store = store
        self._nodes: dict[str, Node] = {}
        self._heartbeats: dict[str, Heartbeat] = {}
        self._dampeners: dict[str, float] = {}
        self._telemetry: dict[str, Any] = {}
        # Per-node control-API credentials, captured at registration. Held here
        # rather than on the Node model so they cannot be serialised into an API
        # response -- GET /nodes would otherwise hand out every node's secret.
        self._node_tokens: dict[str, str] = {}
        # Nodes observed on the Zenoh mesh. Dispatch queries these over the mesh instead
        # of dialling `ip_address`, which is how a node behind NAT is reached at all.
        # Held outside the Node model for the same reason as the tokens: it must not be
        # serialisable into an API response, and a node must not be able to assert it.
        self._mesh_nodes: set[str] = set()
        self.consensus_engine: Any = None

    async def load(self) -> None:
        """Refill the in-memory state from the store. Call once, at startup.

        Only nodes and their credentials come back. Heartbeats, telemetry, mesh
        reachability, and dampeners are deliberately *not* restored: they are
        observations from a moment that has passed, and presenting them as current
        is worse than not having them. The matchmaker already falls back to a
        node's registered `gpu.vram_available_gb` when there is no heartbeat, so a
        freshly loaded node is schedulable rather than filtered out. The table of
        what is persisted and why is in specs/scheduler-persistence.md.

        A no-op without a store, so startup does not need to know which it has.
        """
        if self._store is None:
            return
        nodes = await self._store.load_nodes()
        tokens = await self._store.load_node_tokens()
        async with self._lock:
            for node in nodes:
                self._nodes[node.node_id] = node
                self._dampeners[node.node_id] = 0.0
            self._node_tokens.update(tokens)
        logger.info("persistence_loaded: nodes=%d tokens=%d", len(nodes), len(tokens))

    # `get_node_token` is deliberately synchronous and does not take `self._lock`,
    # unlike every other accessor on this class. The lock exists to keep compound
    # read-modify-write sequences from interleaving at `await` points; a single dict
    # get contains no await point and cannot be interleaved on the event loop.
    # Acquiring the lock here would add an await to the hot path of every proxied
    # request, and would deadlock if it were ever called from inside an
    # already-locked section (`local_unregister_node` and `clear` mutate
    # `_node_tokens` directly for exactly that reason).
    #
    # If it ever grows a compound operation or an await, it must take the lock and
    # its callers must move off the locked paths.
    #
    # `set_node_token` *is* async, and was made so by ROADMAP 2.1. It is not on a
    # hot path -- it runs once per registration -- and it has to reach the store, or
    # a rotated credential would live only in memory and a restart would resurrect
    # the stale one. It still does not take the lock, for the deadlock reason above.

    async def set_node_token(self, node_id: str, token: str | None) -> None:
        """Remember the credential a node presented, for use when calling it back.

        Args:
            node_id: Node the credential belongs to.
            token: The credential. A falsy value clears any stored token.
        """
        if token:
            self._node_tokens[node_id] = token
        else:
            self._node_tokens.pop(node_id, None)
            self._mesh_nodes.discard(node_id)
        if self._store is not None:
            await self._store.save_node_token(node_id, token)

    def get_node_token(self, node_id: str) -> str | None:
        """Return the stored credential for a node, or None if unknown."""
        return self._node_tokens.get(node_id)

    # Lock-free for the same reason as the two methods above: a single set membership
    # test or insertion has no await point, and `is_mesh_reachable` sits on the hot path
    # of every dispatched request.

    def mark_mesh_reachable(self, node_id: str) -> None:
        """Record that traffic has arrived from this node over the Zenoh mesh.

        Called from the Zenoh router when a heartbeat, telemetry envelope, or liveliness
        token is seen -- evidence the node holds a live session, rather than a claim it
        made about itself.
        """
        self._mesh_nodes.add(node_id)

    def is_mesh_reachable(self, node_id: str) -> bool:
        """Return whether this node has been observed on the mesh."""
        return node_id in self._mesh_nodes

    async def register(self, node: Node) -> None:
        """Register a new node.

        If a consensus engine is active, propose the change atomically.
        Otherwise, perform local registration immediately.
        """
        engine = getattr(self, "consensus_engine", None)
        if engine is not None and engine.is_active():
            await engine.propose("register", node.model_dump())
        else:
            await self.local_register(node)

    async def local_register(self, node: Node) -> None:
        """Actually perform local registration of the node.

        The store write happens inside the lock, not after it. Outside, two
        concurrent writers could apply to memory in one order and to the database
        in the other, and the restart would disagree with the running process.
        Every persisting method below holds the lock for the same reason.
        """
        async with self._lock:
            if node.node_id in self._nodes:
                msg = f"Node already registered: {node.node_id}"
                raise ValueError(msg)
            self._nodes[node.node_id] = node
            self._dampeners[node.node_id] = 0.0
            if self._store is not None:
                await self._store.save_node(node)

    async def unregister(self, node_id: str) -> None:
        """Remove a node and its heartbeat from the registry.

        If a consensus engine is active, propose the change atomically.
        Otherwise, perform local unregistration immediately.
        """
        engine = getattr(self, "consensus_engine", None)
        if engine is not None and engine.is_active():
            await engine.propose("unregister", {"node_id": node_id})
        else:
            await self.local_unregister(node_id)

    async def local_unregister(self, node_id: str) -> None:
        """Actually perform local unregistration of the node."""
        async with self._lock:
            if node_id not in self._nodes:
                msg = f"Node not found: {node_id}"
                raise ValueError(msg)
            self._nodes.pop(node_id, None)
            self._heartbeats.pop(node_id, None)
            self._dampeners.pop(node_id, None)
            self._telemetry.pop(node_id, None)
            self._node_tokens.pop(node_id, None)
            self._mesh_nodes.discard(node_id)
            if self._store is not None:
                await self._store.delete_node(node_id)
        # The two ways a node can leave used to be asymmetric: eviction announced
        # itself whether or not it happened, and this path said nothing at all.
        # Both now log, so "where did node X go" is one grep rather than an
        # inference from a later listing.
        logger.info("node_departed: node_id=%s reason=unregistered", node_id)

    async def get(self, node_id: str) -> Node | None:
        """Look up a node by ID.

        Args:
            node_id: The ID of the node to retrieve.

        Returns:
            The Node if found, otherwise None.
        """
        async with self._lock:
            return self._nodes.get(node_id)

    async def list(self) -> builtins.list[Node]:
        """Return all registered nodes in insertion order.

        Returns:
            A list of all registered Node objects.
        """
        async with self._lock:
            return builtins.list(self._nodes.values())

    async def snapshot(self) -> builtins.list[tuple[Node, Heartbeat | None]]:
        """Return registered nodes paired with their latest heartbeat."""
        async with self._lock:
            return [(node, self._heartbeats.get(node_id)) for node_id, node in self._nodes.items()]

    async def update(self, node: Node) -> None:
        """Update an existing node's data.

        Args:
            node: The updated node. Must have a node_id that is already registered.

        Raises:
            ValueError: If the node_id is not registered.
        """
        async with self._lock:
            if node.node_id not in self._nodes:
                msg = f"Node not found: {node.node_id}"
                raise ValueError(msg)
            self._nodes[node.node_id] = node
            if self._store is not None:
                await self._store.save_node(node)

    async def set_available_models(self, node_id: str, models: builtins.list[str]) -> None:
        """Replace a node's advertised model catalogue.

        This is the only thing a node may restate about itself after registration.
        Its hardware is measured once per process and cannot change while that
        process lives; its model list changes whenever the host runs `ollama pull`
        or `ollama rm`. See specs/truthful-model-catalogue.md.

        The read-modify-write happens inside the lock rather than as a `get()` then
        `update()` pair, which would put an await between reading the node and
        writing it back and so could interleave with an unregister.

        `model_copy` rather than in-place mutation: `list()` hands out references to
        these same objects, so assigning to `node.available_models` would change the
        catalogue under a reader already iterating the result of a previous `list()`.

        Args:
            node_id: Node whose catalogue is being replaced.
            models: The node's current model identifiers.

        Raises:
            ValueError: If the node_id is not registered.
        """
        async with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                msg = f"Node not found: {node_id}"
                raise ValueError(msg)
            updated = node.model_copy(update={"available_models": list(models)})
            self._nodes[node_id] = updated
            if self._store is not None:
                await self._store.save_node(updated)

    async def exists(self, node_id: str) -> bool:
        """Check whether a node is registered.

        Args:
            node_id: The ID to check.

        Returns:
            True if the node is registered, False otherwise.
        """
        async with self._lock:
            return node_id in self._nodes

    async def clear(self) -> None:
        """Remove all nodes and heartbeats from the registry."""
        async with self._lock:
            self._nodes.clear()
            self._heartbeats.clear()
            self._dampeners.clear()
            self._telemetry.clear()
            self._node_tokens.clear()
            self._mesh_nodes.clear()
            if self._store is not None:
                await self._store.clear_nodes()

    async def count(self) -> int:
        """Return the number of registered nodes.

        Returns:
            The count of registered nodes.
        """
        async with self._lock:
            return len(self._nodes)

    async def update_heartbeat(self, heartbeat: Heartbeat) -> None:
        """Update the runtime state for a registered node with a new heartbeat.

        Args:
            heartbeat: The heartbeat containing runtime metrics.

        Raises:
            ValueError: If the node_id in heartbeat is not registered.
        """
        async with self._lock:
            if heartbeat.node_id not in self._nodes:
                msg = f"Node not found: {heartbeat.node_id}"
                raise ValueError(msg)
            self._heartbeats[heartbeat.node_id] = heartbeat
            # Decay cleanly on incoming heartbeat
            self._dampeners[heartbeat.node_id] = 0.0

    async def get_heartbeat(self, node_id: str) -> Heartbeat | None:
        """Get the latest heartbeat for a node.

        Args:
            node_id: The ID of the node.

        Returns:
            The Heartbeat if found, otherwise None.
        """
        async with self._lock:
            return self._heartbeats.get(node_id)

    async def get_dampener(self, node_id: str) -> float:
        """Get the scheduling dampener for a node.

        Args:
            node_id: The ID of the node.

        Returns:
            The dampener value.
        """
        async with self._lock:
            return self._dampeners.get(node_id, 0.0)

    async def increment_dampener(self, node_id: str) -> None:
        """Increment the scheduling dampener for a node by 0.1.

        Args:
            node_id: The ID of the node.

        Raises:
            ValueError: If the node_id is not registered.
        """
        async with self._lock:
            if node_id not in self._nodes:
                msg = f"Node not found: {node_id}"
                raise ValueError(msg)
            self._dampeners[node_id] = self._dampeners.get(node_id, 0.0) + 0.1

    async def unregister_node(self, node_id: str) -> bool:
        """Unregister a node and clear its dynamic herd dampeners.

        If a consensus engine is active, propose the change atomically.
        Otherwise, perform local unregistration immediately.

        Returns:
            Whether the node is gone as a result. This used to return None, so the
            caller logged "evicted" on the strength of having *asked* -- see
            specs/eviction-reports-what-it-did.md.

            On the consensus path this method cannot know whether the proposal was
            applied: `propose` returns immediately, and a dropped, queued or
            election-lost proposal is indistinguishable from an applied one. So it
            does not claim to have removed anything -- it reports whether the node
            is absent afterwards. That is a weaker statement, and the true one.
        """
        engine = getattr(self, "consensus_engine", None)
        if engine is not None and engine.is_active():
            await engine.propose("unregister_node", {"node_id": node_id})
            return not await self.exists(node_id)
        return await self.local_unregister_node(node_id)

    async def local_unregister_node(self, node_id: str) -> bool:
        """Actually perform local unregistration of the node (safe if not present).

        This is the path stale eviction and deathrattles take, so the store write
        matters as much as it does on the explicit `DELETE /nodes/{id}`: without it
        every eviction would be undone by the next restart.

        Returns:
            True if the node was present and has been removed. Tolerating an absent
            node is correct; being unable to tell the two cases apart is what made
            the caller's log untrustworthy.
        """
        async with self._lock:
            was_present = node_id in self._nodes
            self._nodes.pop(node_id, None)
            self._heartbeats.pop(node_id, None)
            self._dampeners.pop(node_id, None)
            self._telemetry.pop(node_id, None)
            self._node_tokens.pop(node_id, None)
            self._mesh_nodes.discard(node_id)
            if self._store is not None:
                await self._store.delete_node(node_id)
        if was_present:
            logger.info("node_departed: node_id=%s reason=evicted", node_id)
        return was_present
