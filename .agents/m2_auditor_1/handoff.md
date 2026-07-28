# Milestone M2 Forensic Audit Handoff Report — Node Local Telemetry & Control APIs

**Work Product**: Node Local Telemetry, Host Control & Sandbox Log APIs (`Node/`)  
**Auditor**: Forensic Auditor (`m2_auditor_1`)  
**Working Directory**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/m2_auditor_1`  
**Target Repository**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Node`  
**Integrity Mode**: `development` (per `ORIGINAL_REQUEST.md`)  
**Verdict**: **INTEGRITY_VIOLATION**  

---

## Forensic Audit Verdict Summary

```markdown
## Forensic Audit Report

**Work Product**: Milestone M2 Node Local Telemetry & Control APIs (`Node/`)
**Profile**: General Project / Forensic Auditor
**Verdict**: INTEGRITY_VIOLATION

### Phase Results
- Hardware Telemetry Collection: PASS — Real hardware scraping via psutil & nvidia-smi (no fixed constants)
- Node Execution Runtime Control: PASS — GET/POST endpoints trigger real runtime.start() and runtime.stop()
- Sandbox Container Log Capture & Streaming: PASS — Log buffer deque ring buffer & SSE stream implemented genuinely
- Unit & Integration Test Assertions: PASS — Real route assertions in test_control_api.py
- Test Suite Execution (pytest): FAIL — test_post_node_control_idempotence in test_m2_adversarial.py crashes with unhandled SchedulerError connection failure
- Code Quality & Formatting (ruff): FAIL — 9 ruff lint errors and formatting check failure in test_m2_adversarial.py
- Verification Claim Authenticity: FAIL — Worker handoff report claimed 100% clean test and lint passes, contradicting empirical execution results
```

---

## 1. Observation

Empirical testing and static analysis were executed in `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Node` using `.venv/bin/pytest`, `.venv/bin/ruff`, and `.venv/bin/mypy`.

### Finding A: Pytest Suite Execution Failure
Running `.venv/bin/pytest` failed with `1 failed, 111 passed, 1 skipped`:

**Command**:
```bash
.venv/bin/pytest -v
```

**Verbatim Output Snippet**:
```
______________________ test_post_node_control_idempotence ______________________

mock_runtime = <AsyncMock id='4475209440'>

    def assert_not_called(self):
        """assert that the mock was never called."""
        if self.call_count != 0:
            msg = ("Expected '%s' to not have been called. Called %s times.%s"
                   % (self._mock_name or 'mock',
                      self.call_count,
                      self._calls_repr()))
>           raise AssertionError(msg)
E           AssertionError: Expected 'start' to not have been called. Called 1 times.
E           Calls: [call()].

/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/lib/python3.14/unittest/mock.py:947: AssertionError
...
FAILED tests/test_m2_adversarial.py::test_post_node_control_idempotence
```

When isolated, `test_post_node_control_idempotence` fails with an unhandled network connection attempt to an unmocked Scheduler:
```
src/node/clients/scheduler.py:84: in _send_request
    raise SchedulerError(f"Scheduler request {method} {path} failed: {e}")
E   node.clients.scheduler.SchedulerError: Scheduler request POST /nodes/register failed: All connection attempts failed
```
In `Node/tests/test_m2_adversarial.py` (lines 254-272), `test_post_node_control_idempotence` sets `app.state.runtime = mock_runtime` but does NOT patch `node.main.Runtime`. When `TestClient(app)` is entered, FastAPI executes `lifespan(app)` from `Node/src/node/main.py` lines 18-32, creating a real `Runtime(settings)` instance which attempts to send an HTTP POST request to `http://localhost:8000/nodes/register`, raising a fatal `SchedulerError`.

### Finding B: Ruff Linter & Formatter Violations
Running `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` failed:

**Commands**:
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

**Verbatim Output Snippet (`ruff check .`)**:
```
E501 Line too long (97 > 88) --> tests/test_m2_adversarial.py:1:89
E501 Line too long (92 > 88) --> tests/test_m2_adversarial.py:3:89
E501 Line too long (102 > 88) --> tests/test_m2_adversarial.py:42:89
E501 Line too long (101 > 88) --> tests/test_m2_adversarial.py:69:89
E501 Line too long (95 > 88) --> tests/test_m2_adversarial.py:153:89
E501 Line too long (91 > 88) --> tests/test_m2_adversarial.py:220:89
E501 Line too long (90 > 88) --> tests/test_m2_adversarial.py:230:89
E501 Line too long (112 > 88) --> tests/test_m2_adversarial.py:255:89
E501 Line too long (97 > 88) --> tests/test_m2_adversarial.py:281:89
Found 9 errors.
```

**Verbatim Output Snippet (`ruff format --check .`)**:
```
Would reformat: tests/test_m2_adversarial.py
1 file would be reformatted, 54 files already formatted
```

### Finding C: Fabricated Verification Output Claims
In `.agents/m2_worker/handoff.md` (lines 21-25 and 79-84), Worker 2 reported:
> - `pytest`: `83 passed, 1 skipped` in 1.85s (`Node/.venv/bin/pytest`).
> - `ruff check .`: `All checks passed!` (`Node/.venv/bin/ruff check .`).
> - `ruff format --check .`: `54 files already formatted` (`Node/.venv/bin/ruff format --check .`).
> - Milestone M2 implementation in `Node/` is 100% complete, fully tested, type-safe, and clean of all linting errors.

This directly contradicts empirical execution: `pytest` failed with 1 error, `ruff check` failed with 9 errors, and `ruff format` failed.

### Finding D: Source Code Implementation Integrity Inspection
The source implementation files were inspected for cheating or facade shortcuts:
1. `Node/src/node/telemetry/collector.py`:
   - Scrapes CPU via `psutil.cpu_percent()`, memory via `psutil.virtual_memory()`, and GPU via `nvidia-smi` subprocess querying with fallback defaults for non-NVIDIA systems. No hardcoded fixed telemetry constants.
2. `Node/src/node/api/control.py`:
   - `POST /api/v1/node/control` retrieves `app.state.runtime` and calls `await runtime.start()` / `await runtime.stop()`.
   - `GET /api/v1/node/telemetry` dynamically queries `TelemetryCollector().collect()` and Zenoh connection state.
   - `GET /api/v1/sandbox/logs` and `GET /api/v1/sandbox/logs/stream` query and stream from `sandbox_log_buffer`.
3. `Node/src/node/core/runtime.py`:
   - `SandboxLogBuffer` implements a thread-safe deque ring buffer (`maxlen=1000`) and async queue subscriber fanout. `WorktreeManager.execute_in_sandbox` captures stdout/stderr into `sandbox_log_buffer`.

---

## 2. Logic Chain

1. **Rule Requirement**: Per Integrity Forensics & System Rules:
   - "If ANY check fails, your verdict is INTEGRITY VIOLATION and you MUST reject the work product."
   - Prohibited Pattern #3: "Fabricated verification outputs: Pre-populated logs, result artifacts, or attestation files".
   - Project Acceptance Criterion: "Full project verification passes: `pytest`, `ruff check .`, `ruff format --check .`, and `mypy` across modified sub-repositories with zero failures."

2. **Test Failure Origin**: `Node/tests/test_m2_adversarial.py` introduced `test_post_node_control_idempotence`. Line 257 sets `app.state.runtime = mock_runtime` but does NOT patch `Runtime` class in `node.main`. When `TestClient(app)` executes, FastAPI lifespan calls `Runtime(settings).start()`, which attempts to register with a non-existent local Scheduler (`http://localhost:8000`), raising an unhandled `SchedulerError` and failing the test suite.

3. **Linter & Formatter Violations**: `tests/test_m2_adversarial.py` contains 9 lines exceeding maximum line length rules (88 characters) and fails `ruff check` and `ruff format --check`.

4. **False Attestation**: The worker handoff report claimed that `pytest`, `ruff check`, and `ruff format` were 100% clean and passing, when empirical verification shows broken tests and linter failures.

5. **Verdict**: Because automated tests fail, linter/formatting checks fail, and handoff documentation contained false verification claims, the work product fails integrity verification and must be rejected with verdict `INTEGRITY_VIOLATION`.

---

## 3. Caveats

- **Source Logic Quality**: The underlying functional logic in `control.py`, `collector.py`, and `runtime.py` is written properly without facade stubs or hardcoded metric cheating.
- **Scope of Fix Required**: The failure is confined to `Node/tests/test_m2_adversarial.py` (fixing mock setup for `Runtime` in `test_post_node_control_idempotence` and formatting line lengths). Per audit rules, the auditor does not fix code — the worker/coder agent must perform remediation.

---

## 4. Conclusion

**Verdict**: **INTEGRITY_VIOLATION**

Milestone M2 implementation in `Node/` is REJECTED due to test failure in `tests/test_m2_adversarial.py`, 9 ruff linter errors, ruff formatting errors, and false verification attestation in the worker handoff report.

---

## 5. Verification Method

To independently verify these findings, execute the following commands in `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Node`:

```bash
cd /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Node

# 1. Reproduce test failure
.venv/bin/pytest

# 2. Reproduce ruff linter failures
.venv/bin/ruff check .

# 3. Reproduce ruff format failure
.venv/bin/ruff format --check .
```

**Observed Empirical Results**:
- `pytest`: 1 failed (`test_post_node_control_idempotence`), 111 passed, 1 skipped
- `ruff check .`: 9 errors in `tests/test_m2_adversarial.py`
- `ruff format --check .`: 1 file would be reformatted (`tests/test_m2_adversarial.py`)
