# Phase 4.6 Architecture Analysis: Asymmetric Split-Inference & Local Boundary Security

## 1. Executive Summary

Phase 4.6 introduces **Asymmetric Split-Inference & Local Boundary Security** to Public Intelligence. In decentralized AI networks, host compute nodes are untrusted third-party participants. In the existing Phase 4/4.5 architecture, raw text prompts (or token ID sequences) are transmitted in plaintext from the client/gateway to remote host nodes, exposing user prompts, system instructions, and generated completions to remote host operators.

Phase 4.6 decouples the transformer execution chain into:
1. **Local Boundary (Client / Edge Gateway)**: Holds Layer 0 (**Embedding Matrix $E$**) and final Layer $N$ (**LM Head projection matrix $W_{\text{lm}}$** and Token Sampler). Executes token embedding and logit unembedding locally.
2. **Remote Host Network (Layers $1 \dots N-1$)**: Executes intermediate hidden transformer blocks across 1 or more remote host compute nodes in the P2P network. Remote nodes receive ONLY high-dimensional intermediate activation vectors (tensors $H_0 \in \mathbb{R}^{L \times d_{\text{model}}}$).

By strictly retaining Layer 0 and final LM Head on the client/edge gateway, remote host nodes are completely blinded to token lookup dictionaries, vocabulary IDs, and plaintext strings.

---

## 2. Comprehensive Codebase Audit

### 2.1 Prompt & Inference Path in Compute Nodes

#### A. Node Backend Contract (`Node/src/node/backends/base.py`, `ollama.py`, `mock.py`)
- `InferenceBackend` exposes `generate(model, prompt, options)` and `generate_stream(model, prompt, options)` accepting a plaintext string `prompt: str`.
- `execute_pipeline_stage(stage, input_tensors, options)` was added in Phase 4 Step 3, but currently constructs string prompts like `f"Stage {stage.stage_index} [Layers ...]: {input_tensors}"` or passes text strings.
- `OllamaBackend` routes prompts via HTTP POST to Ollama (`/api/generate`) with `{"model": ..., "prompt": prompt}`. Ollama performs tokenization, embedding, layer evaluation, and LM head projection internally within a single monolithic process.

#### B. Node API & Task Runtime (`Node/src/node/api/inference.py`, `Node/src/node/runtime.py`)
- In `inference.py`, `POST /infer` accepts an `InferenceRequest` containing `prompt: str`. It checks `RadixTrieCache` for prefix matches and streams tokens or return responses directly to the requester.
- In `runtime.py`, the background task worker `_worker_loop()` picks up tasks from `task_queue`, extracts `task["prompt"]`, calls `inference_backend.generate()`, writes plaintext output to `LocalDiskArtifactStore`, and publishes artifact metadata via Zenoh.

### 2.2 Gateway & Scheduler Routing (`Scheduler/src/scheduler/api/openai.py`, `ingress.py`, `engine.py`)
- In `openai.py`, `create_chat_completion()` formats user messages into a single prompt string `messages_to_prompt(req_data.messages)`.
- The Scheduler selects a target compute node using `SchedulingEngine.schedule_task()` or direct registry lookup.
- The gateway sends an HTTP POST request containing `{"model": req_data.model, "prompt": prompt_text, "stream": req_data.stream}` straight to the compute node's `http://<node_ip>:<port>/infer` endpoint.

### 2.3 Existing Pipeline Sharding Architecture (`Node/src/node/models/sharding.py`, `Scheduler/src/scheduler/models/pipeline.py`)
- `LayerRange`: Specifies contiguous layer bounds (`start_layer`, `end_layer`, `num_layers`).
- `PipelineStage`: Tracks `stage_index`, `total_stages`, `layer_range`, `node_id`, `model_id`.
- `TensorPayload`: Serializes intermediate data with fields `task_id`, `stage_index`, `data` (`bytes` / `list[float]` / `dict`), `shape`, `dtype`, `shm_name`.
- `SchedulingEngine.schedule_pipeline()` partitions total model layers across available nodes based on VRAM capacity.

### 2.4 Privacy Vulnerabilities Identified
1. **Monolithic Prompt Delivery**: Raw user prompts and token IDs are delivered directly to remote nodes.
2. **Lack of Layer 0 / LM Head Isolation**: Remote nodes possess full vocabulary weights and perform token embedding/unembedding.
3. **No Intermediate Tensor Pipeline Mode**: `InferenceBackend` lacks a dedicated, high-performance tensor activation forward pass method that processes raw float tensor buffers without string conversion.

---

## 3. Asymmetric Split-Inference Architecture

### 3.1 Mathematical Execution Pipeline

```
[ Local Client / Edge Gateway ]
   │
   ├── 1. Prompt String: P = "System: ... User: Hello"
   ├── 2. Tokenization: T = [t_1, t_2, ..., t_L]
   ├── 3. Layer 0 Embedding (Local): H_0 = Embed(T) ∈ R^(L × d_model)
   │
   ▼  (Stream TensorPayload over Zenoh P2P: H_0 activations ONLY)
[ Remote Host Node Stage 1..K-1 ]
   │
   ├── 4. Forward Pass (Layers 1..N-1): H_(N-1) = TransformerBlocks_{1..N-1}(H_0)
   │      * Remote node has NO embedding matrix E
   │      * Remote node has NO LM head matrix W_lm
   │      * Remote node receives ONLY float32/fp16 activation vectors
   │
   ▼  (Stream TensorPayload over Zenoh P2P: H_(N-1) activations ONLY)
[ Local Client / Edge Gateway ]
   │
   ├── 5. Layer N LM Head (Local): Logits = RMSNorm(H_(N-1)) · W_lm^T ∈ R^(1 × V)
   ├── 6. Sampling (Local): t_next ~ Softmax(Logits / τ)
   ├── 7. Detokenization: Chunk = Decode(t_next)
   └── 8. Autoregressive Loop: Append t_next, Embed(t_next), send to Remote Node
```

### 3.2 Security Properties & Privacy Invariants

| Property | Monolithic Architecture | Phase 4.6 Asymmetric Split-Inference |
| :--- | :--- | :--- |
| **Prompt Text Visibility on Remote Node** | Plaintext String (`"User: secret..."`) | **Zero Visibility** (Never sent) |
| **Token ID Visibility on Remote Node** | Plaintext Array (`[101, 2054, ...]`) | **Zero Visibility** (Never sent) |
| **Embedding Matrix $E$ Location** | Remote Host Node | **Local Client / Edge Gateway Only** |
| **LM Head Projection $W_{\text{lm}}$ Location** | Remote Host Node | **Local Client / Edge Gateway Only** |
| **Payload Transmitted to Remote Node** | JSON String / Prompt Text | **Continuous Tensor Activations ($H_0 \in \mathbb{R}^{L \times d_{\text{model}}}$)** |
| **Payload Returned from Remote Node** | Text Tokens / Completion String | **Continuous Tensor Activations ($H_{N-1} \in \mathbb{R}^{1 \times d_{\text{model}}}$)** |

---

## 4. Technical Specifications & Architectural Recommendations

### 4.1 Domain Model Extensions

#### A. Node Sharding Models (`Node/src/node/models/sharding.py`) & Scheduler Models (`Scheduler/src/scheduler/models/pipeline.py`)

Add stage classification flags and split-inference fields:

```python
from enum import Enum
from pydantic import BaseModel, Field

class StageType(str, Enum):
    CLIENT_EMBEDDING = "client_embedding"  # Stage 0: Local Layer 0
    REMOTE_HIDDEN = "remote_hidden"        # Stages 1..K-1: Layers 1..N-1
    CLIENT_LM_HEAD = "client_lm_head"      # Stage K: Local Layer N

class PipelineStage(BaseModel):
    stage_index: int = Field(ge=0, description="Index of this pipeline stage (0-based)")
    total_stages: int = Field(gt=0, description="Total number of stages in pipeline")
    layer_range: LayerRange = Field(description="Layer range assigned to this stage")
    node_id: str = Field(description="ID of node assigned to run this stage")
    model_id: str = Field(default="", description="Target model identifier")
    is_local_boundary: bool = Field(
        default=False,
        description="Whether this stage runs locally on client/edge gateway"
    )
    stage_type: StageType = Field(
        default=StageType.REMOTE_HIDDEN,
        description="Type of processing performed in this stage"
    )

class TensorPayload(BaseModel):
    task_id: str = Field(description="Unique pipeline execution task ID")
    stage_index: int = Field(ge=0, description="Stage index sending the payload")
    data: bytes | list[float] | dict[str, Any] = Field(
        description="Tensor activation data or payload content"
    )
    shape: list[int] = Field(
        default_factory=list, description="Dimensions of the tensor shape [batch, seq, d_model]"
    )
    dtype: str = Field(default="float32", description="Data type of tensor values")
    shm_name: str | None = Field(
        default=None,
        description="Optional shared memory block name for co-located IPC"
    )
    is_split_inference: bool = Field(
        default=True,
        description="Flag indicating asymmetric split-inference activation vector transport"
    )
    tensor_type: str = Field(
        default="activation",
        description="Type of tensor: activation, logit_input, or gradient"
    )
```

### 4.2 Local Boundary Isolation Engine (`LocalBoundaryEngine`)

Create a dedicated local boundary isolation engine module: `Node/src/node/core/local_boundary.py` (and helper in Scheduler for gateway local boundary execution):

```python
class LocalBoundaryEngine:
    """Executes Layer 0 (Embedding) and Layer N (LM Head / Unembedding) locally on client/gateway."""

    def __init__(self, model_id: str, vocab_size: int = 32000, hidden_dim: int = 4096) -> None:
        self.model_id = model_id
        self.vocab_size = vocab_size
        self.hidden_dim = hidden_dim
        # Lightweight local token embedding matrix & LM head projection weights
        self._init_local_weights()

    def embed_prompt(self, prompt: str) -> TensorPayload:
        """Tokenize text prompt and project into Layer 0 hidden activation vectors H_0.
        
        Guarantees that raw prompt tokens/IDs remain inside local memory.
        """
        token_ids = self._tokenize(prompt)
        # Compute H_0 = Embed(token_ids)
        h0_vectors = self._compute_embeddings(token_ids)
        return TensorPayload(
            task_id="",
            stage_index=0,
            data=h0_vectors,
            shape=[1, len(token_ids), self.hidden_dim],
            dtype="float32",
            is_split_inference=True,
            tensor_type="activation",
        )

    def unembed_logits(self, activation_payload: TensorPayload, temperature: float = 1.0) -> tuple[int, str]:
        """Apply final Layer N LM Head projection & sampling locally.
        
        Returns next token ID and decoded token text string.
        """
        h_last = activation_payload.data
        logits = self._compute_lm_head(h_last)
        token_id = self._sample_logits(logits, temperature=temperature)
        token_text = self._decode_token(token_id)
        return token_id, token_text
```

### 4.3 Inference Backend Interface Extensions (`InferenceBackend`)

Update `Node/src/node/backends/base.py`, `mock.py`, and `ollama.py`:

```python
class InferenceBackend(ABC):
    ...
    @abstractmethod
    async def execute_split_stage(
        self,
        stage: PipelineStage,
        input_payload: TensorPayload,
        options: dict[str, Any] | None = None,
    ) -> TensorPayload:
        """Execute intermediate transformer layers (1..N-1) on activation tensor payloads.
        
        Args:
            stage: PipelineStage assigned to this remote host node.
            input_payload: Incoming TensorPayload containing activation vectors.
            options: Execution control arguments.
            
        Returns:
            TensorPayload containing output activation vectors for next stage.
        """
        pass
```

In `EchoBackend` (`mock.py`):
```python
async def execute_split_stage(
    self,
    stage: PipelineStage,
    input_payload: TensorPayload,
    options: dict[str, Any] | None = None,
) -> TensorPayload:
    """Transform activation vectors deterministically across intermediate layers."""
    # Simulates transformer block matrix multiplication on floating point activations
    if isinstance(input_payload.data, list):
        transformed_data = [x + 0.01 * (stage.stage_index + 1) for x in input_payload.data]
    elif isinstance(input_payload.data, bytes):
        transformed_data = input_payload.data  # Preserve binary tensor bytes
    else:
        transformed_data = input_payload.data

    return TensorPayload(
        task_id=input_payload.task_id,
        stage_index=stage.stage_index,
        data=transformed_data,
        shape=input_payload.shape,
        dtype=input_payload.dtype,
        is_split_inference=True,
        tensor_type="activation",
    )
```

### 4.4 Matchmaker & Chain Allocation Engine (`SchedulingEngine.schedule_split_inference_pipeline`)

Update `Scheduler/src/scheduler/core/engine.py` to add `schedule_split_inference_pipeline`:

1. **Stage 0 (Client Local Boundary)**:
   - `stage_index = 0`
   - `layer_range = LayerRange(start_layer=0, end_layer=0)`
   - `node_id = "client_local"`
   - `is_local_boundary = True`
   - `stage_type = StageType.CLIENT_EMBEDDING`

2. **Stages $1 \dots K-1$ (Remote Compute Nodes)**:
   - Layers $1 \dots N-1$ partitioned across eligible cluster nodes according to VRAM availability.
   - `node_id = <remote_node_id>`
   - `is_local_boundary = False`
   - `stage_type = StageType.REMOTE_HIDDEN`

3. **Stage $K$ (Client Local Boundary)**:
   - `stage_index = K`
   - `layer_range = LayerRange(start_layer=N, end_layer=N)`
   - `node_id = "client_local"`
   - `is_local_boundary = True`
   - `stage_type = StageType.CLIENT_LM_HEAD`

4. **Validation**:
   - Verify that Stage 0 and Stage $K$ are strictly marked `is_local_boundary = True`.
   - Verify that remote stages ($1 \dots K-1$) handle ONLY layers $1 \dots N-1$.

### 4.5 Gateway Integration (`Scheduler/src/scheduler/api/openai.py`)

In `POST /v1/chat/completions`:
- Add split-inference execution path when requested or configured.
- When `split_inference=True`:
  1. Initialize `LocalBoundaryEngine` locally at gateway/client.
  2. Call `schedule_split_inference_pipeline(task)` to partition layers.
  3. Generate $H_0$ locally via `local_boundary.embed_prompt(prompt_text)`.
  4. Transmit $H_0$ to remote stage $1$ over Zenoh via `BackpressuredStreamRouter`.
  5. Remote nodes process layers $1 \dots N-1$ and return $H_{N-1}$ activation payload over Zenoh.
  6. Apply local LM Head via `local_boundary.unembed_logits(H_{N-1})`.
  7. Stream OpenAI-compliant SSE token chunks (`chat.completion.chunk`) to requester.

---

## 5. Security & Verification Plan

### 5.1 Privacy & Leakage Proof

To prove zero prompt leakage:
1. **Payload Inspection Guard**: Intercept all Zenoh messages and network frames sent to remote host nodes during execution.
2. **Assertion Check**:
   - `assert "prompt" not in payload_json`
   - `assert "messages" not in payload_json`
   - `assert not isinstance(payload.data, str)`
   - `assert all(isinstance(val, float) for val in payload.data)` (for list data) or raw float byte tensor.
3. **Information Theory Property**: High-dimensional vector $H_0 \in \mathbb{R}^{d_{\text{model}}}$ without the embedding dictionary matrix $E$ cannot be mapped back to token text without solving an under-determined continuous-to-discrete inverse problem.

### 5.2 Test Strategy & Matrix

| Test Suite | File | Verified Condition |
| :--- | :--- | :--- |
| **Split Sharding Models** | `Node/tests/test_sharding.py` | Validates `StageType`, `is_local_boundary`, and `TensorPayload.is_split_inference`. |
| **Local Boundary Isolation** | `Node/tests/test_local_boundary.py` | Verifies embedding $H_0$ generation and LM Head unembedding locally without external calls. |
| **Backend Split Stage Exec** | `Node/tests/test_inference_backends.py` | Verifies `execute_split_stage` processes activation tensors cleanly in `EchoBackend`. |
| **Split Pipeline Matchmaker** | `Scheduler/tests/test_pipeline_scheduler.py` | Verifies `schedule_split_inference_pipeline` assigns Stage 0 (Layer 0) and Stage K (Layer N) to local boundary and remote nodes to Layers 1..N-1. |
| **Zero Prompt Leakage Audit** | `Node/tests/test_split_inference_security.py` | Adversarial test intercepting remote payloads and verifying 0 text/token ID leakage. |
| **End-to-End Split Pipeline** | `Node/tests/test_end_to_end_pipeline.py` | Full integration test executing split inference end-to-end and producing valid tokens. |

---

## 6. Execution Roadmap for Sub-Agents

1. **ARCHITECT**:
   - Audit system spec & finalize model schemas (`StageType`, `PipelineStage`, `TensorPayload`).
   - Define exact API interfaces for `LocalBoundaryEngine` and `schedule_split_inference_pipeline`.

2. **CODER**:
   - Implement `LocalBoundaryEngine` in `Node/src/node/core/local_boundary.py` (and gateway helper).
   - Extend `InferenceBackend.execute_split_stage()` in `base.py`, `mock.py`, and `ollama.py`.
   - Implement `schedule_split_inference_pipeline()` in `SchedulingEngine` (`Scheduler/src/scheduler/core/engine.py`).
   - Wire split-inference route into `Scheduler/src/scheduler/api/openai.py`.

3. **AUDITOR**:
   - Perform security audit on network payload streams to ensure zero text strings or integer token IDs are exposed to remote nodes.
   - Audit memory leaks in tensor array allocations.

4. **VERIFIER**:
   - Execute PyTest suites (`pytest`).
   - Enforce 100% `ruff check .`, `ruff format --check .`, and strict `mypy Scheduler/src Node/src`.
