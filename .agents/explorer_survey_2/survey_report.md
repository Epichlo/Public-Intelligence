# Phase 4.5 Explorer Survey Report: OpenAI REST Gateway & Scheduler Control Plane Integration

**Author**: Explorer 2 (`explorer_survey_2`)  
**Target Architecture**: `Scheduler/src/scheduler/`  
**Date**: 2026-07-26  
**Status**: Comprehensive Survey Completed  

---

## 1. Executive Summary

This survey provides a detailed architectural audit of the `Scheduler` sub-repository (`Scheduler/src/scheduler/`) for implementing Phase 4.5 of Public Intelligence: **OpenAI-Compatible REST API Gateway (`POST /v1/chat/completions`) & Web Control Plane Backend Integration**.

The existing Scheduler provides robust components for task ingress (`api/ingress.py`), rate-limiting (`core/rate_limiter.py`), multi-scheduler consensus (`core/consensus.py`), two-stage capability match-making & scheduling engines (`core/engine.py`, `scheduler/algorithm.py`), node registry (`registry/node_registry.py`), and Zenoh WAN networking/transport (`core/zenoh_router.py`, `core/transport.py`).

To achieve 100% compliance with OpenAI's REST API specification (used by standard client SDKs and the Requester Web UI `/playground`), the Scheduler must expose `/v1/chat/completions` and `/v1/models` endpoints. This report details the precise request translation pipeline, authentication mechanism, rate-limiting integration, response formatting (non-streaming JSON and streaming Server-Sent Events SSE), missing models/helpers, and FastAPI routing adjustments required.

---

## 2. Detail Analysis of Existing Scheduler Architecture

### 2.1 Task Ingress Gateway (`Scheduler/src/scheduler/api/ingress.py`)
- **Primary Endpoint**: `POST /api/v1/tasks/submit` (lines 77–158)
- **Input Model**: `TaskSubmission` (lines 27–35) with `task_id: str`, `action: str`, `data: dict[str, Any]`.
- **Authentication**: `verify_jwt` dependency (lines 37–74) validates `Authorization: Bearer <RS256_JWT>` against `app.state.jwt_public_key` (or `JWT_PUBLIC_KEY` environment variable / fallback PEM). Requires `tenant_id` claim in token payload.
- **Rate-Limiting**: Calls `request.app.state.rate_limiter.acquire(tenant_id)`. If `False`, raises `HTTPException(429, detail="Rate limit exceeded. Multi-tenant quota exhausted.")`.
- **Scheduling Execution**: Packages requirements (`model_name`, `min_vram_gb`, `backend_type`) and invokes `scheduling_engine.schedule_task(task_data)`. Returns `(tx_hash, node_id)`.
- **Consensus Log Commitment**: If `consensus_engine` is active, proposes `"allocate_task"` event to the Raft consensus log before returning.

### 2.2 Token-Bucket Rate Limiter (`Scheduler/src/scheduler/core/rate_limiter.py`)
- **Class**: `TokenBucketLimiter` (lines 7–50)
- **Invariants**: Default `capacity = 5` (burst capacity) and `refill_rate = 0.5` tokens/sec (1 token per 2 seconds).
- **Thread/Async Safety**: Protected by `asyncio.Lock()`.
- **Tenant Isolation**: Tracks per-`tenant_id` bucket capacities (`self.buckets[tenant_id]`) and timestamps (`self.last_updated[tenant_id]`).
- **Acquire Logic**: `await rate_limiter.acquire(tenant_id)` returns `True` if bucket has $\ge 1.0$ tokens, refilling based on elapsed time ($now - last\_updated$).

### 2.3 Raft Consensus Engine (`Scheduler/src/scheduler/core/consensus.py`)
- **Class**: `RaftConsensusEngine` (lines 17–511)
- **Transport**: Communicates over Zenoh channels (`public-intelligence/net/consensus/*`).
- **Propose Logic**: `await consensus_engine.propose(action, data)` appends entry to leader log or forwards to leader, waiting for majority quorum commitment.

### 2.4 Scheduling Engines (`Scheduler/src/scheduler/core/engine.py` & `algorithm.py`)
- **`SchedulingEngine` (`core/engine.py`)**:
  - `schedule_task(task)`: Runs 2-stage match-making (`CapabilityMatchmaker` filtering + scoring by current load), updates queue depth in `_telemetry[node_id]`, returns `(tx_hash, node_id)`.
  - `schedule_pipeline(task)`: Shards model layer ranges across multiple compute nodes based on available VRAM.
- **`Scheduler` (`scheduler/algorithm.py`)**:
  - `select_node(model_name)`: Deterministic node selection scoring nodes by queue length (40%), GPU utilization (30%), CPU utilization (10%), VRAM ratio (20%), and dampener penalties.

### 2.5 Lifespan & Application Setup (`Scheduler/src/scheduler/main.py`)
- Configures lifespan context manager (lines 26–60).
- Instantiates `NodeRegistry`, `TokenBucketLimiter`, `CapabilityMatchmaker`, `SchedulingEngine`, and `ZenohRouter` on `app.state`.
- Currently includes routers: `health_router`, `nodes_router`, `heartbeat_router`, `schedule_router`, `ingress_router` (lines 79–83).

---

## 3. OpenAI REST Gateway (`POST /v1/chat/completions`) Technical Specification

### 3.1 Request Schema (`ChatCompletionRequest`)
Standard OpenAI payload format:
```json
{
  "model": "llama3",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Explain quantum computing in simple terms."}
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 512
}
```

### 3.2 Translation to Task Ingress Pipeline
When `POST /v1/chat/completions` receives a request:
1. **JWT Verification**: Pass request through `verify_jwt` dependency (`Authorization: Bearer <JWT>`). Extract `tenant_id`.
2. **Rate Limiting Guard**: Call `await rate_limiter.acquire(tenant_id)`. If `False`, return HTTP 429.
3. **Message Translation to Prompt**:
   Convert OpenAI message history into a flattened LLM prompt string:
   ```python
   def messages_to_prompt(messages: list[dict[str, str]]) -> str:
       parts = []
       for msg in messages:
           role = msg.get("role", "user")
           content = msg.get("content", "")
           if role == "system":
               parts.append(f"System: {content}")
           elif role == "user":
               parts.append(f"User: {content}")
           elif role == "assistant":
               parts.append(f"Assistant: {content}")
       parts.append("Assistant:")
       return "\n\n".join(parts)
   ```
4. **Node Selection & Consensus Proposal**:
   - Create internal task structure:
     `task_id = f"task_{uuid.uuid4().hex[:12]}"`
     `task_data = {"task_id": task_id, "requirements": {"model_name": req.model}}`
   - Select target node via `scheduling_engine.schedule_task(task_data)` (or `scheduler.select_node(req.model)`).
   - If `consensus_engine` is active, propose `"allocate_task"` event to Raft consensus ledger.

### 3.3 Node Execution & Response Formatting

#### A. Non-Streaming Response (`stream: false`)
- Issue HTTP POST request to selected Node: `http://{node.ip_address}:{settings.node_api_port}/infer` with `InferenceRequest(model=req.model, prompt=prompt, stream=False)`.
- Receive Node `InferenceResponse(model=..., response="Generated text...")`.
- Wrap into standard OpenAI `ChatCompletionResponse`:
```json
{
  "id": "chatcmpl-a1b2c3d4e5f6",
  "object": "chat.completion",
  "created": 1722000000,
  "model": "llama3",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Generated text..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 24,
    "completion_tokens": 12,
    "total_tokens": 36
  }
}
```

#### B. Streaming Response (`stream: true`)
- Issue HTTP POST (or Zenoh stream receiver) to Node `/infer` with `stream=True`.
- Node yields line-by-line SSE chunks (e.g. `data: {"model": "llama3", "response": "token", "done": false}`).
- Wrap stream output into a FastAPI `StreamingResponse(stream_generator(), media_type="text/event-stream")`.
- Format chunks as `chat.completion.chunk`:
  1. **Initial Role Chunk**:
     `data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1722000000,"model":"llama3","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n`
  2. **Content Delta Chunks**:
     `data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1722000000,"model":"llama3","choices":[{"index":0,"delta":{"content":"token"},"finish_reason":null}]}\n\n`
  3. **Final Stop Chunk**:
     `data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1722000000,"model":"llama3","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n`
  4. **Terminal Signal**:
     `data: [DONE]\n\n`

---

## 4. Identification of Missing FastAPI Endpoints & Helper Functions

### 4.1 Missing FastAPI Endpoints
To achieve full OpenAI REST API compatibility:
1. `POST /v1/chat/completions`: Main chat completion gateway endpoint (supports streaming & non-streaming).
2. `GET /v1/models`: Returns list of available models across all active nodes in `NodeRegistry`.
3. `GET /v1/models/{model_id}`: Returns model metadata object for a specific model ID.

### 4.2 Missing Pydantic Data Models
The following models should be defined (e.g., in `Scheduler/src/scheduler/models/openai.py` or `api/openai.py`):
- `ChatMessage`: `role: str`, `content: str`, `name: str | None = None`
- `ChatCompletionRequest`: `model: str`, `messages: list[ChatMessage]`, `stream: bool = False`, `temperature: float | None = 1.0`, `max_tokens: int | None = None`
- `CompletionUsage`: `prompt_tokens: int`, `completion_tokens: int`, `total_tokens: int`
- `ChatCompletionResponseChoice`: `index: int`, `message: ChatMessage`, `finish_reason: str = "stop"`
- `ChatCompletionResponse`: `id: str`, `object: str = "chat.completion"`, `created: int`, `model: str`, `choices: list[ChatCompletionResponseChoice]`, `usage: CompletionUsage`
- `ChatCompletionChunkDelta`: `role: str | None = None`, `content: str | None = None`
- `ChatCompletionChunkChoice`: `index: int`, `delta: ChatCompletionChunkDelta`, `finish_reason: str | None = None`
- `ChatCompletionChunk`: `id: str`, `object: str = "chat.completion.chunk"`, `created: int`, `model: str`, `choices: list[ChatCompletionChunkChoice]`
- `ModelObject`: `id: str`, `object: str = "model"`, `created: int`, `owned_by: str = "public-intelligence"`
- `ModelListResponse`: `object: str = "list"`, `data: list[ModelObject]`

### 4.3 Missing Helper Functions
1. `messages_to_prompt(messages: list[ChatMessage]) -> str`: Formats conversation history into standard LLM prompt string.
2. `estimate_tokens(text: str) -> int`: Simple character heuristic (`len(text) // 4`) for usage metadata.
3. `format_sse_chunk(chunk_data: dict[str, Any]) -> str`: Formats dictionary into `data: <json>\n\n`.
4. `get_aggregate_models(registry: NodeRegistry) -> list[str]`: Collects deduplicated list of available models from all live nodes in `NodeRegistry`.

### 4.4 Missing Middleware & CORS Configuration
- In `Scheduler/src/scheduler/main.py`:
  Add `CORSMiddleware` with `allow_origins=["*"]` (or configured origins), `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`. This is essential so the Requester Playground in `website/` (running on Vite dev server `http://localhost:5173`) can call `/v1/chat/completions` without browser CORS errors.

---

## 5. Verification Plan

1. **Unit Testing**:
   - `Scheduler/tests/api/test_openai.py`:
     - Test `POST /v1/chat/completions` with non-streaming payload (`stream: false`).
     - Test `POST /v1/chat/completions` with streaming payload (`stream: true`, checking SSE chunks and `data: [DONE]`).
     - Test JWT authentication failure (401).
     - Test rate limit exhaustion (429).
     - Test `GET /v1/models` model list aggregation.
2. **System Verification**:
   - Run `pytest`, `ruff check .`, `ruff format --check .`, and `mypy src` in `Scheduler/` to guarantee zero regressions and 100% type safety.

---

## 6. Summary Matrix

| Metric / Component | Status in Existing Codebase | Action Required for Phase 4.5 |
|---|---|---|
| JWT Auth (`RS256`) | Implemented in `api/ingress.py` (`verify_jwt`) | Reuse `verify_jwt` dependency for `/v1/chat/completions` |
| Multi-tenant Rate Limiting | Implemented in `core/rate_limiter.py` (`TokenBucketLimiter`) | Call `rate_limiter.acquire(tenant_id)` in `/v1/chat/completions` |
| Node Matchmaking | Implemented in `core/engine.py` & `algorithm.py` | Call `scheduling_engine` / `select_node` for model routing |
| Raft Consensus Proposal | Implemented in `core/consensus.py` | Propose `allocate_task` on request submission |
| `POST /v1/chat/completions` | **Missing** | Implement in new `scheduler/api/openai.py` module |
| `GET /v1/models` | **Missing** | Implement model discovery endpoint in `scheduler/api/openai.py` |
| SSE Streaming Handler | Partially in Node, not exposed as OpenAI SSE | Implement SSE chunk translator in `scheduler/api/openai.py` |
| CORS Middleware | **Missing** in `main.py` | Add `CORSMiddleware` in `main.py` for web UI compatibility |
