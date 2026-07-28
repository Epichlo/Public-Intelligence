# Comprehensive Technical Analysis: R3 OpenAI-Compatible REST Gateway Router (`POST /v1/chat/completions`)

**Author:** `explorer_1` (teamwork_preview_explorer)  
**Target Subsystem:** Scheduler Service (`/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Scheduler`)  
**Date:** 2026-07-29  

---

## Executive Summary

This document provides a thorough technical analysis of the OpenAI-compatible REST API Gateway router within the Public Intelligence Scheduler service. It details how standard OpenAI request payloads (`POST /v1/chat/completions`) are authenticated, rate-limited, scheduled via `SchedulingEngine`, committed to the Raft consensus log (`RaftConsensusEngine`), proxied to node compute backends (`/infer`), and formatted into OpenAI-compliant JSON responses or Server-Sent Event (SSE) streams (`text/event-stream`).

---

## 1. Existing Ingress Infrastructure Audit

### 1.1 Ingress Endpoint & Pipeline Architecture
The standard task submission ingress gateway is implemented in `Scheduler/src/scheduler/api/ingress.py`:

- **Endpoint:** `POST /api/v1/tasks/submit`
- **Request Schema (`TaskSubmission`):**
  - `task_id: str`: Unique identifier for the task.
  - `action: str`: Instruction / state machine action payload.
  - `data: dict[str, Any]`: Task arguments (e.g., `model_name`, `min_vram_gb`, `backend_type`).

### 1.2 Authentication Mechanism (`verify_jwt`)
Implemented as a FastAPI `Depends` dependency in `Scheduler/src/scheduler/api/ingress.py` (lines 37–74):
- Decodes bearer tokens supplied in the `Authorization: Bearer <token>` header.
- Uses RS256 asymmetric signature verification against `request.app.state.jwt_public_key` or environment variable `JWT_PUBLIC_KEY` (with a hardcoded fallback RSA public key).
- Verifies the presence of the `tenant_id` claim in the decoded payload.
- **Failure modes:**
  - Header not starting with `"Bearer "`: Returns HTTP `401 Unauthorized` (`"Invalid Authorization header format. Must be Bearer <JWT>."`).
  - PyJWT decoding / signature error: Returns HTTP `401 Unauthorized` (`"JWT signature verification failed: <error>"`).
  - Missing `tenant_id` claim: Returns HTTP `401 Unauthorized` (`"Invalid claims: Missing 'tenant_id' in token payload."`).

### 1.3 Multi-Tenant Token-Bucket Rate Limiter
Implemented in `Scheduler/src/scheduler/core/rate_limiter.py`:
- `TokenBucketLimiter` enforces dynamic per-`tenant_id` rate limits.
- **Parameters:** Default `capacity = 5` (burst threshold) and `refill_rate = 0.5` tokens/sec (1 token per 2.0s).
- **Operation:**
  ```python
  allowed = await rate_limiter.acquire(tenant_id)
  ```
  If `allowed` is `False`, raises HTTP `429 Too Many Requests` (`"Rate limit exceeded. Multi-tenant quota exhausted."`).

### 1.4 Two-Stage Scheduling Engine & Consensus Log
Implemented in `Scheduler/src/scheduler/core/engine.py` and `Scheduler/src/scheduler/core/consensus.py`:
- **Stage 1 (Filtering):** `CapabilityMatchmaker.filter_nodes()` filters live nodes by required model (`model_name`), minimum VRAM, and pulse staleness ($\Delta t \le 15.0$s).
- **Stage 2 (Scoring):** `CapabilityMatchmaker.score_nodes()` ranks eligible nodes using fitness score:
  $$\text{Score} = (\text{Reliability} \times 100.0) - (\text{QueueDepth} \times 15.0) - (\text{CPUUtilization} \times 0.5)$$
- **Telemetry update:** Increments `queue_depth` for the selected node in `NodeRegistry._telemetry`.
- **Transaction Hash:** Generates `tx_hash = sha256(f"{node_id}:{task_id}:{score}")`.
- **Consensus Replication:** When `RaftConsensusEngine` is active, proposes `"allocate_task"` action containing `{task_id, node_id, tx_hash, action, data}` over Zenoh channel `public-intelligence/net/consensus/*` and waits for majority quorum consensus commitment before proceeding.

---

## 2. Payload Translation Architecture (`POST /v1/chat/completions`)

### 2.1 Schema Definition
The request model `ChatCompletionRequest` is defined in `Scheduler/src/scheduler/models/openai.py`:

```python
class ChatMessage(BaseModel):
    role: str
    content: str
    name: str | None = None

class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = 1.0
    max_tokens: int | None = None
```

### 2.2 Translation & Dispatch Logic
When a request arrives at `POST /v1/chat/completions` (`Scheduler/src/scheduler/api/openai.py`):

1. **Task ID Generation:**  
   `task_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"`
2. **Prompt Assembly (`messages_to_prompt`):**  
   Concatenates list of `ChatMessage` objects into unified LLM prompt format:
   ```text
   System: <system_prompt>

   User: <user_prompt>

   Assistant:
   ```
3. **Task Requirement Mapping:**  
   Packs `req_data.model` into `task_data`:
   ```python
   task_data = {
       "task_id": task_id,
       "requirements": {"model_name": req_data.model},
   }
   ```
4. **Target Node Scheduling:**  
   Invokes `scheduling_engine.schedule_task(task_data)` to execute Stage 1/Stage 2 selection, returning `(tx_hash, target_node_id)`. If no nodes are available, falls back to direct `NodeRegistry` scan or raises HTTP `503 Service Unavailable`.
5. **Consensus Proposal:**  
   Proposes log entry to Raft consensus engine:
   ```python
   await consensus_engine.propose(
       "allocate_task",
       {
           "task_id": task_id,
           "node_id": target_node_id,
           "tx_hash": tx_hash or task_id,
           "action": "chat_completion",
           "data": {"model": req_data.model, "stream": req_data.stream},
       },
   )
   ```
6. **Backend Routing Payload:**  
   Constructs `/infer` HTTP payload for node execution:
   ```python
   infer_payload = {
       "model": req_data.model,
       "prompt": prompt_text,
       "stream": req_data.stream,
   }
   ```

---

## 3. Auth & Rate Limiting Enforcement for Gateway Router

Both JWT authentication and token-bucket rate limiting are strictly enforced on `POST /v1/chat/completions`:

```python
@router.post("/v1/chat/completions")
async def create_chat_completion(
    request: Request,
    req_data: ChatCompletionRequest,
    jwt_claims: Annotated[dict[str, Any], Depends(verify_jwt)],
) -> ChatCompletionResponse | StreamingResponse:
    tenant_id = jwt_claims.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid claims: Missing 'tenant_id' in token payload.",
        )

    rate_limiter = getattr(request.app.state, "rate_limiter", None)
    if rate_limiter is not None:
        allowed = await rate_limiter.acquire(tenant_id)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Multi-tenant quota exhausted.",
            )
```

---

## 4. Response Formatting Specifications

### 4.1 Non-Streaming Response (`stream: false`)

**HTTP Proxy Flow:**
- Sends async POST request to `http://{node_ip}:{node_port}/infer`.
- Parses JSON output: `{"model": "...", "response": "<generated_text>"}`.
- Estimates token usage using standard character count heuristic: $\text{tokens} = \max(1, \text{len}(\text{text}) // 4)$.

**Output Object Structure (`ChatCompletionResponse`):**
```json
{
  "id": "chatcmpl-a1b2c3d4e5f6",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "llama3",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Generated text response..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 25,
    "total_tokens": 37
  }
}
```

### 4.2 SSE Streaming Response (`stream: true`)

**HTTP Proxy Flow:**
- Returns `fastapi.responses.StreamingResponse(sse_generator(), media_type="text/event-stream")`.
- `sse_generator()` produces Server-Sent Events with framing `data: <JSON>\n\n`.

**Chunk Sequence:**
1. **Initial Role Chunk:**
   ```text
   data: {"id":"chatcmpl-a1b2c3d4e5f6","object":"chat.completion.chunk","created":1700000000,"model":"llama3","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

   ```
2. **Token Delta Chunks:**
   ```text
   data: {"id":"chatcmpl-a1b2c3d4e5f6","object":"chat.completion.chunk","created":1700000000,"model":"llama3","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

   data: {"id":"chatcmpl-a1b2c3d4e5f6","object":"chat.completion.chunk","created":1700000000,"model":"llama3","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":null}]}

   ```
3. **Final Termination Chunk & Stop Signal:**
   ```text
   data: {"id":"chatcmpl-a1b2c3d4e5f6","object":"chat.completion.chunk","created":1700000000,"model":"llama3","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

   data: [DONE]

   ```

---

## 5. Endpoints, Error Codes, and Test Strategies

### 5.1 Endpoint Matrix

| Method | Endpoint | Description | Auth Required | Rate Limited |
|---|---|---|---|---|
| `POST` | `/v1/chat/completions` | Create OpenAI chat completion (streaming / non-streaming) | Yes (RS256 JWT) | Yes (`TokenBucketLimiter`) |
| `GET` | `/v1/models` | List all available models across registered nodes | No | No |
| `GET` | `/v1/models/{model_id}` | Retrieve details for a specific model | No | No |
| `POST` | `/api/v1/tasks/submit` | Low-level task submission gateway | Yes (RS256 JWT) | Yes (`TokenBucketLimiter`) |

### 5.2 HTTP Error Code Mapping

| Status Code | Reason / Condition | Error Response Detail |
|---|---|---|
| `401 Unauthorized` | Missing / malformed `Authorization` header, invalid RS256 JWT signature, or missing `tenant_id` | `"Invalid Authorization header format."` / `"JWT signature verification failed."` / `"Missing 'tenant_id'"` |
| `429 Too Many Requests` | Tenant token bucket exhausted (burst > 5 requests without refill) | `"Rate limit exceeded. Multi-tenant quota exhausted."` |
| `422 Unprocessable Entity` | Pydantic validation failure (e.g. missing `model` or `messages` field) | FastAPI standard validation error detail |
| `404 Not Found` | Requested `model_id` not found in active nodes via `GET /v1/models/{model_id}` | `"Model '<model_id>' not found among active nodes."` |
| `502 Bad Gateway` | Compute node unreachable or refused connection during `/infer` POST | `"Failed to communicate with compute node: <error>"` |
| `503 Service Unavailable` | No live compute node satisfies requirements for specified model | `"No suitable compute node available for model '<model>'"` |
| `500 Internal Server Error` | Scheduler internal failure or Raft consensus proposal exception | `"Consensus log commitment failed: <error>"` |

### 5.3 Automated Verification Strategy
Verification is performed via `tests/test_openai_gateway.py`:

1. **Authentication Tests:** Generate valid and invalid RS256 JWTs using RSA key pair fixtures. Assert 200 on valid token, 401 on expired/signature-tampered tokens, and 401/422 on missing headers.
2. **Rate Limiting Tests:** Fire 5 consecutive requests to consume bucket capacity, verify HTTP 200. Fire 6th request and assert HTTP 429 response.
3. **Non-Streaming Integration Test:** Mock `httpx.AsyncClient.post` return payload. Assert HTTP 200, schema compliance of `ChatCompletionResponse`, correct choice indexing, and non-zero token usage stats.
4. **Streaming SSE Test:** Mock `httpx.AsyncClient.stream` returning an async line generator. Assert HTTP 200, `text/event-stream` media type, initial role delta chunk, token content chunks, final stop chunk, and `data: [DONE]`.
5. **Model Registry Tests:** Query `GET /v1/models` and `GET /v1/models/{model_id}`, verifying valid model discovery and 404 behavior for unknown models.
6. **Code Quality Standards:** Run `pytest`, `ruff check .`, `ruff format --check .`, and `mypy src` to guarantee 100% test pass rate and zero static typing errors.
