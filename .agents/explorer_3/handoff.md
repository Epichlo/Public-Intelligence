# Phase 4.6 Architectural Handoff Report: Asymmetric Split-Inference & Local Boundary Security

**Author**: Codebase Architecture Explorer 3  
**Working Directory**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_3`  
**Date**: 2026-07-29  

---

## 1. Observation

Direct observations from codebase inspection:

1. **Pipeline Stage Allocation (`Scheduler/src/scheduler/core/engine.py:72-216`)**:
   - `SchedulingEngine.schedule_pipeline(task)` partitions all model layers from `start_layer = 0` to `end_layer = total_layers - 1` across registered remote compute nodes:
     ```python
     # Lines 189-201
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
     ```
   - In this logic, Stage 0 (`start_layer = 0`, Embedding) and Stage $M-1$ (`end_layer = total_layers - 1`, LM Head) are assigned to remote worker nodes in `node_capacities`.

2. **Pipeline Models (`Scheduler/src/scheduler/models/pipeline.py:27-58, 59-108` and `Node/src/node/models/sharding.py:28-58`)**:
   - `PipelineStage` has fields `stage_index`, `total_stages`, `layer_range`, `node_id`, and `model_id`. It currently has no fields indicating local vs. remote boundary execution (`is_local_boundary`) or stage type classification (`local_embedding`, `remote_transformer`, `local_lm_head`).
   - `PipelineConfig` validates index continuity and layer coverage from `start_layer == 0` to `end_layer == total_layers - 1`, but does not enforce local boundary isolation rules.

3. **Tensor Transport (`Node/src/node/models/sharding.py:60-76` & `Node/src/node/core/transport.py:209-233`)**:
   - `TensorPayload` models data payloads across stages with fields `task_id`, `stage_index`, `data`, `shape`, `dtype`, `shm_name`.
   - `get_tensor_topic` builds topics: `public-intelligence/net/tasks/<task_id>/tensors/<stage_index>`.

4. **Existing Test Suite Footprint**:
   - `Scheduler/tests` contains 15 test files (including `test_pipeline_scheduler.py` which tests standard VRAM layer partitioning across 1..3 nodes).
   - `Node/tests` contains 18 test files (including `test_sharding.py` for models, `test_transport.py` for IPC, `test_end_to_end_pipeline.py` for task execution, and `test_m2_adversarial.py` for stability).

---

## 2. Logic Chain

1. **From Observation 1**: Current `schedule_pipeline` allocates Layer 0 (Embedding) to the first remote node in `stage_allocations`.
2. **Step 2**: Layer 0 processes raw text prompts or token IDs to produce hidden activation vectors $H_0$. If Stage 0 runs on an untrusted remote node, the client must transmit raw prompt text to that node over the network, violating the zero prompt leakage requirement of Phase 4.6.
3. **Step 3**: To enforce local boundary isolation (Requirement R1 & R3), Stage 0 (Embedding, Layer 0) and Stage $M+1$ (LM Head, Layer $N-1$) must be assigned to the local client (`client_node_id`, `is_local_boundary=True`), while intermediate remote nodes are assigned only intermediate transformer layers ($1 \dots N-2$).
4. **From Observation 2**: Updating `PipelineStage` to include `is_local_boundary: bool` and `stage_type: str`, and adding a model validator `validate_split_inference_boundaries` to `PipelineConfig`, enables strict runtime verification of local boundary isolation before task dispatch.
5. **From Observation 3 & 4**: Zero prompt leakage can be verified independently by adding a security packet inspection test suite (`test_zero_prompt_leakage_security.py`), unit tests for split allocation (`test_split_inference_scheduler.py` and `test_split_inference_node.py`), and an end-to-end split-inference integration test (`test_end_to_end_split_inference.py`).

---

## 3. Caveats

- **No Caveats**: All codebase files, domain models, chain allocator functions, and test structures were directly examined. The architectural specification is complete and actionable.

---

## 4. Conclusion

To implement Phase 4.6 Asymmetric Split-Inference & Local Boundary Security:
1. Extend `PipelineStage` with `is_local_boundary: bool = False` and `stage_type: str = "remote_transformer"` in both `Scheduler/src/scheduler/models/pipeline.py` and `Node/src/node/models/sharding.py`.
2. Extend `PipelineConfig` with `split_inference: bool = True` and a validator enforcing that Stage 0 is local embedding (`start_layer=0`) and Stage $M+1$ is local LM Head (`end_layer=N-1`).
3. Refactor `SchedulingEngine.schedule_pipeline()` in `Scheduler/src/scheduler/core/engine.py` to automatically allocate local Stage 0 (Embedding) and local Stage $M+1$ (LM Head) to `client_node_id`, partitioning only intermediate layers ($1 \dots N-2$) across remote worker nodes.
4. Add 4 test suites:
   - `Scheduler/tests/test_split_inference_scheduler.py` (Unit & matchmaker tests for split allocation)
   - `Node/tests/test_split_inference_node.py` (Unit tests for payload & split backend)
   - `Node/tests/test_zero_prompt_leakage_security.py` (Security verification auditing packet payloads for zero prompt text/token exposure)
   - `Node/tests/test_end_to_end_split_inference.py` (E2E split execution loop)

---

## 5. Verification Method

To independently verify the implementation after coding:

1. **Detailed Analysis Reference**:
   - Inspect `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_3/analysis.md` for full code snippets, domain model definitions, and test case blueprints.

2. **Automated Verification Command**:
   Run full test suite and static checks across both sub-repositories:
   ```bash
   # Run pytest on Scheduler and Node
   pytest Scheduler/tests Node/tests

   # Run ruff check and formatting check
   ruff check Scheduler Node
   ruff format --check Scheduler Node

   # Run mypy static typing
   mypy Scheduler/src Node/src
   ```

3. **Zero Prompt Leakage Verification Invalidation Condition**:
   The verification fails if any remote node in `test_zero_prompt_leakage_security.py` receives raw prompt text, integer token ID lists, or Layer 0 embedding weights in any network frame or memory buffer.
