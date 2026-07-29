# Forensic Audit Report & Handoff: Phase 4.6 Asymmetric Split-Inference & Local Boundary Security

**Work Product**: Public Intelligence Phase 4.6 (Node & Scheduler sub-repositories)  
**Profile**: General Project / Forensic Audit  
**Verdict**: **`INTEGRITY VIOLATION`**

---

### Phase Results

- **Source Code Integrity Check**: **PASS** — Genuine implementation logic across `LocalBoundaryEngine`, `EchoBackend.execute_split_stage`, `OllamaBackend.execute_split_stage`, `SchedulingEngine.schedule_split_inference_pipeline`, and `POST /v1/chat/completions`. No hardcoded test returns or dummy/facade implementations found.
- **Zero Prompt Leakage & Security Boundary Audit**: **PASS** — `LocalBoundaryEngine` tokenizes, embeds, and unembeds prompts strictly on the local client gateway. Remote host activation payloads (`TensorPayload`) contain 0 raw prompt text, 0 prompt messages, and 0 integer token IDs.
- **Behavioral Test Suite Execution (`pytest`)**: **PASS** — 288 passed, 1 skipped (Node: 150 passed, 1 skipped; Scheduler: 125 passed; Root E2E: 13 passed).
- **Linter Quality Check (`ruff check`)**: **FAIL** — 13 linting errors in project source and test files (`Node/src/node/core/boundary_engine.py`, `Node/tests/test_local_boundary_challenger.py`, `Node/tests/test_split_inference_pipeline.py`, `Node/tests/test_split_inference_security.py`).
- **Code Formatter Check (`ruff format --check`)**: **FAIL** — 1 unformatted file (`Node/tests/test_split_inference_pipeline.py`).
- **Static Type Checker (`mypy`)**: **FAIL** — 2 static typing errors in `Node/src` (`Node/src/node/telemetry/collector.py:8` and `Node/src/node/core/transport.py:307`).
- **Documentation Alignment Audit**: **FAIL** — `docs/ROADMAP.md`, `Scheduler/docs/STATUS.md`, `Node/docs/STATUS.md`, and `AGENTS.md` are out of sync (marking Phase 4.6 as "Next Priority" / missing event log entry).

---

## 1. Observation

### Observation 1: Code Base & Security Leakage Audit (PASS)
1. **`LocalBoundaryEngine` (`Node/src/node/core/local_boundary.py` & `Scheduler/src/scheduler/core/local_boundary.py`)**:
   - Computes $H_0$ float activation vectors from local embedding matrix $E$ (`embed_prompt`, lines 219–253).
   - Unembeds $H_{N-1}$ float activation vectors through local LM Head $W_{\text{lm}}$ (`unembed_logits`, lines 255–338).
   - Integer token history (`_local_token_history`) remains local to client memory.
2. **Remote Stage Backend (`Node/src/node/backends/mock.py` & `ollama.py`)**:
   - `execute_split_stage` validates `input_payload.is_split_inference is True` and transforms floating-point activation vectors $H \in \mathbb{R}^{L \times d_{\text{model}}}$.
   - No prompt string parameters or integer token ID arguments are passed to remote nodes.
3. **Chain Allocator (`Scheduler/src/scheduler/core/engine.py`)**:
   - `schedule_split_inference_pipeline` allocates Stage 0 (`CLIENT_EMBEDDING`, `client_local`), Stages 1..K-1 (`REMOTE_HIDDEN`, remote nodes), and Stage K (`CLIENT_LM_HEAD`, `client_local`).

### Observation 2: Test Suite Execution (`pytest`) (PASS)
- Command: `PYTHONPATH=Node/src:Scheduler/src ./Node/.venv/bin/pytest Node/tests`
  - Output: `150 passed, 1 skipped in 2.36s`
- Command: `PYTHONPATH=Scheduler/src:Node/src ./Scheduler/.venv/bin/pytest Scheduler/tests`
  - Output: `125 passed in 10.42s`
- Command: `PYTHONPATH=Node/src:Scheduler/src ./Scheduler/.venv/bin/pytest tests/`
  - Output: `13 passed in 0.31s`

### Observation 3: Linter & Formatter Violations (`ruff`) (FAIL)
1. Command: `./Node/.venv/bin/ruff check Node/src Node/tests Scheduler/src Scheduler/tests tests/`
   - Output:
     ```
     F401 [*] `typing.Any` imported but unused
      --> Node/src/node/core/boundary_engine.py:5:20

     E501 Line too long (92 > 88)
      --> Node/tests/test_local_boundary_challenger.py:42:89

     E501 Line too long (106 > 88)
      --> Node/tests/test_split_inference_pipeline.py:33:89

     E501 Line too long (96 > 88)
      --> Node/tests/test_split_inference_pipeline.py:95:89

     E501 Line too long (92 > 88)
      --> Node/tests/test_split_inference_pipeline.py:139:89

     E501 Line too long (91 > 88)
      --> Node/tests/test_split_inference_security.py:4:89

     I001 [*] Import block is un-sorted or un-formatted
      --> Node/tests/test_split_inference_security.py:7:1

     E501 Line too long (99 > 88)
      --> Node/tests/test_split_inference_security.py:30:89

     E501 Line too long (95 > 88)
      --> Node/tests/test_split_inference_security.py:56:89

     E501 Line too long (110 > 88)
      --> Node/tests/test_split_inference_security.py:98:89

     E501 Line too long (89 > 88)
      --> Node/tests/test_split_inference_security.py:118:89

     E501 Line too long (89 > 88)
      --> Node/tests/test_split_inference_security.py:126:89

     F841 Local variable `token_ids_set` is assigned to but never used
      --> Node/tests/test_split_inference_security.py:141:5

     Found 13 errors.
     ```

2. Command: `./Node/.venv/bin/ruff format --check Node/src Node/tests Scheduler/src Scheduler/tests tests/`
   - Output:
     ```
     Would reformat: Node/tests/test_split_inference_pipeline.py
     1 file would be reformatted, 122 files already formatted
     ```

### Observation 4: Static Type Checker Violations (`mypy`) (FAIL)
- Command: `./Node/.venv/bin/mypy --config-file Node/pyproject.toml Node/src`
  - Output:
    ```
    Node/src/node/telemetry/collector.py:8: error: Unused "type: ignore" comment  [unused-ignore]
    Node/src/node/core/transport.py:307: error: Unused "type: ignore" comment  [unused-ignore]
    Found 2 errors in 2 files (checked 36 source files)
    ```

### Observation 5: Documentation Misalignment (FAIL)
1. `docs/ROADMAP.md`: Lines 13 & 43 list Phase 4.6 as `v0.40 (Next Priority)` and `Phase 4.6: Asymmetric Split-Inference & Local Boundary Security (v0.40 — Next Priority)` instead of `(Realized)`.
2. `Scheduler/docs/STATUS.md`: Lines 53 & 57 list Phase 4.5 as realized and Phase 4.6 as `Next Feature (v0.40 — Next Priority)`.
3. `Node/docs/STATUS.md`: Lines 40 & 46 list Phase 4.5 as realized and Phase 4.6 as `Upcoming Features (v0.40 — Next Priority)`.
4. `AGENTS.md`: Missing event log entry for Phase 4.6 implementation (Milestones M1–M4) under date `2026-07-29`.

---

## 2. Logic Chain

1. **Observation 1 & 2 (Code Logic & Behavioral Verification)**: The split-inference and local boundary isolation code features genuine mathematical tensor operations, zero prompt leakage over network payloads, and 100% test pass rate across unit/integration test suites (288 passed, 1 skipped).
2. **Observation 3 & 4 (Static Code Quality & Type Safety Invariants)**: Project invariants require strict zero-error output for `ruff check .`, `ruff format --check .`, and `mypy`. Observation 3 reveals 13 linter errors and 1 unformatted file. Observation 4 reveals 2 mypy errors on `Node/src`.
3. **Observation 5 (Documentation Synchronization Invariants)**: Protocol governance requires synchronizing `docs/ROADMAP.md`, `Scheduler/docs/STATUS.md`, `Node/docs/STATUS.md`, and `AGENTS.md` log upon feature completion. Observation 5 proves documentation remains out of sync.
4. **Forensic Rule Enforcement**: Under the Integrity Forensics rules, if ANY check fails, the verdict must be `INTEGRITY VIOLATION` and the work product must be rejected.

---

## 3. Caveats

- Implementation logic and zero prompt leakage security boundary are 100% functional and clean.
- Violations are restricted to linting/formatting rules, static typing errors, and documentation synchronization.
- No caveats regarding security leakage or cheating: no facade/dummy shortcuts were found.

---

## 4. Conclusion

Phase 4.6 Asymmetric Split-Inference implementation fails protocol quality and documentation invariants.
**Verdict**: **`INTEGRITY VIOLATION`**

### Required Action Items before Re-audit:
1. Fix 13 `ruff check` errors in `Node/src/node/core/boundary_engine.py`, `Node/tests/test_split_inference_security.py`, `Node/tests/test_split_inference_pipeline.py`, and `Node/tests/test_local_boundary_challenger.py`.
2. Run `ruff format` to reformat `Node/tests/test_split_inference_pipeline.py`.
3. Fix 2 `mypy` unused type ignore comments in `Node/src/node/telemetry/collector.py:8` and `Node/src/node/core/transport.py:307`.
4. Update `docs/ROADMAP.md`, `Scheduler/docs/STATUS.md`, `Node/docs/STATUS.md` to mark Phase 4.6 as `(Realized)`, and append Phase 4.6 event log entry to `AGENTS.md` under date `2026-07-29`.

---

## 5. Verification Method

To independently verify this audit verdict:

1. **Linter Check**:
   `./Node/.venv/bin/ruff check Node/src Node/tests Scheduler/src Scheduler/tests tests/`
   *Invalidation condition*: Must report 0 errors.

2. **Formatter Check**:
   `./Node/.venv/bin/ruff format --check Node/src Node/tests Scheduler/src Scheduler/tests tests/`
   *Invalidation condition*: Must report 0 files to reformat.

3. **Static Type Check**:
   `./Node/.venv/bin/mypy --config-file Node/pyproject.toml Node/src`
   `./Scheduler/.venv/bin/mypy --config-file Scheduler/pyproject.toml Scheduler/src`
   *Invalidation condition*: Must report `Success: no issues found`.

4. **Documentation Audit**:
   Inspect `docs/ROADMAP.md`, `Scheduler/docs/STATUS.md`, `Node/docs/STATUS.md`, and `AGENTS.md`.
   *Invalidation condition*: Phase 4.6 must be marked as `(Realized)` across all status matrices and documented in the `AGENTS.md` event log.

---

## 6. Raw Evidence Log

### A. Test Execution Summary (`pytest`)
```
Node: 150 passed, 1 skipped in 2.36s
Scheduler: 125 passed in 10.42s
Root E2E: 13 passed in 0.31s
Total: 288 passed, 1 skipped
```

### B. Linter Output (`ruff check`)
```
F401 [*] `typing.Any` imported but unused (Node/src/node/core/boundary_engine.py:5:20)
F841 Local variable `token_ids_set` assigned but unused (Node/tests/test_split_inference_security.py:141:5)
I001 [*] Import block un-sorted (Node/tests/test_split_inference_security.py:7:1)
E501 Line too long (8 errors in test_local_boundary_challenger.py, test_split_inference_pipeline.py, test_split_inference_security.py)
Found 13 errors.
```

### C. Formatter Output (`ruff format --check`)
```
Would reformat: Node/tests/test_split_inference_pipeline.py
1 file would be reformatted, 122 files already formatted
```

### D. Type Checker Output (`mypy`)
```
Node/src/node/telemetry/collector.py:8: error: Unused "type: ignore" comment [unused-ignore]
Node/src/node/core/transport.py:307: error: Unused "type: ignore" comment [unused-ignore]
Found 2 errors in 2 files (checked 36 source files)
```
