# Handoff Report — Intermediate Vector Activation Transport (Phase 4.6)

**Agent**: `explorer_2`  
**Working Directory**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_2`  
**Milestone**: Phase 4.6 Asymmetric Split-Inference & Local Boundary Security  
**Parent Orchestrator**: `f83b81f8-1121-41d6-bf2f-86acffbfb380`

---

## 1. Observation

Direct code observations from the codebase investigation:

1. **Current `TensorPayload` Definition**:
   - Location: `Node/src/node/models/sharding.py` (lines 60-76)
   - Code snippet:
     ```python
     class TensorPayload(BaseModel):
         task_id: str = Field(description="Unique pipeline execution task ID")
         stage_index: int = Field(ge=0, description="Stage index sending the payload")
         data: bytes | list[float] | dict[str, Any] = Field(
             description="Tensor activation data or payload content"
         )
         shape: list[int] = Field(
             default_factory=list, description="Dimensions of the tensor shape"
         )
         dtype: str = Field(default="float32", description="Data type of tensor values")
         shm_name: str | None = Field(
             default=None,
             description="Optional shared memory block name for co-located IPC",
         )
     ```
   - Observations: Lacks `is_split_inference: bool` flag, `target_stage_index: int`, `tensor_type: str`, `sequence_id: int`, and binary framing methods.

2. **Current Transport Implementation**:
   - Locations:
     - `Node/src/node/core/transport.py` (lines 71-233)
     - `Scheduler/src/scheduler/core/transport.py` (lines 72-149)
   - Code snippets:
     - `BackpressuredStreamRouter.send_chunk(chunk, publish_func, is_local)` sends generic `bytes` or `shm://` handle over Zenoh sliding window flow control channel (`public-intelligence/net/transport/stream/{session_id}`).
     - `BackpressuredReceiver.start(on_chunk)` subscribes to `stream/{session_id}`, cleans up shared memory if `shm://` token is received, invokes `on_chunk(data)`, and emits ACK to `public-intelligence/net/transport/ack/{session_id}`.
     - `get_tensor_topic(task_id, stage_index)` yields `public-intelligence/net/tasks/{task_id}/tensors/{stage_index}`.
     - `get_tensor_ack_topic(task_id, stage_index)` yields `public-intelligence/net/tasks/{task_id}/tensors/{stage_index}/ack`.

3. **Activation Serialization Overhead**:
   - For batch size 1, sequence length 128, hidden dim 4096 ($[1, 128, 4096]$ float matrix = 524,288 float elements):
     - JSON list of floats: $\approx 10.5\text{–}15.7\text{ MB}$ per forward pass (severe network congestion & CPU parsing overhead).
     - Raw float32 bytes: $2.0\text{ MB}$.
     - Raw float16 / bfloat16 bytes: $1.0\text{ MB}$ (50% reduction).
     - FP8 (E4M3FN): $512\text{ KB}$ (75% reduction).
     - Shared Memory (`SharedMemoryIPC`): 20-byte token `shm://pi_shm_...` ($<0.1\text{ ms}$ latency for local co-located processes).

---

## 2. Logic Chain

1. **Premise 1**: Phase 4.6 requires retaining Layer 0 (Embedding) and LM Head on the client/edge node, streaming only intermediate activation vectors (Layers 1..N-1) to external P2P compute nodes.
2. **Premise 2**: To distinguish split-inference activation passes from standard pipeline or complete task requests, transport payloads must carry an explicit `is_split_inference: bool` flag and target stage classification (`target_stage_index`, `tensor_type`).
3. **Premise 3**: Transporting high-dimensional float matrices ($[1, 128, 4096]$) via JSON lists causes 5x-10x payload expansion ($>10\text{ MB}$ per chunk), rendering real-time inference over P2P WAN infeasible.
4. **Premise 4**: A binary framing format (`PITP` magic header + 4-byte JSON metadata length + JSON header + raw activation bytes) achieves exact 1:1 memory efficiency ($1.0-2.0\text{ MB}$) while preserving full Pydantic schema validation.
5. **Premise 5**: For co-located local nodes, `SharedMemoryIPC` allows passing activations via zero-copy `/dev/shm` blocks, reducing WAN transmission cost to zero.
6. **Conclusion**: Extending `TensorPayload` with split-inference metadata and binary framing, coupled with high-level `send_tensor_payload` and `start_tensor_listener` methods in `BackpressuredStreamRouter` and `BackpressuredReceiver`, provides a secure, efficient, and robust foundation for Phase 4.6.

---

## 3. Caveats

1. **GPU-Direct CUDA IPC**: This design currently transfers host-RAM byte arrays or CPU shared memory blocks. Future GPU-direct RDMA / CUDA IPC extensions can be layered on top using `shm_name` handles or dedicated CUDA IPC handles.
2. **Float8 (FP8) Quantization Support**: While FP8 serialization layouts are specified in `TensorPayload.dtype="fp8"`, PyTorch/NumPy native FP8 support varies depending on Python/CUDA environment versions. Fallback to `float16` or `bfloat16` is recommended when FP8 C-extensions are missing.
3. **Model Heterogeneity**: The activation dimension ($D = 4096$) is model-specific. The `shape` field in `TensorPayload` dynamically specifies dimensions to ensure multi-model compatibility (e.g. 8B vs 70B models).

---

## 4. Conclusion

1. **`TensorPayload` Model Extension**:
   - Extend `TensorPayload` in `Node/src/node/models/sharding.py` and `Scheduler/src/scheduler/models/pipeline.py` with:
     - `target_stage_index: int = 0`
     - `is_split_inference: bool = False`
     - `tensor_type: str = "intermediate_activation"`
     - `sequence_id: int = 0`
     - `to_framed_bytes() -> bytes`
     - `from_framed_bytes(raw: bytes) -> TensorPayload`
2. **Transport Subsystem Extension**:
   - Extend `BackpressuredStreamRouter` in `Node/src/node/core/transport.py` with `send_tensor_payload(payload, is_local)`.
   - Extend `BackpressuredReceiver` in `Node/src/node/core/transport.py` and `Scheduler/src/scheduler/core/transport.py` with `start_tensor_listener(task_id, stage_index, on_payload)`.
3. **Zero Prompt Leakage Guarantee**:
   - Raw tokens and embedding weights remain on Stage 0 (Client Local). Remote compute nodes receive only framed intermediate activation vectors over Zenoh topics `public-intelligence/net/tasks/{task_id}/tensors/{stage_index}`.

---

## 5. Verification Method

To verify these architectural extensions during and after implementation:

1. **Unit Test Verification**:
   - Run Node model tests:
     ```bash
     pytest Node/tests/test_sharding.py -v
     ```
   - Run Node transport tests:
     ```bash
     pytest Node/tests/test_transport.py -v
     ```
   - Run Scheduler transport tests:
     ```bash
     pytest Scheduler/tests/test_transport.py -v
     ```

2. **Code Quality & Static Typing Verification**:
   - Run Ruff linter and formatter checks:
     ```bash
     ruff check .
     ruff format --check .
     ```
   - Run MyPy static type checking:
     ```bash
     mypy Scheduler/src Node/src
     ```

3. **Invalidation Conditions**:
   - Verification fails if high-dimensional activations sent as `list[float]` cause JSON serialization errors or memory limits to be exceeded.
   - Verification fails if `is_split_inference` flag is missing or omitted from `TensorPayload` binary frame metadata.
   - Verification fails if receiver fails to deserialize shared memory `shm://` tokens back into valid `TensorPayload` instances.
