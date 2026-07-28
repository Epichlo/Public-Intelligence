## 2026-07-26T18:23:44Z

You are Worker 1 implementing Milestone M1 (Scheduler OpenAI REST Gateway & Telemetry Endpoints).
Your working directory is: /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/m1_worker

Context & Instructions:
- Read /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/ORIGINAL_REQUEST.md.
- Read /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/PROJECT.md.
- Read /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_survey_2/survey_report.md.

Implementation Scope (Scheduler Sub-repository: /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Scheduler):
1. Create `Scheduler/src/scheduler/models/openai.py`:
   - Define Pydantic models for OpenAI specification: `ChatMessage`, `ChatCompletionRequest`, `CompletionUsage`, `ChatCompletionResponseChoice`, `ChatCompletionResponse`, `ChatCompletionChunkDelta`, `ChatCompletionChunkChoice`, `ChatCompletionChunk`, `ModelObject`, `ModelListResponse`.
2. Create `Scheduler/src/scheduler/api/openai.py`:
   - `POST /v1/chat/completions`:
     - Authenticate via `verify_jwt` dependency (RS256 JWT header `Authorization: Bearer <token>`).
     - Enforce rate limiting via `await request.app.state.rate_limiter.acquire(tenant_id)`. If False, raise `HTTPException(429, detail="Rate limit exceeded. Multi-tenant quota exhausted.")`.
     - Convert OpenAI `messages` to prompt string via `messages_to_prompt()`.
     - Select target compute node via `scheduling_engine` / `select_node()`.
     - Propose task allocation to Raft consensus engine if active.
     - For `stream: false`: proxy request to Node `/infer`, parse result, and return standard `ChatCompletionResponse` JSON with choices and token usage.
     - For `stream: true`: proxy streaming request to Node `/infer`, wrap response in FastAPI `StreamingResponse(..., media_type="text/event-stream")` yielding formatted OpenAI SSE chunks (`data: {"id":..., "object":"chat.completion.chunk", ...}\n\n`) terminating with `data: [DONE]\n\n`.
   - `GET /v1/models`: List available models from active nodes in `NodeRegistry`.
   - `GET /v1/models/{model_id}`: Retrieve model details.
3. Create `Scheduler/src/scheduler/api/telemetry.py`:
   - `GET /nodes/{node_id}/telemetry` and `GET /nodes/telemetry`: Expose decrypted hardware metrics from `NodeRegistry._telemetry`.
4. Update `Scheduler/src/scheduler/main.py`:
   - Add `CORSMiddleware` (`allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`).
   - Include `openai_router` and `telemetry_router`.
5. Create comprehensive test suite in `Scheduler/tests/test_openai_gateway.py` (and test telemetry endpoint) covering:
   - Non-streaming completions
   - Streaming SSE completions (checking `chat.completion.chunk` and `[DONE]`)
   - Invalid JWT / unauthorized (401)
   - Rate limit exhaustion (429)
   - `GET /v1/models` and telemetry routes
6. Run verification tools inside `Scheduler/`:
   - `pytest`
   - `ruff check .`
   - `ruff format --check .`
   - `mypy src`
7. Write your execution report and handoff report to /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/m1_worker/handoff.md and report back via send_message to parent.
