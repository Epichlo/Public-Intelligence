## 2026-07-26T18:24:00Z

You are Worker 2 implementing Milestone M2 (Node Local Telemetry, Host Control & Sandbox Log APIs).
Your working directory is: /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/m2_worker

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Context & Instructions:
- Read /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/ORIGINAL_REQUEST.md.
- Read /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/PROJECT.md.
- Read /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_survey_3/survey_report.md.

Implementation Scope (Node Sub-repository: /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Node):
1. Create `Node/src/node/api/control.py`:
   - `GET /api/v1/node/telemetry`: Return real-time CPU, RAM, GPU, VRAM, and `wan_connected` P2P status (scraped via `TelemetryCollector` or system metrics).
   - `POST /api/v1/node/control`: Endpoint accepting `{"action": "start" | "stop"}` payload to trigger node runtime start/stop sequence.
   - `GET /api/v1/sandbox/logs`: Return recent Docker container sandbox execution log entries JSON.
   - `GET /api/v1/sandbox/logs/stream`: Yield real-time Docker sandbox execution logs as SSE stream (`text/event-stream`).
2. Update `Node/src/node/core/runtime.py`:
   - Extend `WorktreeManager.execute_in_sandbox()` to capture container stdout/stderr into an in-memory ring buffer (e.g. max 1,000 lines) so container logs are accessible via `control.py`.
3. Update `Node/src/node/main.py`:
   - Add `CORSMiddleware` (`allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`).
   - Include `control_router`.
4. Create test suite in `Node/tests/test_control_api.py` testing:
   - `GET /api/v1/node/telemetry`
   - `POST /api/v1/node/control`
   - `GET /api/v1/sandbox/logs` & log streaming.
5. Run verification tools inside `Node/`:
   - `pytest`
   - `ruff check .`
   - `ruff format --check .`
   - `mypy src`
6. Write your execution report and handoff report to /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/m2_worker/handoff.md and report back via send_message to parent.
