# Phase 4.6 Architectural Analysis & Test Suite Specification: Asymmetric Split-Inference & Local Boundary Security

**Author**: Codebase Architecture Explorer 3  
**Target Subsystems**: `Scheduler` (`SchedulingEngine`, `PipelineStage`, `PipelineConfig`), `Node` (`TensorPayload`, `Runtime`, `Transport`), and Test Suites (`Scheduler/tests`, `Node/tests`).  
**Date**: 2026-07-29  

---

## 1. Executive Summary & Mission Objective

Phase 4.6 introduces **Asymmetric Split-Inference & Local Boundary Security** to Public Intelligence. The core requirement is to decouple raw prompt tokens from untrusted network nodes by executing **Layer 0 (Embedding)** and the **Final LM Head (Unembedding / Projection)** locally on the client/edge gateway. Intermediate network nodes process only intermediate transformer layers (Layers 1 to $N-2$) via high-dimensional hidden activation vectors passed over backpressured Zenoh channels (`TensorPayload`).

This document provides a comprehensive analysis of the existing pipeline allocation implementation (`SchedulingEngine.schedule_pipeline()` in `Scheduler/src/scheduler/core/engine.py` and `PipelineStage` in `Scheduler/src/scheduler/models/pipeline.py`), details the necessary domain model and chain allocator updates, establishes local boundary verification invariants, and maps out the exact unit, integration, and security test suites needed for 100% test coverage and zero prompt leakage verification.

---

## 2. Current Architecture Audit & Gaps

### 2.1 Existing Pipeline Allocation (`SchedulingEngine.schedule_pipeline`)
In the current implementation (`Scheduler/src/scheduler/core/engine.py`, lines 72–216):
- `schedule_pipeline` accepts a task dictionary containing `total_layers` (e.g., 32), `model_id`, and VRAM requirements per layer.
- It ranks registered cluster nodes by fitness score ($\text{Score} = \text{Reliability} \times 100 - \text{QueueDepth} \times 15 - \text{CPUUtil} \times 0.5$).
- It partitions all layers $0 \dots (N-1)$ directly across remote cluster nodes.
- **Security Vulnerability in Split-Inference Context**: Stage 0 (`start_layer = 0`) is currently assigned to a remote node. Under standard pipeline parallelism, this requires sending the raw prompt string or token ID list to the remote node for Layer 0 embedding. Similarly, Stage $(M-1)$ (`end_layer = N-1`) computes the final LM Head and returns raw text tokens. This exposes raw user prompt text to untrusted remote nodes.

### 2.2 Existing Pipeline Models (`PipelineStage` & `PipelineConfig`)
In `Scheduler/src/scheduler/models/pipeline.py` (and mirrored in `Node/src/node/models/sharding.py`):
```python
class PipelineStage(BaseModel):
    stage_index: int = Field(ge=0)
    total_stages: int = Field(gt=0)
    layer_range: LayerRange
    node_id: str
    model_id: str = ""
```
- Missing metadata distinguishing **Local Client Boundary** stages from **Remote Network Compute** stages.
- `PipelineConfig` validates index continuity ($0 \dots N-1$) but does not enforce local boundary security rules (e.g., that Stage 0 must be local embedding and Stage $M-1$ must be local LM Head when split-inference is enabled).

---

## 3. Proposed Phase 4.6 Architecture & Chain Allocator Specifications

### 3.1 Domain Model Enhancements (`PipelineStage`, `PipelineConfig`, `TensorPayload`)

#### A. Updates to `PipelineStage` (`Scheduler/src/scheduler/models/pipeline.py` and `Node/src/node/models/sharding.py`)
Add explicit flags and stage categorization:
```python
class StageType(str, Enum):
    LOCAL_EMBEDDING = "local_embedding"
    REMOTE_TRANSFORMER = "remote_transformer"
    LOCAL_LM_HEAD = "local_lm_head"
    STANDARD = "standard"

class PipelineStage(BaseModel):
    stage_index: int = Field(ge=0, description="Index of this pipeline stage (0-based)")
    total_stages: int = Field(gt=0, description="Total number of stages in pipeline")
    layer_range: LayerRange = Field(description="Layer range assigned to this stage")
    node_id: str = Field(description="ID of node assigned to run this stage")
    model_id: str = Field(default="", description="Target model identifier")
    is_local_boundary: bool = Field(
        default=False, 
        description="Whether stage executes on local client/edge boundary"
    )
    stage_type: str = Field(
        default="remote_transformer", 
        description="Stage classification: 'local_embedding', 'remote_transformer', 'local_lm_head'"
    )

    @property
    def is_embedding_stage(self) -> bool:
        return self.stage_type == "local_embedding" or (self.is_local_boundary and self.stage_index == 0)

    @property
    def is_lm_head_stage(self) -> bool:
        return self.stage_type == "local_lm_head" or (self.is_local_boundary and self.stage_index == self.total_stages - 1)
```

#### B. Updates to `PipelineConfig`
Add split-inference validator and property checks:
```python
class PipelineConfig(BaseModel):
    task_id: str
    model_id: str
    total_layers: int
    split_inference: bool = Field(default=True, description="Enforce local boundary split-inference")
    client_node_id: str = Field(default="client-local", description="Identifier of client node")
    stages: list[PipelineStage] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_split_inference_boundaries(self) -> Self:
        if not self.split_inference or not self.stages:
            return self

        # 1. First stage MUST be local embedding
        first_stage = self.stages[0]
        if not first_stage.is_local_boundary or first_stage.layer_range.start_layer != 0:
            raise ValueError("Split-inference Stage 0 must be local embedding starting at layer 0")

        # 2. Last stage MUST be local LM head
        last_stage = self.stages[-1]
        if not last_stage.is_local_boundary or last_stage.layer_range.end_layer != self.total_layers - 1:
            raise ValueError(
                f"Split-inference final stage must be local LM Head ending at layer {self.total_layers - 1}"
            )

        # 3. Intermediate stages MUST NOT be assigned layer 0 or final layer, and MUST be marked remote
        for stage in self.stages[1:-1]:
            if stage.is_local_boundary:
                continue  # Allow co-located testing local stages if explicitly configured
            if stage.layer_range.start_layer == 0 or stage.layer_range.end_layer == self.total_layers - 1:
                raise ValueError(
                    f"Remote stage {stage.stage_index} cannot handle boundary layers (0 or {self.total_layers - 1})"
                )
        return self
```

---

### 3.2 Chain Allocator Refactoring in `SchedulingEngine.schedule_pipeline()`

When `task.get("split_inference", True)` is set (default behavior):

```
       [ Client Local Boundary ]              [ Remote Cluster Nodes ]             [ Client Local Boundary ]
┌──────────────────────────────────────┐  ┌──────────────────────────────┐  ┌──────────────────────────────────────┐
│ Stage 0: Local Embedding             │  │ Stage 1..M: Transformer      │  │ Stage M+1: Local LM Head             │
│ LayerRange(0, 0)                     │  │ LayerRange(1, total_layers-2)│  │ LayerRange(total_layers-1, total-1)  │
│ Node ID: client_node_id              │─►│ Distributed Remote Nodes     │─►│ Node ID: client_node_id              │
│ Input: Prompt Text / Token IDs       │  │ Input: Activation Float Tensors│ │ Input: Final Activation Tensor       │
│ Output: Hidden Activation Vector H_0 │  │ Output: Hidden Vector H_M    │  │ Output: Generated Text Tokens        │
└──────────────────────────────────────┘  └──────────────────────────────┘  └──────────────────────────────────────┘
```

#### Algorithm Steps:
1. **Identify Local Client Node**: Extract `client_node_id = task.get("client_node_id", "client-local")`.
2. **Allocate Local Stage 0 (Embedding)**:
   - `LayerRange(start_layer=0, end_layer=0)`
   - `node_id = client_node_id`
   - `is_local_boundary = True`
   - `stage_type = "local_embedding"`
3. **Partition Intermediate Layers ($1 \dots N-2$) Across Remote Nodes**:
   - Intermediate layers to allocate: `intermediate_total = total_layers - 2`.
   - Retrieve live remote compute nodes from `registry.list()`.
   - Calculate node VRAM capacities for intermediate layers.
   - Allocate contiguous layer ranges starting from layer 1 to layer $N-2$ across eligible remote nodes.
4. **Allocate Local Stage $M+1$ (LM Head)**:
   - `LayerRange(start_layer=total_layers-1, end_layer=total_layers-1)`
   - `node_id = client_node_id`
   - `is_local_boundary = True`
   - `stage_type = "local_lm_head"`
5. **Local Boundary Security Verification**:
   - Assert `stages[0].node_id == client_node_id` and `stages[-1].node_id == client_node_id`.
   - Assert for all $1 \le k \le M$: `stages[k].is_local_boundary == False` $\implies$ `1 <= stages[k].layer_range.start_layer` and `stages[k].layer_range.end_layer <= total_layers - 2`.
6. **Generate Hash & Return**:
   - Compute SHA-256 transaction hash with `split_verified` prefix:
     `tx_raw = f"split_pipeline:{task_id}:{total_stages}:{stage_nodes}:split_verified"`

---

## 4. Test Suite Mapping & Specification

### 4.1 Existing Test Suite Mapping

#### `Scheduler/tests` (15 existing files):
- `test_pipeline_scheduler.py` — Currently tests standard pipeline scheduling (1 to N nodes). Needs enhancement / extension for split-inference chain allocation.
- `test_openai_gateway.py` — Tests REST API translation to scheduler task submission.
- `test_ingress_gateway.py` — Tests JWT auth and rate-limiting on ingress.
- `test_scheduler_engine.py` — Tests single-node task matchmaking.
- `test_consensus.py`, `test_registry/test_node_registry.py`, `test_transport.py`, `test_zenoh_integration.py`.

#### `Node/tests` (18 existing files):
- `test_sharding.py` — Tests `LayerRange`, `PipelineStage`, `TensorPayload`.
- `test_end_to_end_pipeline.py` — End-to-end task execution integration test.
- `test_transport.py` — SharedMemory IPC and BackpressuredStreamRouter.
- `test_inference_backends.py`, `test_ollama_client.py`, `test_runtime.py`, `test_zenoh_client.py`.
- `test_m2_adversarial.py` — System stability & error injection test.

---

### 4.2 Required New Test Suites & Test Cases

To achieve closed-loop verification for Phase 4.6, the following unit, integration, and security test files must be created / extended:

```
Scheduler/tests/
├── test_split_inference_scheduler.py     [NEW - Unit & Integration for Split Chain Allocator]
└── (updates to test_pipeline_scheduler.py)

Node/tests/
├── test_split_inference_node.py          [NEW - Unit tests for Node Split Backend & Payload]
├── test_zero_prompt_leakage_security.py  [NEW - Security tests for Prompt Privacy & Packet Audit]
└── test_end_to_end_split_inference.py    [NEW - Integration test for Full Split-Inference Loop]
```

#### Detailed Test Specifications:

#### 1. Unit Tests (`Scheduler/tests/test_split_inference_scheduler.py`)
- **`test_schedule_pipeline_split_inference_basic()`**:
  - Input: 32-layer task, 1 remote node.
  - Expected Output: 3 stages.
    - Stage 0: `node_id="client-local"`, `layer_range=[0, 0]`, `is_local_boundary=True`, `stage_type="local_embedding"`.
    - Stage 1: `node_id="remote-1"`, `layer_range=[1, 30]`, `is_local_boundary=False`, `stage_type="remote_transformer"`.
    - Stage 2: `node_id="client-local"`, `layer_range=[31, 31]`, `is_local_boundary=True`, `stage_type="local_lm_head"`.
- **`test_schedule_pipeline_split_inference_multi_remote_nodes()`**:
  - Input: 32-layer task, 2 remote nodes (each with 16GB VRAM).
  - Expected Output: 4 stages (Stage 0: Local Embedding, Stage 1: Remote 1 [1..15], Stage 2: Remote 2 [16..30], Stage 3: Local LM Head).
- **`test_split_inference_boundary_verification_failure()`**:
  - Manually construct invalid stage list assigning Layer 0 to a remote node. Verify `PipelineConfig` validation raises `ValueError`.
- **`test_split_inference_insufficient_remote_vram()`**:
  - Verify `ValueError` is raised when remote nodes cannot host layers 1..30.

#### 2. Unit Tests (`Node/tests/test_split_inference_node.py`)
- **`test_tensor_payload_activation_vector_validation()`**:
  - Verify `TensorPayload` accepts float arrays / binary buffers with dimensions `[batch_size, seq_len, hidden_dim]` and `dtype="float32"`.
  - Verify validation fails if `data` is a raw text string or integer token list when `stage_type="remote_transformer"`.
- **`test_node_split_backend_execution()`**:
  - Mock `InferenceBackend.execute_pipeline_stage()`. Pass activation payload; verify it produces output activation payload without loading tokenizers or embedding matrices.

#### 3. Security Verification Tests (`Node/tests/test_zero_prompt_leakage_security.py`)
- **`test_zero_prompt_leakage_in_network_traffic()`**:
  - Mock Zenoh transport recorder. Run a split-inference request with prompt `"CLASSIFIED_SECRET_PROMPT_12345"`.
  - Audit all serialized frames sent to remote nodes (`public-intelligence/net/tasks/<task_id>/tensors/*`).
  - Assert string `"CLASSIFIED_SECRET_PROMPT_12345"` and exact token IDs DO NOT appear anywhere in the binary or JSON payloads transmitted over WAN.
- **`test_remote_node_memory_inspection_isolation()`**:
  - Inspect remote node's task queue, state, and logs after split-inference task execution.
  - Verify remote node retains only floating-point activation vectors, with zero access to vocabulary lookup tables or raw prompt text.
- **`test_activation_payload_tamper_rejection()`**:
  - Inject corrupted / malformed activation tensor payload into remote node receiver.
  - Verify node gracefully drops packet, logs security warning, and refrains from leaking memory state.

#### 4. End-to-End Integration Test (`Node/tests/test_end_to_end_split_inference.py`)
- **`test_end_to_end_split_inference_pipeline()`**:
  1. Instantiate `NodeRegistry`, `SchedulingEngine`, and mock local client boundary engine.
  2. Register 2 remote worker nodes running mock activation backends.
  3. Client submits prompt `"Public Intelligence Split Inference Integration Test"`.
  4. Client embeds prompt locally $\rightarrow$ generates activation tensor $H_0$.
  5. $H_0$ is streamed over Zenoh to Remote Stage 1, which outputs $H_1$, streamed to Remote Stage 2, which outputs $H_2$.
  6. $H_2$ is streamed back to Client Local LM Head, which decodes text tokens.
  7. Verify end-to-end output matches expected text, zero prompt leakage occurred on intermediate remote nodes, and backpressure flow control succeeded.

---

## 5. Summary Matrix & Implementation Roadmap

| Subsystem | File | Action Required |
|---|---|---|
| **Scheduler Domain** | `Scheduler/src/scheduler/models/pipeline.py` | Add `is_local_boundary`, `stage_type`, `StageType` enum to `PipelineStage`. Add `split_inference`, `client_node_id`, and `validate_split_inference_boundaries` to `PipelineConfig`. |
| **Scheduler Engine** | `Scheduler/src/scheduler/core/engine.py` | Update `schedule_pipeline()` to automatically allocate local Stage 0 (Embedding) and local Stage M+1 (LM Head), partitioning intermediate layers 1..N-2 across remote nodes. |
| **Node Domain** | `Node/src/node/models/sharding.py` | Synchronize `PipelineStage`, `LayerRange`, `TensorPayload` domain models with Scheduler updates. |
| **Scheduler Tests** | `Scheduler/tests/test_split_inference_scheduler.py` | Create new unit/integration tests for split-inference chain allocation and boundary validation. |
| **Node Tests** | `Node/tests/test_split_inference_node.py` | Create new unit tests for tensor payload validation and split backend execution. |
| **Security Tests** | `Node/tests/test_zero_prompt_leakage_security.py` | Create new security suite auditing network packets and remote memory for zero prompt leakage. |
| **E2E Tests** | `Node/tests/test_end_to_end_split_inference.py` | Create E2E integration test verifying complete client-remote-client split-inference execution loop. |

---
*End of Architectural Analysis.*
