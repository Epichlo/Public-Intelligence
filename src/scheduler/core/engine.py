"""Orchestration engine for multi-stage scheduling."""

import hashlib
import uuid
from typing import TYPE_CHECKING, Any

from scheduler.core.strategy import SchedulingStrategy
from scheduler.models.pipeline import (
    KVCacheSnapshot,
    LayerRange,
    PipelineStage,
    StageType,
    TaskProposal,
)
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

        vram_per_layer: float = float(vram_per_layer_val) if vram_per_layer_val is not None else 0.5

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

    async def schedule_split_inference_pipeline(
        self,
        task: dict[str, Any] | TaskProposal | Any,
        total_layers: int = 32,
    ) -> list[PipelineStage]:
        """Schedule a 3-tier asymmetric split-inference chain across local/remote nodes.

        Stage 0 (Client Local Embedding): stage_index=0, layer_range=LayerRange(0, 0),
            node_id="client_local", is_local_boundary=True, stage_type=StageType.CLIENT_EMBEDDING,
            is_split_inference=True.
        Stages 1..K-1 (Remote Host Pipeline): Partition layers 1..total_layers-1 across eligible
            nodes based on VRAM, is_local_boundary=False,
            stage_type=StageType.REMOTE_HIDDEN, is_split_inference=True.
        Stage K (Client Local LM Head): stage_index=K, layer_range=LayerRange(total_layers,
            total_layers), node_id="client_local", is_local_boundary=True,
            stage_type=StageType.CLIENT_LM_HEAD, is_split_inference=True.

        Args:
            task: Task dictionary or TaskProposal object detailing model requirements.
            total_layers: Total number of transformer model layers.

        Returns:
            A list of PipelineStage objects representing the split-inference chain.

        Raises:
            ValueError: If total_layers < 2, no active nodes exist, or cluster VRAM is low.
        """
        if isinstance(task, dict):
            task_dict = task
        elif hasattr(task, "model_dump"):
            task_dict = task.model_dump()
        elif hasattr(task, "dict"):
            task_dict = task.dict()
        else:
            task_dict = getattr(task, "__dict__", {})

        model_id = str(task_dict.get("model_id") or task_dict.get("model") or "")
        t_layers_val = task_dict.get("total_layers", total_layers)
        t_layers = int(t_layers_val) if t_layers_val is not None else total_layers

        if t_layers < 2:
            raise ValueError("total_layers must be at least 2 for split inference")

        # Retrieve live eligible compute nodes for remote intermediate stages
        live_nodes = await self.registry.list()
        if not live_nodes:
            raise ValueError("No active nodes available in registry.")

        requirements = dict(task_dict.get("requirements", {}))
        if model_id and "model" not in requirements and "model_name" not in requirements:
            requirements["model"] = model_id

        eligible_nodes = self.strategy.filter_nodes(requirements, live_nodes)
        if not eligible_nodes:
            raise ValueError("No active nodes satisfy the split-inference task requirements.")

        ranked_tuples = self.strategy.score_nodes(task_dict, eligible_nodes)
        ranked_nodes = [n for n, _ in ranked_tuples] if ranked_tuples else eligible_nodes

        # Intermediate layers to partition on remote hosts: layers 1 to t_layers - 1
        num_remote_layers = t_layers - 1
        vram_per_layer_val = task_dict.get("vram_per_layer_gb") or task_dict.get("layer_vram_gb")
        if vram_per_layer_val is None and "vram_required_gb" in task_dict:
            vram_per_layer_val = float(task_dict["vram_required_gb"]) / float(t_layers)
        vram_per_layer: float = float(vram_per_layer_val) if vram_per_layer_val is not None else 0.5

        node_capacities: list[tuple[Node, int]] = []
        total_cluster_capacity = 0
        for node in ranked_nodes:
            heartbeat = self.registry._heartbeats.get(node.node_id)
            avail_vram = (
                getattr(heartbeat, "vram_available_gb", node.gpu.vram_available_gb)
                if heartbeat is not None
                else node.gpu.vram_available_gb
            )
            cap = int(avail_vram // vram_per_layer) if vram_per_layer > 0 else num_remote_layers
            if cap > 0:
                node_capacities.append((node, cap))
                total_cluster_capacity += cap

        if total_cluster_capacity < num_remote_layers:
            raise ValueError(
                f"Insufficient VRAM in cluster for intermediate layers: "
                f"req {num_remote_layers}, avail {total_cluster_capacity}."
            )

        # Partition intermediate layers across eligible nodes
        remote_allocations: list[tuple[Node, int]] = []
        remaining = num_remote_layers
        for node, cap in node_capacities:
            if remaining <= 0:
                break
            assigned = min(remaining, cap)
            remote_allocations.append((node, assigned))
            remaining -= assigned

        if remaining > 0:
            raise ValueError(
                "Insufficient VRAM across cluster to schedule intermediate split layers."
            )

        num_remote_stages = len(remote_allocations)
        total_stages = (
            num_remote_stages + 2
        )  # Stage 0 (Local Embedding) + Remote Hidden Stages + Stage K (Local LM Head)

        stages: list[PipelineStage] = []

        # 1. Stage 0: Client Local Embedding
        stage_0 = PipelineStage(
            stage_index=0,
            total_stages=total_stages,
            layer_range=LayerRange(start_layer=0, end_layer=0),
            node_id="client_local",
            model_id=model_id,
            is_local_boundary=True,
            stage_type=StageType.CLIENT_EMBEDDING,
            is_split_inference=True,
        )
        stages.append(stage_0)

        # 2. Stages 1..K-1: Remote Host Pipeline
        current_remote_layer = 1
        for idx, (node, layer_count) in enumerate(remote_allocations):
            start_l = current_remote_layer
            end_l = current_remote_layer + layer_count - 1
            current_remote_layer = end_l + 1

            r_stage = PipelineStage(
                stage_index=idx + 1,
                total_stages=total_stages,
                layer_range=LayerRange(start_layer=start_l, end_layer=end_l),
                node_id=node.node_id,
                model_id=model_id,
                is_local_boundary=False,
                stage_type=StageType.REMOTE_HIDDEN,
                is_split_inference=True,
            )
            stages.append(r_stage)

            if node.node_id not in self.registry._telemetry:
                self.registry._telemetry[node.node_id] = {}
            cur_q = self.registry._telemetry[node.node_id].get("queue_depth", 0)
            self.registry._telemetry[node.node_id]["queue_depth"] = cur_q + 1
            await self.registry.increment_dampener(node.node_id)

        # 3. Stage K: Client Local LM Head
        stage_k = PipelineStage(
            stage_index=total_stages - 1,
            total_stages=total_stages,
            layer_range=LayerRange(start_layer=t_layers, end_layer=t_layers),
            node_id="client_local",
            model_id=model_id,
            is_local_boundary=True,
            stage_type=StageType.CLIENT_LM_HEAD,
            is_split_inference=True,
        )
        stages.append(stage_k)

        # Validation: verify local boundary placement and layer continuity.
        if (
            not stages[0].is_local_boundary
            or stages[0].stage_type not in (StageType.CLIENT_EMBEDDING, "client_embedding")
            or stages[0].node_id != "client_local"
            or stages[0].layer_range.start_layer != 0
            or stages[0].layer_range.end_layer != 0
        ):
            raise ValueError("Invalid split-inference client embedding boundary stage")

        if (
            not stages[-1].is_local_boundary
            or stages[-1].stage_type not in (StageType.CLIENT_LM_HEAD, "client_lm_head")
            or stages[-1].node_id != "client_local"
            or stages[-1].layer_range.start_layer != t_layers
            or stages[-1].layer_range.end_layer != t_layers
        ):
            raise ValueError("Invalid split-inference client LM head boundary stage")

        if stages[1].layer_range.start_layer != 1:
            raise ValueError("Split-inference remote stages must start at layer 1")
        for i in range(1, len(stages) - 2):
            if stages[i].layer_range.end_layer + 1 != stages[i + 1].layer_range.start_layer:
                raise ValueError("Split-inference remote stage layer ranges must be contiguous")
        if stages[-2].layer_range.end_layer != t_layers - 1:
            raise ValueError("Split-inference remote stages must end before the LM head layer")

        for r_s in stages[1:-1]:
            if (
                r_s.is_local_boundary
                or r_s.stage_type not in (StageType.REMOTE_HIDDEN, "remote_hidden")
                or not r_s.is_split_inference
            ):
                raise ValueError("Invalid split-inference remote hidden stage")

        return stages

    async def restitch_pipeline_on_eviction(
        self,
        task_id: str,
        failed_node_id: str,
        kv_snapshot: KVCacheSnapshot,
        pipeline_stages: list[PipelineStage],
    ) -> list[PipelineStage]:
        """Restitch pipeline stages when a compute node is evicted, restoring from KVCacheSnapshot.

        Args:
            task_id: Unique pipeline task identifier.
            failed_node_id: Identifier of the evicted compute node.
            kv_snapshot: Validated KVCacheSnapshot to restore computation state from.
            pipeline_stages: Existing pipeline stages configuration.

        Returns:
            Updated list of PipelineStage objects with replacement node assigned.
        """
        kv_snapshot.verify_checksum()

        active_nodes = await self.registry.list()
        available_nodes = [n for n in active_nodes if n.node_id != failed_node_id]

        if not available_nodes:
            raise ValueError(f"No replacement compute nodes available to restitch task {task_id}")

        replacement = available_nodes[0]
        restitched_stages: list[PipelineStage] = []

        for stage in pipeline_stages:
            if stage.node_id == failed_node_id:
                new_stage = PipelineStage(
                    stage_index=stage.stage_index,
                    total_stages=stage.total_stages,
                    layer_range=stage.layer_range,
                    node_id=replacement.node_id,
                    model_id=stage.model_id,
                    is_local_boundary=stage.is_local_boundary,
                    stage_type=stage.stage_type,
                    is_split_inference=stage.is_split_inference,
                )
                restitched_stages.append(new_stage)
            else:
                restitched_stages.append(stage)

        return restitched_stages
