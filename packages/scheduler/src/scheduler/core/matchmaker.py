"""Capability Matchmaker scheduling strategy implementation."""

from collections.abc import Callable
from typing import Any

from scheduler.core.canary import CanaryVerifier
from scheduler.core.strategy import SchedulingStrategy
from scheduler.models.node import Node
from scheduler.registry.node_registry import NodeRegistry


class CapabilityMatchmaker(SchedulingStrategy):
    """Concrete scheduling strategy based on hardware capability and dynamic telemetry load."""

    def __init__(
        self,
        registry: NodeRegistry,
        canary: CanaryVerifier | None = None,
        in_flight: Callable[[str], float] | None = None,
    ) -> None:
        """Initialize the matchmaker with a registry reference for telemetry lookup.

        Args:
            registry: Reference to the active NodeRegistry instance.
            canary: Optional canary verifier (decision D1). When supplied,
                quarantined nodes are excluded from dispatch. `None` keeps the
                pre-D1 behaviour, which is what every existing test constructs.
            in_flight: Optional source of per-node EPHEMERAL assignment pressure
                (a node_id -> count callable, owned by the SchedulingEngine).
                The registry's `_telemetry` dict holds only VERIFIED telemetry
                reported over the mesh; synthetic assignment counters were once
                written into it and never decremented, so un-telemetered nodes
                accumulated uncapped negative score. Pressure from assignments
                now combines with verified telemetry here, at read time.
        """
        self.registry = registry
        self.canary = canary
        self.in_flight = in_flight

    def set_in_flight_source(self, source: Callable[[str], float]) -> None:
        """Attach the engine's pressure source (called by the engine at wiring)."""
        self.in_flight = source

    def filter_nodes(self, task_requirements: dict[str, Any], live_nodes: list[Node]) -> list[Node]:
        """Filter live nodes based on hard VRAM, model, and backend requirements.

        Args:
            task_requirements: Task hard constraints.
            live_nodes: List of currently online compute nodes.

        Returns:
            List of eligible nodes.
        """
        eligible = []
        for node in live_nodes:
            # 0. Canary quarantine (decision D1).
            #
            # FIRST, and before any capability check, because this is the only
            # filter that is about whether the node is telling the truth rather
            # than about what it can do. A node returning `token_556` satisfies
            # every requirement below it perfectly.
            #
            # Exclusion here rather than at registration is deliberate: a
            # quarantined node stays registered, keeps heartbeating and remains
            # visible in `GET /nodes`, so an operator can see it is being skipped
            # and why. Silently dropping it from the registry would look like the
            # node had gone away.
            if self.canary is not None and self.canary.is_quarantined(node.node_id):
                continue

            # 1. Model Support Match
            model_req = task_requirements.get("model_name") or task_requirements.get("model")
            if model_req and model_req not in node.available_models:
                continue

            # 2. Minimum VRAM Match
            min_vram_gb = task_requirements.get("min_vram_gb") or task_requirements.get("vram")
            if min_vram_gb is not None:
                heartbeat = self.registry._heartbeats.get(node.node_id)
                vram_available = getattr(heartbeat, "vram_available_gb", node.gpu.vram_available_gb)
                if vram_available < float(min_vram_gb):
                    continue

            # 3. Backend Type Match
            backend_req = task_requirements.get("backend_type")
            if backend_req:
                telemetry = self.registry._telemetry.get(node.node_id, {})
                backend_type = telemetry.get("backend_type")
                # Fallback to matching standard metadata or properties
                if not backend_type or str(backend_type).lower() != str(backend_req).lower():
                    continue

            eligible.append(node)

        return eligible

    # `task` is unread here but required by the SchedulingStrategy ABC in
    # strategy.py; this implementation scores purely on live node load.
    def score_nodes(
        self,
        task: dict[str, Any],  # noqa: ARG002
        eligible_nodes: list[Node],
    ) -> list[tuple[Node, float]]:
        """Rank eligible nodes by dynamic load metrics and reliability score.

        Fitness score formula:
        score = (reliability * 100) - (queue_depth * 15) - (cpu_util * 0.5)
                - (in_flight * 15)

        `queue_depth`, `cpu` and `reliability` come from VERIFIED telemetry in
        the registry (falling back to the node's own heartbeat, then neutral
        defaults). `in_flight` is the engine's ephemeral assignment pressure,
        combined here at read time rather than stored into the telemetry dict.

        Args:
            task: Task details (unused in default scoring).
            eligible_nodes: Filtered subset of nodes.

        Returns:
            Sorted list of (Node, score) tuples.
        """
        scored_list = []
        for node in eligible_nodes:
            node_id = node.node_id
            telemetry = self.registry._telemetry.get(node_id, {})
            heartbeat = self.registry._heartbeats.get(node_id)

            # Get queue depth from VERIFIED telemetry (lower queue depth
            # increases score)
            current_queue_depth = float(
                telemetry.get(
                    "current_queue_depth",
                    telemetry.get("queue_depth", getattr(heartbeat, "queue_length", 0)),
                )
            )

            # Get CPU utilization (minimal CPU utilization increases score)
            current_cpu_utilization_pct = float(
                telemetry.get(
                    "current_cpu_utilization_pct",
                    telemetry.get(
                        "cpu_utilization",
                        getattr(heartbeat, "cpu_utilization", 0.0),
                    ),
                )
            )

            # Get historical reliability score (maximum reliability increases score)
            reliability_score = float(
                telemetry.get(
                    "reliability_score",
                    telemetry.get("reliability", 1.0),
                )
            )

            # Ephemeral pressure: assignments this engine has made that have not
            # been released or TTL-expired. Same weight per request as a verified
            # queued request, so both kinds of busyness compare.
            in_flight_count = float(self.in_flight(node_id)) if self.in_flight else 0.0

            # Compute dynamic fitness score
            score = (
                (reliability_score * 100.0)
                - (current_queue_depth * 15.0)
                - (current_cpu_utilization_pct * 0.5)
                - (in_flight_count * 15.0)
            )
            scored_list.append((node, score))

        # Sort descending by score
        scored_list.sort(key=lambda item: item[1], reverse=True)
        return scored_list
