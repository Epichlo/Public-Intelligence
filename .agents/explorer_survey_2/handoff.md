# Handoff Report — Explorer 2: OpenAI REST Gateway & Scheduler Control Plane Survey

**Agent Folder**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_survey_2`  
**Handoff Type**: Hard Handoff  
**Date**: 2026-07-26  

---

## 1. Observation

1. **`Scheduler/src/scheduler/api/ingress.py`**:
   - Lines 37–74: `verify_jwt` dependency decodes `Authorization: Bearer <JWT>` using RS256 algorithm via `app.state.jwt_public_key` or `JWT_PUBLIC_KEY` environment variable / fallback key, requiring the `tenant_id` claim in the payload.
   - Lines 77–158: `submit_task` endpoint handles `POST /api/v1/tasks/submit`, acquires tokens from `app.state.rate_limiter`, schedules tasks via `scheduling_engine.schedule_task()`, and proposes task allocation events to `consensus_engine`.
2. **`Scheduler/src/scheduler/core/rate_limiter.py`**:
   - Lines 7–50: `TokenBucketLimiter` enforces multi-tenant rate limiting with burst capacity = 5 and refill rate = 0.5 tokens/sec (1 token/2s) per `tenant_id` via `acquire(tenant_id)`.
3. **`Scheduler/src/scheduler/core/consensus.py`**:
   - Lines 117–176: `RaftConsensusEngine.propose()` commits state allocations to the Raft consensus log over Zenoh channels (`public-intelligence/net/consensus/*`).
4. **`Scheduler/src/scheduler/core/engine.py` & `scheduler/algorithm.py`**:
   - `SchedulingEngine.schedule_task()` (lines 28–70) and `Scheduler.select_node()` (lines 22–88) filter active nodes by model capability and score them based on queue length, CPU/GPU utilization, VRAM ratio, and dampeners.
5. **`Scheduler/src/scheduler/main.py`**:
   - Lines 79–83: Routers `health_router`, `nodes_router`, `heartbeat_router`, `schedule_router`, and `ingress_router` are currently registered.
   - `CORSMiddleware` is not currently mounted on the FastAPI application.
6. **OpenAI Compatibility**:
   - Endpoint `POST /v1/chat/completions` does not exist yet in Scheduler.
   - Model listing endpoint `GET /v1/models` does not exist yet in Scheduler.

---

## 2. Logic Chain

1. **Observation 1 & 2** show that authentication (`verify_jwt`) and multi-tenant rate-limiting (`TokenBucketLimiter`) are already implemented for `/api/v1/tasks/submit` in `api/ingress.py` and `core/rate_limiter.py`.
2. **Observation 3 & 4** confirm that node selection (`SchedulingEngine` / `Scheduler.select_node`) and Raft consensus log commitment (`RaftConsensusEngine.propose`) are ready to be integrated for task allocation.
3. **Observation 5 & 6** demonstrate that while the core control plane primitives exist, `POST /v1/chat/completions`, `GET /v1/models`, message-to-prompt translation, OpenAI SSE formatting, and CORS middleware are currently missing from the Scheduler.
4. Therefore, implementing `POST /v1/chat/completions` requires creating `Scheduler/src/scheduler/api/openai.py` (with Pydantic models for OpenAI requests/responses and SSE generators), mounting `openai_router` and `CORSMiddleware` in `main.py`, and connecting `verify_jwt` and `TokenBucketLimiter` to secure the route.

---

## 3. Caveats

- Node streaming `/infer` yields line-by-line JSON stream buffers from Ollama or raw text chunks via Zenoh `BackpressuredReceiver`. The OpenAI gateway translator in Scheduler must cleanly parse these stream lines into standard OpenAI `data: {"id":..., "object":"chat.completion.chunk", ...}\n\n` SSE events.
- If no node in `NodeRegistry` currently advertises a requested model name, `select_node` will raise a `ValueError`, which should be translated into HTTP 404 (Model Not Found) or HTTP 400 with an OpenAI error format payload (`{"error": {"message": ..., "type": "invalid_request_error"}}`).

---

## 4. Conclusion

Phase 4.5 OpenAI REST Gateway & Scheduler Control Plane Integration is fully specified and ready for implementation. The missing components are:
1. `Scheduler/src/scheduler/models/openai.py` (or `api/openai.py`): Pydantic models for OpenAI Chat Completions and Model Listing.
2. `Scheduler/src/scheduler/api/openai.py`: FastAPI router implementing `POST /v1/chat/completions` (JSON & SSE streaming), `GET /v1/models`, message translation, JWT auth, rate-limiting, task proposal, and node proxying.
3. `Scheduler/src/scheduler/main.py`: Include `openai_router` and add `CORSMiddleware` for cross-origin browser requests from Requester Web UI Playground.
4. `Scheduler/tests/api/test_openai.py`: Unit and integration test suite covering translation, non-streaming/streaming completions, JWT auth failure, rate limiting, and model listing.

Full details are documented in `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_survey_2/survey_report.md`.

---

## 5. Verification Method

To verify the findings and subsequent implementation:
1. Inspect survey report: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_survey_2/survey_report.md`.
2. Inspect target codebase files:
   - `Scheduler/src/scheduler/api/ingress.py`
   - `Scheduler/src/scheduler/core/rate_limiter.py`
   - `Scheduler/src/scheduler/core/consensus.py`
   - `Scheduler/src/scheduler/core/engine.py`
   - `Scheduler/src/scheduler/main.py`
3. Run project verification commands in `Scheduler/`:
   ```bash
   cd /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Scheduler
   pytest
   ruff check .
   ruff format --check .
   mypy src
   ```
