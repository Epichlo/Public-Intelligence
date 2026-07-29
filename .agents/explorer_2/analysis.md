# Comprehensive Technical Analysis: Intermediate Vector Activation Transport (Phase 4.6)

## Executive Summary

Phase 4.6 introduces **Asymmetric Split-Inference & Local Boundary Security** for Public Intelligence. Under this architecture, raw prompt tokens, text strings, token IDs, token embedding weights (Layer 0), and final language model projection weights (LM Head / Unembedding) remain strictly local on the user's client or edge gateway. Remote untrusted P2P nodes only execute intermediate transformer layers (Layers 1 to $N-1$) by consuming and producing high-dimensional intermediate activation vectors ($H \in \mathbb{R}^{B \times S \times D}$).

This report provides an in-depth architectural investigation of:
1. `TensorPayload` domain models in `Node/src/node/models/sharding.py` and `Scheduler/src/scheduler/models/pipeline.py`.
2. `BackpressuredStreamRouter` and `BackpressuredReceiver` transport systems in `Node/src/node/core/transport.py` and `Scheduler/src/scheduler/core/transport.py`.
3. High-dimensional vector activation serialization, deserialization, zero-copy shared memory IPC, and Zenoh P2P backpressured WAN streaming.
4. Concrete recommendations and code extension specifications for the implementation phase.

---

## 1. Baseline Codebase Inspection & Observations

### 1.1 Existing Model Definitions

#### `Node/src/node/models/sharding.py`
In `Node/src/node/models/sharding.py` (lines 60-76):
```python
class TensorPayload(BaseModel):
    """Payload representing serialized tensor activation data across stages."""

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

#### `Scheduler/src/scheduler/models/pipeline.py`
Currently defines `LayerRange`, `PipelineStage`, and `PipelineConfig`, but does not yet export `TensorPayload`. For architectural consistency and client/scheduler verification, `TensorPayload` should be symmetrically available or shared between `Scheduler` and `Node`.

### 1.2 Existing Transport Layer Subsystem

#### `Node/src/node/core/transport.py` & `Scheduler/src/scheduler/core/transport.py`
1. **Shared Memory IPC (`SharedMemoryIPC`)**:
   - `write_data(data: bytes) -> str`: Writes length-prefixed binary buffer into `multiprocessing.shared_memory.SharedMemory` with handle format `pi_shm_<uuid_12>`.
   - `read_data(name: str) -> bytes`: Reads length-prefixed bytes from shared memory.
   - `cleanup(name: str) -> None`: Closes and unlinks shared memory block.
2. **Backpressured Stream Router (`BackpressuredStreamRouter`)**:
   - Sliding window flow control initialized with `window_size` (default: 4).
   - Subscribes to ACK channel: `public-intelligence/net/transport/ack/{session_id}`.
   - Publishes to stream topic: `public-intelligence/net/transport/stream/{session_id}`.
   - Topic helpers (lines 209-232 of `Node/src/node/core/transport.py`):
     - `get_tensor_topic(task_id, stage_index)` $\rightarrow$ `public-intelligence/net/tasks/{task_id}/tensors/{stage_index}`
     - `get_tensor_ack_topic(task_id, stage_index)` $\rightarrow$ `public-intelligence/net/tasks/{task_id}/tensors/{stage_index}/ack`
3. **Backpressured Receiver (`BackpressuredReceiver`)**:
   - Subscribes to stream topic, executes `on_chunk` callback.
   - Automatically detects `shm://` prefixes, resolves shared memory contents, performs cleanup, and returns binary payload.
   - Transmits capacity signal back to sender: `{"seq": self.processed_count}`.

---

## 2. Gap Analysis & Rationale for Extensions

| Feature Dimension | Current Baseline | Phase 4.6 Requirement | Deficit & Architectural Remedy |
|---|---|---|---|
| **Split-Inference Flag** | Not present | Explicit flag signaling local boundary isolation mode | Add `is_split_inference: bool = True` to `TensorPayload` |
| **Pipeline Target Stage** | `stage_index` (sender) only | Explicit `target_stage_index: int` | Add `target_stage_index: int` to prevent cross-stage routing errors |
| **Tensor Type Categorization** | Generic payload | Distinct classification of activation vs embedding vs LM head input | Add `tensor_type: str = "intermediate_activation"` |
| **Sequence Step Tracking** | None | Multi-step / autoregressive generation step index | Add `sequence_id: int = 0` to preserve causal ordering |
| **Binary Payload Framing** | Untyped `bytes` or `list[float]` | Framed header + binary C-contiguous buffer | Implement binary framing protocol (`to_framed_bytes` / `from_framed_bytes`) |
| **NumPy/PyTorch Integration** | Manual list/bytes conversion | Native `to_numpy()` and `from_numpy()` helpers | Add zero-copy array mapping helpers |
| **Typed Transport API** | Generic chunk streaming (`send_chunk`) | High-level `send_tensor_payload()` and `start_tensor_listener()` | Extend `BackpressuredStreamRouter` & `BackpressuredReceiver` |

---

## 3. High-Dimensional Activation Vector Serialization Analysis

### 3.1 Data Volume & Bandwidth Benchmark

Consider an intermediate hidden state matrix $H$ produced by Layer 0 (Embedding) for a Llama-3 8B model ($D = 4096$, sequence length $S = 128$, batch size $B = 1$):
- Shape: $[1, 128, 4096]$
- Element Count: $1 \times 128 \times 4096 = 524,288$ float elements

| Format | Byte Overhead per Element | Total Payload Size | Transport Latency over 100 Mbps WAN | Evaluation & Recommendation |
|---|---|---|---|---|
| **JSON float list** (`[0.012, ...]`) | $\approx 20\text{–}30\text{ bytes}$ | $\approx 10.5\text{ MB}\text{–}15.7\text{ MB}$ | $\approx 840\text{ ms}\text{–}1250\text{ ms}$ | **Unacceptable**: Extreme serialization bloat & CPU overhead. |
| **Base64 encoded bytes** | $\approx 5.33\text{ bytes}$ | $\approx 2.8\text{ MB}$ | $\approx 224\text{ ms}$ | **Suboptimal**: 33% inflation over raw bytes. |
| **Raw Binary FP32** (`float32`) | $4.00\text{ bytes}$ | $2,097,152\text{ bytes} \approx 2.0\text{ MB}$ | $\approx 160\text{ ms}$ | **Standard**: Exact precision, zero conversion loss. |
| **Raw Binary FP16 / BF16** (`float16` / `bfloat16`) | $2.00\text{ bytes}$ | $1,048,576\text{ bytes} \approx 1.0\text{ MB}$ | $\approx 80\text{ ms}$ | **Recommended for WAN**: 50% bandwidth reduction. |
| **FP8 (E4M3FN format)** | $1.00\text{ byte}$ | $524,288\text{ bytes} \approx 512\text{ KB}$ | $\approx 40\text{ ms}$ | **Optimal for WAN**: 75% bandwidth reduction. |
| **Local Shared Memory** (`SharedMemoryIPC`) | 20 bytes handle | 20 bytes (`shm://pi_shm_...`) | $<0.1\text{ ms}$ | **Mandatory for Co-Located Nodes**: Complete zero WAN overhead! |

### 3.2 Binary Framing Layout Protocol

To avoid JSON parsing overhead while remaining self-describing, framed payloads transmitted over Zenoh follow a 2-part layout:

```
+-----------------------------------+-----------------------------------+-----------------------------------+
| Field                             | Type / Length                     | Description                       |
+-----------------------------------+-----------------------------------+-----------------------------------+
| Magic Header                      | 4 bytes (ASCII "PITP")            | Protocol Identification ("Public  |
|                                   |                                   | Intelligence Tensor Payload")     |
| Metadata Length (N)               | 4 bytes (Big-Endian uint32)       | Byte length of JSON header        |
| JSON Metadata Header              | N bytes (UTF-8 JSON string)       | Pydantic metadata (task_id, shape,|
|                                   |                                   | dtype, is_split_inference, etc.)  |
| Binary Activation Buffer          | Remaining bytes                   | Contiguous float raw byte array   |
+-----------------------------------+-----------------------------------+-----------------------------------+
```

#### Python Framing Implementation Logic:
```python
MAGIC_BYTES = b"PITP"

def to_framed_bytes(self) -> bytes:
    # 1. Prepare metadata dict (excluding raw heavy data bytes)
    meta = {
        "task_id": self.task_id,
        "stage_index": self.stage_index,
        "target_stage_index": self.target_stage_index,
        "is_split_inference": self.is_split_inference,
        "tensor_type": self.tensor_type,
        "shape": self.shape,
        "dtype": self.dtype,
        "sequence_id": self.sequence_id,
    }
    meta_bytes = json.dumps(meta).encode("utf-8")
    meta_len = len(meta_bytes)
    
    # 2. Extract raw activation bytes
    if isinstance(self.data, bytes):
        raw_data = self.data
    else:
        # Convert list or array to bytes
        raw_data = np.array(self.data, dtype=self.dtype).tobytes()
        
    # 3. Assemble binary frame
    return MAGIC_BYTES + meta_len.to_bytes(4, "big") + meta_bytes + raw_data
```

---

## 4. End-to-End Split-Inference Sequence & Topic Architecture

### 4.1 Topic Hierarchy for Pipeline Stages

For a pipeline consisting of Stage 0 (Client Local), Stage 1 (Remote Node A), and Stage 2 (Client Local LM Head):

```
                       STAGE 0 (Client Local)
               [Layer 0: Embedding Token Projection]
                                 |
                                 | TensorPayload (H_0) over Zenoh Topic:
                                 | "public-intelligence/net/tasks/{task_id}/tensors/1"
                                 v
                       STAGE 1 (Remote Node A)
              [Layers 1..N-1: Hidden Transformer Blocks]
                                 |
                                 | TensorPayload (H_1) over Zenoh Topic:
                                 | "public-intelligence/net/tasks/{task_id}/tensors/2"
                                 v
                       STAGE 2 (Client Local)
               [LM Head: Unembedding / Token Projection]
```

Backpressure Flow Control ACKs flow in reverse:
- Stage 1 publishes ACK to `public-intelligence/net/tasks/{task_id}/tensors/0/ack` (received by Stage 0 router).
- Stage 2 publishes ACK to `public-intelligence/net/tasks/{task_id}/tensors/1/ack` (received by Stage 1 router).

### 4.2 Detailed Message Flow Diagram

```
Client (Stage 0)             Remote Node A (Stage 1)              Client (Stage 0)
   [Local Layer 0]                [Layers 1..N-1]                     [Local LM Head]
         |                               |                                   |
  1. Compute H_0 = Embed(X)              |                                   |
         |                               |                                   |
  2. Send TensorPayload(H_0)             |                                   |
     Topic: .../tensors/1 -------------->|                                   |
         |                         3. Process H_1 = Stage1(H_0)              |
  4. Send ACK (seq=1)                    |                                   |
     Topic: .../tensors/0/ack <----------|                                   |
         |                               |                                   |
         |                        5. Send TensorPayload(H_1)                 |
         |                           Topic: .../tensors/2 ------------------>|
         |                               |                            6. Process Logits = LM_Head(H_1)
         |                               |                               Sample Token Y
         |                               |                            7. Send ACK (seq=1)
         |                               |<-------------------------- Topic: .../tensors/1/ack
```

---

## 5. Architectural Recommendations & Detailed Code Extensions

### 5.1 Recommendation 1: Extend `TensorPayload` in `Node/src/node/models/sharding.py` & `Scheduler/src/scheduler/models/pipeline.py`

Update `TensorPayload` to support split-inference flags, target stage indexing, tensor type classification, sequence ID, and binary framing helpers:

```python
class TensorPayload(BaseModel):
    """Payload representing serialized tensor activation data across stages."""

    task_id: str = Field(description="Unique pipeline execution task ID")
    stage_index: int = Field(ge=0, description="Stage index sending the payload")
    target_stage_index: int = Field(
        default=0, description="Target stage index receiving the payload"
    )
    is_split_inference: bool = Field(
        default=False,
        description="Flag indicating asymmetric split-inference mode (Layer 0 & LM Head local)",
    )
    tensor_type: str = Field(
        default="intermediate_activation",
        description="Type of tensor ('intermediate_activation', 'embedding', 'lm_head_input')",
    )
    data: bytes | list[float] | dict[str, Any] = Field(
        description="Tensor activation data or payload content"
    )
    shape: list[int] = Field(
        default_factory=list, description="Dimensions of the tensor shape"
    )
    dtype: str = Field(default="float32", description="Data type ('float32', 'float16', 'bfloat16', 'fp8')")
    sequence_id: int = Field(default=0, description="Sequence step or micro-batch index")
    shm_name: str | None = Field(
        default=None,
        description="Optional shared memory block name for co-located IPC",
    )

    def to_framed_bytes(self) -> bytes:
        """Serialize TensorPayload metadata and activation bytes into binary frame."""
        meta = {
            "task_id": self.task_id,
            "stage_index": self.stage_index,
            "target_stage_index": self.target_stage_index,
            "is_split_inference": self.is_split_inference,
            "tensor_type": self.tensor_type,
            "shape": self.shape,
            "dtype": self.dtype,
            "sequence_id": self.sequence_id,
            "shm_name": self.shm_name,
        }
        meta_bytes = json.dumps(meta).encode("utf-8")
        raw_bytes: bytes
        if isinstance(self.data, bytes):
            raw_bytes = self.data
        elif isinstance(self.data, list):
            import numpy as np
            raw_bytes = np.array(self.data, dtype=np.dtype(self.dtype)).tobytes()
        else:
            raw_bytes = json.dumps(self.data).encode("utf-8")

        return b"PITP" + len(meta_bytes).to_bytes(4, "big") + meta_bytes + raw_bytes

    @classmethod
    def from_framed_bytes(cls, raw: bytes) -> "TensorPayload":
        """Deserialize a binary frame into a TensorPayload instance."""
        if not raw.startswith(b"PITP"):
            raise ValueError("Invalid TensorPayload binary header magic string")
        meta_len = int.from_bytes(raw[4:8], "big")
        meta_bytes = raw[8 : 8 + meta_len]
        meta = json.loads(meta_bytes.decode("utf-8"))
        data_bytes = raw[8 + meta_len :]

        return cls(
            task_id=meta["task_id"],
            stage_index=meta["stage_index"],
            target_stage_index=meta.get("target_stage_index", 0),
            is_split_inference=meta.get("is_split_inference", False),
            tensor_type=meta.get("tensor_type", "intermediate_activation"),
            data=data_bytes,
            shape=meta.get("shape", []),
            dtype=meta.get("dtype", "float32"),
            sequence_id=meta.get("sequence_id", 0),
            shm_name=meta.get("shm_name"),
        )
```

### 5.2 Recommendation 2: Extend `BackpressuredStreamRouter` in `Node/src/node/core/transport.py`

Add high-level method `send_tensor_payload`:

```python
async def send_tensor_payload(
    self,
    payload: TensorPayload,
    is_local: bool = False,
) -> bytes:
    """Stream a TensorPayload across pipeline stages with sliding window flow control.

    Args:
        payload: TensorPayload object containing activations and metadata.
        is_local: Whether the target stage runs co-located on the local machine.

    Returns:
        The transmitted byte payload (either shm token or framed binary payload).
    """
    raw_frame = payload.to_framed_bytes()
    target_topic = get_tensor_topic(payload.task_id, payload.target_stage_index)

    # Temporary override or declare publisher for target topic
    pub = self.zenoh_session.declare_publisher(target_topic)
    try:
        def _pub(data: bytes) -> None:
            pub.put(data)

        return await self.send_chunk(raw_frame, publish_func=_pub, is_local=is_local)
    finally:
        if hasattr(pub, "undeclare"):
            pub.undeclare()
```

### 5.3 Recommendation 3: Extend `BackpressuredReceiver` in `Node/src/node/core/transport.py` & `Scheduler/src/scheduler/core/transport.py`

Add high-level method `start_tensor_listener`:

```python
def start_tensor_listener(
    self,
    task_id: str,
    stage_index: int,
    on_payload: Callable[[TensorPayload], Any],
) -> None:
    """Subscribe to stage tensor channel and process incoming activation payloads.

    Args:
        task_id: Pipeline task ID.
        stage_index: Local stage index to listen on.
        on_payload: Callback invoked with deserialized TensorPayload.
    """
    self.stream_topic = get_tensor_topic(task_id, stage_index)
    self.ack_topic = get_tensor_ack_topic(task_id, stage_index)
    self._loop = asyncio.get_running_loop()

    def _on_sample(sample: zenoh.Sample) -> None:
        raw_bytes: bytes
        try:
            payload_str = sample.payload.to_string()
        except AttributeError:
            payload_str = sample.payload.decode("utf-8", errors="ignore")

        if payload_str.startswith("shm://"):
            shm_name = payload_str[6:]
            try:
                raw_bytes = SharedMemoryIPC.read_data(shm_name)
            finally:
                SharedMemoryIPC.cleanup(shm_name)
        else:
            if isinstance(sample.payload, bytes):
                raw_bytes = sample.payload
            else:
                raw_bytes = payload_str.encode("utf-8")

        tensor_payload = TensorPayload.from_framed_bytes(raw_bytes)
        res = on_payload(tensor_payload)

        if asyncio.iscoroutine(res) and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: asyncio.create_task(res))

        self.send_ack()

    self.subscriber = self.zenoh_session.declare_subscriber(self.stream_topic, _on_sample)
```

---

## 6. Security Invariants & Zero Prompt Leakage Guarantees

1. **Local Boundary Invariant**:
   - The user's input string $X$ is tokenized into IDs $T = [t_1, t_2, \dots, t_S]$ strictly inside the local boundary process.
   - Local Embedding Layer produces hidden vector $H_0 = \text{Embedding}(T) \in \mathbb{R}^{B \times S \times D}$.
   - Neither $X$ nor $T$ is ever transmitted across network channels or stored in `TensorPayload`.
2. **Intermediate Activation Irreversibility**:
   - High-dimensional intermediate activations $H_k$ ($D = 4096$) represent abstract vector spaces. Without the corresponding vocabulary embedding projection matrix $W_{\text{embed}} \in \mathbb{R}^{V \times D}$ or LM Head matrix $W_{\text{lm\_head}} \in \mathbb{R}^{V \times D}$ (where $V \approx 128,000$), external nodes cannot invert $H_k$ back to discrete tokens or text.
3. **Payload Integrity Guard**:
   - `TensorPayload` frames can include SHA-256 activation checksums (`activation_hash`) to verify that activations were not altered in transit across untrusted P2P links.

---

## 7. Next Steps for Implementation

1. Update `TensorPayload` in `Node/src/node/models/sharding.py` and `Scheduler/src/scheduler/models/pipeline.py`.
2. Add binary framing methods (`to_framed_bytes` and `from_framed_bytes`) to `TensorPayload`.
3. Update `BackpressuredStreamRouter` and `BackpressuredReceiver` with `send_tensor_payload` and `start_tensor_listener`.
4. Add comprehensive unit tests in `Node/tests/test_sharding.py`, `Node/tests/test_transport.py`, and `Scheduler/tests/test_transport.py`.
