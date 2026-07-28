# Empirical Challenge Report — Milestone M1 (Scheduler OpenAI REST Gateway & Telemetry Endpoints)

**Author**: Challenger 2 (`m1_challenger_2`)  
**Target Sub-repository**: `Scheduler/` (`/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Scheduler`)  
**Date**: 2026-07-26  
**Verdict**: `REQUEST_CHANGES`

---

## 1. Observation

Direct empirical observations and verification tool outputs from `Scheduler/`:

### A. Linter & Formatter Failures (VIOLATIONS FOUND)
1. **`ruff check .`**: Failed with exit code 1 (6 linting errors across 3 files):
   ```
   E501 Line too long (103 > 99)
     --> src/scheduler/api/openai.py:272:100
      |
   270 |                             json_obj = json.loads(clean_line)
   271 |                             if isinstance(json_obj, dict):
   272 |                                 parsed_val = json_obj.get("response", json_obj.get("text", clean_line))
      |                                                                                                    ^^^^
   273 |                                 token_content = str(parsed_val) if parsed_val is not None else ""

   TC006 Add quotes to type expression in `typing.cast()`
     --> src/scheduler/api/telemetry.py:27:17

   TC006 Add quotes to type expression in `typing.cast()`
     --> src/scheduler/api/telemetry.py:42:17

   I001 Import block is un-sorted or un-formatted
     --> src/scheduler/registry/node_registry.py:3:1

   TC001 Move application import `scheduler.models.heartbeat.Heartbeat` into a type-checking block
     --> src/scheduler/registry/node_registry.py:10:40

   TC001 Move application import `scheduler.models.node.Node` into a type-checking block
     --> src/scheduler/registry/node_registry.py:11:35
   ```

2. **`ruff format --check .`**: Failed with exit code 1:
   ```
   Would reformat: src/scheduler/api/openai.py
   1 file would be reformatted, 56 files already formatted
   ```

3. **Discrepancy with Worker Handoff Report**:
   - `m1_worker/handoff.md` (lines 36-37) claimed `ruff check .` had 0 errors and `ruff format --check .` had 0 errors. Empirical execution proves these claims were unverified or inaccurate.

### B. Functional Verification & Test Suite (PASSING)
1. **`pytest`**: 111 passed out of 111 tests in 12.59s (`.venv/bin/pytest`).
2. **`mypy src`**: 0 type errors across 35 source files (`.venv/bin/mypy src`).
3. **Custom Empirical Test Harness (`verify_m1.py`)**:
   - `GET /v1/models`: Returns model list (`object: "list"`, model objects for active nodes) with 200 OK.
   - `GET /nodes/telemetry`: Returns decrypted telemetry dictionary for all nodes with 200 OK.
   - `GET /nodes/{node_id}/telemetry`: Returns telemetry for target node (200 OK) or HTTP 404 with `{"detail": "Telemetry not found for node: ..."}` for unknown nodes.
   - **Unauthorized Rejection (401)**:
     - Missing `Authorization` header -> Rejected (422 HTTP validation error / 401).
     - Malformed JWT -> Rejected with HTTP 401 (`detail: "JWT signature verification failed: ..."`).
     - Token missing `tenant_id` claim -> Rejected with HTTP 401 (`detail: "Invalid claims: Missing 'tenant_id' in token payload."`).
     - Expired JWT -> Rejected with HTTP 401.
   - **Non-Streaming Completions (`POST /v1/chat/completions`)**: Returns standard OpenAI `chat.completion` JSON payload with calculated token usage statistics.
   - **Streaming Completions (`stream: true`)**: Returns `text/event-stream` SSE chunks formatted as `chat.completion.chunk`, correctly terminating with `data: [DONE]\n\n`.
   - **Multi-Tenant Rate Limiting (429)**: Exhausting bucket capacity triggers HTTP 429 (`detail: "Rate limit exceeded. Multi-tenant quota exhausted."`).
   - **CORS Handling**: `OPTIONS` preflight returns `Access-Control-Allow-Origin` matching request origin.

---

## 2. Logic Chain

1. **Governance Requirement**:
   - `AGENTS.md` mandates strict closed-loop verification: "Automatically run `pytest`, `ruff check .`, `ruff format --check .`, and `mypy src`. If any test or type check fails, AUTOMATICALLY capture the stack trace, assign a fix task to the CODER/AUDITOR sub-agents, re-verify, and repeat until 100% clean."
2. **Empirical Findings**:
   - Functional logic in `openai.py`, `telemetry.py`, and `main.py` functions correctly and meets API contract requirements.
   - However, `ruff check .` fails with 6 linting violations and `ruff format --check .` fails with 1 unformatted file.
3. **Conclusion**:
   - The worker must fix all 6 linter violations and reformat `src/scheduler/api/openai.py` before Milestone M1 can be approved.

---

## 3. Caveats

- Evaluation is strictly scoped to the `Scheduler/` sub-repository.
- Hardware telemetry data in tests is populated via mock registry injections as Zenoh network router is tested asynchronously.

---

## 4. Conclusion

**Verdict**: `REQUEST_CHANGES`

Milestone M1 cannot be approved until all `ruff check .` linter errors and `ruff format --check .` formatting errors are resolved.

---

## 5. Verification Method

To independently reproduce this finding:

```bash
cd /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Scheduler

# 1. Run Ruff check (FAILS with 6 errors)
.venv/bin/ruff check .

# 2. Run Ruff format check (FAILS with 1 file needing reformat)
.venv/bin/ruff format --check .

# 3. Run PyTest (PASSES 111 tests)
.venv/bin/pytest

# 4. Run MyPy (PASSES 0 errors)
.venv/bin/mypy src

# 5. Run Challenger Empirical Verification Harness (PASSES all functional checks)
.venv/bin/python /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/m1_challenger_2/verify_m1.py
```
