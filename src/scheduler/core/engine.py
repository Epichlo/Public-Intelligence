"""Orchestration engine for multi-stage scheduling."""

import hashlib
import uuid
from typing import TYPE_CHECKING, Any

from scheduler.core.strategy import SchedulingStrategy
from scheduler.models.pipeline import LayerRange, PipelineStage
from scheduler.registry.node_registry import NodeRegistry

if TYPE_CHECKING:
    from scheduler.models.node import Node


class SchedulingEngine:
    """Orchestration engine implementing two-stage node task scheduling."""

    def __init__(self, registry: NodeRegistry, strategy: SchedulingStrategy) -> None:
        """Initialize the SchedulingEngine.

        Args:
            registry: The active NodeRegistry instance.
            strategy: The SchedulingStrategy algorithm provider.
        """
        self.registry = registry
        self.strategy = strategy

    async def schedule_task(self, task: dict[str, Any]) -> tuple[str, str]:
        """Schedule an incoming task to the highest-scoring eligible node.

        Stages the task requirements through capability filtering and telemetry-based
        scoring, updates the node's tracked load, and generates a transaction hash.

        Args:
            task: Dict detailing the task parameters and requirements.

        Returns:
            A tuple of (transaction_hash, node_id).

        Raises:
            ValueError: If no active nodes satisfy the task hard constraints.
        """
        # 1. Retrieve all registered live nodes
        live_nodes = await self.registry.list()

        # 2. Stage 1: Filter nodes by hard requirements
        requirements = task.get("requirements", {})
        eligible_nodes = self.strategy.filter_nodes(requirements, live_nodes)

        if not eligible_nodes:
            raise ValueError("No active nodes satisfy the task requirements.")

        # 3. Stage 2: Score eligible nodes by current load
        ranked_nodes = self.strategy.score_nodes(task, eligible_nodes)
        selected_node, score = ranked_nodes[0]

        # 4. Update the inner state tracking registry (dynamic queue depth update)
        node_id = selected_node.node_id
        if node_id not in self.registry._telemetry:
            self.registry._telemetry[node_id] = {}

        current_q = self.registry._telemetry[node_id].get("queue_depth", 0)
        self.registry._telemetry[node_id]["queue_depth"] = current_q + 1

        # 5. Route the transaction hash out (SHA-256 of node_id + task_id + score)
        task_id = task.get("task_id", str(uuid.uuid4()))
        tx_raw = f"{node_id}:{task_id}:{score}"
        tx_hash = hashlib.sha256(tx_raw.encode("utf-8")).hexdigest()

        return tx_hash, node_id

    async def schedule_pipeline(self, task: dict[str, Any]) -> tuple[str, list[PipelineStage]]:
        """Schedule a model execution pipeline across one or more compute nodes.

        Partition layers across eligible nodes according to available VRAM.

        Args:
            task: Dict detailing task parameters including model, total_layers,
                and VRAM requirements per layer.

        Returns:
            A tuple of (transaction_hash, list of PipelineStage objects).

        Raises:
            ValueError: If no active nodes satisfy requirements or cluster VRAM is insufficient.
        """
        task_id = str(task.get("task_id", uuid.uuid4()))
        model_id = str(task.get("model_id") or task.get("model") or "")
        total_layers = int(task.get("total_layers", 32))

        if total_layers <= 0:
            raise ValueError("total_layers must be greater than 0")

        # 1. Retrieve all registered live nodes
        live_nodes = await self.registry.list()
        if not live_nodes:
            raise ValueError("No active nodes available in registry.")

        # 2. Filter nodes by task hard requirements
        requirements = dict(task.get("requirements", {}))
        if model_id and "model" not in requirements and "model_name" not in requirements:
            requirements["model"] = model_id

        eligible_nodes = self.strategy.filter_nodes(requirements, live_nodes)
        if not eligible_nodes:
            raise ValueError("No active nodes satisfy the pipeline task requirements.")

        # Rank eligible nodes by fitness score
        ranked_tuples = self.strategy.score_nodes(task, eligible_nodes)
        ranked_nodes = [n for n, _ in ranked_tuples] if ranked_tuples else eligible_nodes

        # 3. Determine VRAM required per layer (in GB)
        vram_per_layer_val = task.get("vram_per_layer_gb")
        if vram_per_layer_val is None:
            vram_per_layer_val = task.get("layer_vram_gb")
        if vram_per_layer_val is None and "vram_per_layer_mb" in task:
            vram_per_layer_val = float(task["vram_per_layer_mb"]) / 1024.0
        if vram_per_layer_val is None and "model_vram_gb" in task:
            vram_per_layer_val = float(task["model_vram_gb"]) / float(total_layers)
        if vram_per_layer_val is None and "vram_required_gb" in task:
            vram_per_layer_val = float(task["vram_required_gb"]) / float(total_layers)

        vram_per_layer: float = (
            float(vram_per_layer_val) if vram_per_layer_val is not None else 0.5
        )

        # Calculate VRAM layer capacities per node
        node_capacities: list[tuple[Node, int]] = []
        total_cluster_capacity = 0
        for node in ranked_nodes:
            heartbeat = self.registry._heartbeats.get(node.node_id)
            avail_vram = (
                getattr(heartbeat, "vram_available_gb", node.gpu.vram_available_gb)
                if heartbeat is not None
                else node.gpu.vram_available_gb
            )
            cap = int(avail_vram // vram_per_layer) if vram_per_layer > 0 else total_layers
            if cap > 0:
                node_capacities.append((node, cap))
                total_cluster_capacity += cap

        if total_cluster_capacity < total_layers:
            raise ValueError(
                f"Insufficient VRAM in cluster: required {total_layers} layers, "
                f"but cluster can only host {total_cluster_capacity} layers."
            )

        # 4. Partition layers across nodes
        num_stages_requested = task.get("num_stages") or task.get("target_stages")
        stage_allocations: list[tuple[Node, int]] = []

        if num_stages_requested is not None:
            num_stages = int(num_stages_requested)
            if num_stages <= 0:
                raise ValueError("num_stages must be > 0")
            if len(node_capacities) < num_stages:
                raise ValueError(
                    f"Requested {num_stages} stages, but only "
                    f"{len(node_capacities)} eligible nodes available."
                )
            base_l = total_layers // num_stages
            rem_l = total_layers % num_stages
            for i in range(num_stages):
                node, cap = node_capacities[i]
                assigned = base_l + (1 if i < rem_l else 0)
                if assigned > cap:
                    raise ValueError(
                        f"Node {node.node_id} capacity ({cap} layers) "
                        f"insufficient for stage assignment ({assigned} layers)."
                    )
                stage_allocations.append((node, assigned))
        else:
            remaining = total_layers
            for node, cap in node_capacities:
                if remaining <= 0:
                    break
                assigned = min(remaining, cap)
                stage_allocations.append((node, assigned))
                remaining -= assigned

            if remaining > 0:
                raise ValueError("Insufficient VRAM across cluster to schedule pipeline.")

        # 5. Build PipelineStage objects
        total_stages = len(stage_allocations)
        stages: list[PipelineStage] = []
        current_layer = 0

        for idx, (node, layer_count) in enumerate(stage_allocations):
            start_layer = current_layer
            end_layer = current_layer + layer_count - 1
            current_layer = end_layer + 1

            layer_range = LayerRange(start_layer=start_layer, end_layer=end_layer)
            stage = PipelineStage(
                stage_index=idx,
                total_stages=total_stages,
                layer_range=layer_range,
                node_id=node.node_id,
                model_id=model_id,
            )
            stages.append(stage)

            # Update telemetry queue depth & dampeners
            if node.node_id not in self.registry._telemetry:
                self.registry._telemetry[node.node_id] = {}
            cur_q = self.registry._telemetry[node.node_id].get("queue_depth", 0)
            self.registry._telemetry[node.node_id]["queue_depth"] = cur_q + 1
            await self.registry.increment_dampener(node.node_id)

        # 6. Generate transaction hash
        stage_nodes = ",".join(s.node_id for s in stages)
        tx_raw = f"pipeline:{task_id}:{total_stages}:{stage_nodes}"
        tx_hash = hashlib.sha256(tx_raw.encode("utf-8")).hexdigest()

        return tx_hash, stages
