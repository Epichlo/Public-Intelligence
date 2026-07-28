# Milestone M2 Forensic Audit Failure Fix Strategy Report

**Target File**: `Node/tests/test_m2_adversarial.py`  
**Working Directory**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/m2_explorer_remediation_1`  
**Auditor Report**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/m2_auditor_1/handoff.md`  

---

## 1. Executive Summary & Root Cause Analysis

During the Milestone M2 Forensic Audit, `m2_auditor_1` issued an **INTEGRITY_VIOLATION** verdict due to:
1. **Pytest Failure in `test_post_node_control_idempotence`**: Unhandled network connection attempt (`SchedulerError: Scheduler request POST /nodes/register failed: All connection attempts failed`) when running isolated or under specific suite execution orders.
2. **Ruff Linter Violations**: 9 `E501` line-length errors (> 88 characters) in `tests/test_m2_adversarial.py`.
3. **Ruff Formatting Violations**: `tests/test_m2_adversarial.py` failed `ruff format --check .`.
4. **Mypy Static Typing Errors**: Missing type parameters on generic types `asyncio.Queue` and `dict` in `tests/test_m2_adversarial.py`.

### Root Cause of Pytest Lifespan Failure
In `Node/src/node/main.py` line 12, `Runtime` is imported at module load time:
```python
from node.runtime import Runtime
```
When `TestClient(app)` is instantiated in tests, FastAPI triggers the `lifespan(app)` async context manager in `node.main`:
```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    runtime = Runtime(settings)
    app.state.runtime = runtime
    await runtime.start()
    yield
    await runtime.stop()
```
In `tests/test_m2_adversarial.py` (lines 166, 198, 225, 244, 266), tests patched `node.runtime.Runtime` instead of `node.main.Runtime`. Because `node.main` had already bound `Runtime` in its local module namespace, patching `node.runtime.Runtime` did **NOT** intercept the instantiation inside `node.main.lifespan`.

As a consequence:
1. FastAPI `lifespan` instantiated the unpatched `node.runtime.Runtime(settings)` object.
2. `app.state.runtime` was assigned the real `Runtime` object instead of `mock_runtime`.
3. `lifespan` executed `await real_runtime.start()`, which attempted an HTTP POST request to `http://localhost:8000/nodes/register`. When no real Scheduler was running, it threw an unhandled `SchedulerError`.
4. In `test_post_node_control_idempotence`, because `app.state.runtime` was not properly bound to `mock_runtime`, `mock_runtime.start.assert_not_called()` failed.

---

## 2. Step-by-Step Fix Strategy for Worker

The Worker must perform the following explicit code changes in `Node/tests/test_m2_adversarial.py`:

### Step 1: Update Module Imports
Add `Any` to typing imports at top of `tests/test_m2_adversarial.py`:
```python
from typing import Any
```

### Step 2: Fix All `patch` Target Strings to `node.main.Runtime`
Replace all occurrences of `patch("node.runtime.Runtime", ...)` with `patch("node.main.Runtime", ...)` across `tests/test_m2_adversarial.py`:

1. **Line 166** in `test_post_node_control_valid_case_and_whitespace_handling`:
   - *Change*: `patch("node.runtime.Runtime", return_value=mock_runtime)`
   - *To*: `patch("node.main.Runtime", return_value=mock_runtime)`

2. **Line 198** in `test_post_node_control_invalid_actions_return_400`:
   - *Change*: `patch("node.runtime.Runtime", return_value=mock_runtime)`
   - *To*: `patch("node.main.Runtime", return_value=mock_runtime)`

3. **Line 225** in `test_post_node_control_malformed_payloads_return_422`:
   - *Change*: `patch("node.runtime.Runtime", return_value=mock_runtime)`
   - *To*: `patch("node.main.Runtime", return_value=mock_runtime)`

4. **Line 244** in `test_post_node_control_extra_unrecognized_fields_handled_gracefully`:
   - *Change*: `patch("node.runtime.Runtime", return_value=mock_runtime)`
   - *To*: `patch("node.main.Runtime", return_value=mock_runtime)`

5. **Line 266** in `test_post_node_control_idempotence`:
   - *Change*: `patch("node.runtime.Runtime", return_value=mock_runtime)`
   - *To*: `patch("node.main.Runtime", return_value=mock_runtime)`

*(Note: Line 297 `test_get_sandbox_logs_limits_and_empty` already correctly uses `patch("node.main.Runtime", return_value=mock_runtime)`).*

### Step 3: Add Generic Type Arguments for Mypy
1. **Line 77** in `test_sandbox_log_buffer_concurrent_subscribers_and_publishers`:
   - *Change*: `async def consumer(idx: int, q: asyncio.Queue) -> None:`
   - *To*: `async def consumer(idx: int, q: asyncio.Queue[dict[str, Any]]) -> None:`
2. **Line 224** in `test_post_node_control_malformed_payloads_return_422`:
   - *Change*: `bad_payload: dict`
   - *To*: `bad_payload: dict[str, Any]`

### Step 4: Fix 9 Docstrings / Lines Exceeding 88 Characters (E501)
Reformat all module/function docstrings and code lines exceeding 88 characters:

1. **Lines 1-4**:
```python
"""Adversarial and stress test suite for Node Local Telemetry & Host Control APIs.

Focuses on concurrency race conditions, memory leaks, payload stress,
and state transitions.
"""
```

2. **Line 42**:
```python
    """Stress test: 10 threads writing 500 log lines concurrently while buffer
    caps at maxlen=1000.
    """
```

3. **Line 69**:
```python
    """Stress test: High-frequency log additions while subscribers
    subscribe/unsubscribe and read.
    """
```

4. **Line 151**:
```python
    """Verify whitespace trimming and case-insensitive handling of valid
    start/stop actions.
    """
```

5. **Line 226**:
```python
    """Verify malformed/missing action payloads trigger FastAPI/Pydantic HTTP
    422 error.
    """
```

6. **Line 239**:
```python
    """Verify extra unrecognized JSON payload fields do not break the
    control endpoint.
    """
```

7. **Line 266**:
```python
    """Verify triggering 'start' when already started or 'stop' when stopped
    does not crash or double-invoke.
    """
```

8. **Line 296**:
```python
    """Verify GET /api/v1/sandbox/logs handles various limit query parameters
    and empty state.
    """
```

### Step 5: Execute Automated Formatting
Run `ruff format` to apply canonical code formatting:
```bash
cd /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Node
.venv/bin/ruff format tests/test_m2_adversarial.py
```

---

## 3. Verification Commands for Worker

After applying the edits, the Worker must execute and verify the following commands in `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Node`:

```bash
cd /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Node

# 1. Run isolated test that previously failed
.venv/bin/pytest -v tests/test_m2_adversarial.py -k test_post_node_control_idempotence

# 2. Run full adversarial test suite
.venv/bin/pytest -v tests/test_m2_adversarial.py

# 3. Run complete Node test suite
.venv/bin/pytest

# 4. Run Ruff linter check
.venv/bin/ruff check .

# 5. Run Ruff formatter check
.venv/bin/ruff format --check .

# 6. Run Mypy static typing check on source and test files
.venv/bin/mypy src tests/test_m2_adversarial.py
```

**Required Acceptance Criteria**:
- `pytest`: 112 passed, 1 skipped (0 failures).
- `ruff check .`: 0 errors.
- `ruff format --check .`: 55 files formatted cleanly (0 files reformatted).
- `mypy`: 0 static typing errors.
