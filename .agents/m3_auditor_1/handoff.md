# Forensic Audit Report & Handoff — Milestone M3

**Work Product**: Milestone M3 (Matchmaker Allocation & OpenAI Gateway Split Streaming)
**Profile**: General Project
**Verdict**: INTEGRITY VIOLATION

---

## Forensic Audit Summary

| Check Name | Status | Details |
|------------|--------|---------|
| **FACADE_AND_IMPLEMENTATION_CHECK** | 🔴 FAIL | `SchedulingEngine.schedule_split_inference_pipeline()` is completely missing from `Scheduler/src/scheduler/core/engine.py`. |
| **PROMPT_LEAK_CHECK** | 🔴 FAIL | `Scheduler/src/scheduler/api/openai.py` leaks raw text prompts directly to compute node `/infer` endpoints. |
| **LINTING_COMPLIANCE_CHECK** | 🔴 FAIL | `ruff check .` failed with 3 errors in `Scheduler/src/scheduler/core/local_boundary.py`. |
| **TEST_SUITE_CHECK** | 🔴 FAIL | `pytest` failed 1 test in `Scheduler` and 5 tests in `Node`. |
| **HARDCODED_RESULT_CHECK** | 🟢 PASS | No hardcoded result stubs found. |

---

## 1. Observation

### Observation 1.1: Missing Implementation of `schedule_split_inference_pipeline`
Inspection of `Scheduler/src/scheduler/core/engine.py` reveals that `SchedulingEngine` contains only `schedule_task()` (lines 28-70) and `schedule_pipeline()` (lines 72-216).
The required `schedule_split_inference_pipeline()` method specified in `PROJECT.md` (Feature 5) for 3-tier boundary allocation (Stage 0 Local Embedding -> Stages 1..K-1 Remote Hidden Layers -> Stage K Local LM Head) is completely absent.

### Observation 1.2: Raw Prompt Text Leakage in OpenAI Gateway
Inspection of `Scheduler/src/scheduler/api/openai.py` (lines 161-166):
```python
161:     prompt_text = messages_to_prompt(req_data.messages)
162:     infer_payload = {
163:         "model": req_data.model,
164:         "prompt": prompt_text,
165:         "stream": req_data.stream,
166:     }
```
`openai.py` constructs `infer_payload` containing raw prompt text and sends it via `httpx` POST directly to `target_node.ip_address` at `http://<node_ip>:8080/infer`. There is zero split-inference routing or local boundary engine activation.

### Observation 1.3: Ruff Linting Failures in Scheduler
Command executed:
`/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Scheduler/.venv/bin/ruff check .`

Output:
```
B905 `zip()` without an explicit `strict=` parameter
   --> src/scheduler/core/local_boundary.py:311:49
    |
309 |         for tid in range(self.vocab_size):
310 |             weight_vec = self.lm_head_matrix[tid]
311 |             dot_product = sum(w * h for w, h in zip(weight_vec, h_last))
    |                                                 ^^^^^^^^^^^^^^^^^^^^^^^
312 |             logits.append(dot_product)

E741 Ambiguous variable name: `l`
   --> src/scheduler/core/local_boundary.py:317:50
317 |             scaled_logits = [l / temperature for l in logits]

E741 Ambiguous variable name: `l`
   --> src/scheduler/core/local_boundary.py:319:51
319 |             exp_logits = [math.exp(l - max_l) for l in scaled_logits]

Found 3 errors.
```

### Observation 1.4: Test Suite Failures in Scheduler and Node
Command executed in `Scheduler`:
`/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Scheduler/.venv/bin/pytest`
Result: `1 failed, 110 passed`
Failed test: `tests/test_consensus.py::test_consensus_leader_election_and_replication`

Command executed in `Node`:
`/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/Node/.venv/bin/pytest`
Result: `5 failed, 130 passed`
Failed tests: `tests/test_backend_split_stage_challenger.py` (5 tests)

---

## 2. Logic Chain

1. **Step 1**: Requirement R2 & R3 of Phase 4.6 and Feature 5 of `PROJECT.md` mandate `SchedulingEngine.schedule_split_inference_pipeline()` in `Scheduler/src/scheduler/core/engine.py` to construct 3-tier split-inference chains. Observation 1.1 proves this method does not exist.
2. **Step 2**: Phase 4.6 Requirement R1 and project security invariants state that raw prompt text or token IDs MUST NOT be transmitted to remote host nodes. Observation 1.2 demonstrates that `Scheduler/src/scheduler/api/openai.py` packs raw prompt text into `infer_payload` and sends it directly to remote host node `/infer` endpoints over HTTP.
3. **Step 3**: Quality invariants require 100% clean linting (`ruff check .`) and passing test suites (`pytest`). Observations 1.3 and 1.4 show multiple linter and test suite failures.
4. **Conclusion**: The work product fails core security boundary invariants, implementation specifications, linting compliance, and test suite execution. Therefore, the verdict is **INTEGRITY VIOLATION**.

---

## 3. Caveats

No caveats. All findings were verified empirically through direct file inspection and command execution.

---

## 4. Conclusion

Final Assessment: **INTEGRITY VIOLATION**

The Milestone M3 work product MUST be rejected due to:
1. Complete absence of `schedule_split_inference_pipeline()` in `Scheduler/src/scheduler/core/engine.py`.
2. Critical privacy/security violation: raw prompt text leakage over HTTP to remote compute nodes in `Scheduler/src/scheduler/api/openai.py`.
3. Failure of linting checks in `Scheduler/src/scheduler/core/local_boundary.py`.
4. Test suite failures in `Scheduler` and `Node`.

---

## 5. Verification Method

To independently verify these findings, run:

1. **Check missing method in `engine.py`**:
   `grep -n "schedule_split_inference_pipeline" Scheduler/src/scheduler/core/engine.py`
   (Returns empty)

2. **Check prompt leakage in `openai.py`**:
   `grep -n -C 5 "prompt_text = " Scheduler/src/scheduler/api/openai.py`
   (Shows `infer_payload` sending raw prompt to `node_url`)

3. **Check linter status**:
   `Scheduler/.venv/bin/ruff check .`

4. **Run test suites**:
   `Scheduler/.venv/bin/pytest`
   `Node/.venv/bin/pytest`
