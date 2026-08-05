"""In-memory node registry for storing and managing compute nodes."""

from __future__ import annotations

import asyncio
import builtins
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scheduler.models.heartbeat import Heartbeat
    from scheduler.models.node import Node


class NodeRegistry:
    """Thread-safe in-memory registry of compute nodes.

    Stores Node objects keyed by node_id in insertion order.
    Also tracks runtime Heartbeat state for each node.
    Provides CRUD operations for node management.
    Contains no scheduler logic, persistence, or networking.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
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

    # These two are deliberately synchronous and do not take `self._lock`, unlike
    # every other accessor on this class. The lock exists to keep compound
    # read-modify-write sequences from interleaving at `await` points; a single
    # dict get or set contains no await point and cannot be interleaved on the
    # event loop. Acquiring the lock here would add an await to the hot path of
    # every proxied request, and would deadlock if either method were ever called
    # from inside an already-locked section (`local_unregister_node` and `clear`
    # mutate `_node_tokens` directly for exactly that reason).
    #
    # If either method ever grows a compound operation or an await, it must take
    # the lock and its callers must move off the locked paths.

    def set_node_token(self, node_id: str, token: str | None) -> None:
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
        """Actually perform local registration of the node."""
        async with self._lock:
            if node.node_id in self._nodes:
                msg = f"Node already registered: {node.node_id}"
                raise ValueError(msg)
            self._nodes[node.node_id] = node
            self._dampeners[node.node_id] = 0.0

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
            self._nodes[node_id] = node.model_copy(update={"available_models": list(models)})

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

    async def unregister_node(self, node_id: str) -> None:
        """Unregister a node and clear its dynamic herd dampeners.

        If a consensus engine is active, propose the change atomically.
        Otherwise, perform local unregistration immediately.
        """
        engine = getattr(self, "consensus_engine", None)
        if engine is not None and engine.is_active():
            await engine.propose("unregister_node", {"node_id": node_id})
        else:
            await self.local_unregister_node(node_id)

    async def local_unregister_node(self, node_id: str) -> None:
        """Actually perform local unregistration of the node (safe if not present)."""
        async with self._lock:
            self._nodes.pop(node_id, None)
            self._heartbeats.pop(node_id, None)
            self._dampeners.pop(node_id, None)
            self._telemetry.pop(node_id, None)
            self._node_tokens.pop(node_id, None)
            self._mesh_nodes.discard(node_id)
