## 2026-07-29T11:21:05Z

Implement Milestone M2 (Local Boundary Isolation Engine & Backend Split-Inference Interfaces) for Public Intelligence Phase 4.6.

Milestone M2 Scope & Requirements:
1. Implement `LocalBoundaryEngine` in `Node/src/node/core/local_boundary.py` (and re-export / mirror in `Scheduler/src/scheduler/core/local_boundary.py` or share as needed):
   - Client-side engine that holds Layer 0 (Embedding) and Layer N (LM Head / Sampler) locally on the client/edge gateway.
   - `embed_prompt(prompt: str) -> TensorPayload`: Tokenizes text prompt, computes Layer 0 embeddings H_0 in R^(L x d_model), returns TensorPayload with `is_split_inference=True`, `stage_index=0`, `tensor_type="activation"`. Raw prompt tokens remain strictly in local memory.
   - `unembed_logits(activation_payload: TensorPayload, temperature: float = 1.0) -> tuple[int, str]`: Accepts H_(N-1) activation payload from remote hidden layers 1..N-1, projects through local LM Head matrix W_lm, samples next token ID and decoded token text string.
2. Extend `InferenceBackend` abstract class in `Node/src/node/backends/base.py`:
   - Add async abstract method `execute_split_stage(self, stage: PipelineStage, input_payload: TensorPayload, options: dict[str, Any] | None = None) -> TensorPayload`.
3. Implement `execute_split_stage` in `EchoBackend` (`Node/src/node/backends/mock.py`) and `OllamaBackend` (`Node/src/node/backends/ollama.py`):
   - In `EchoBackend`: Transform activation vectors deterministically across intermediate hidden layers (Layers 1..N-1), keeping payload shape, dtype, `is_split_inference=True`.
   - In `OllamaBackend`: Handle activation payload stage execution.
4. Unit Tests:
   - Create `Node/tests/test_local_boundary.py` testing `LocalBoundaryEngine` (embedding generation, unembedding/sampling, shape validation).
   - Update `Node/tests/test_backends.py` (or existing backend test suite) verifying `execute_split_stage` on `EchoBackend` and `OllamaBackend`.
5. Verification:
   - Run `pytest`, `ruff check .`, `ruff format --check .`, `mypy Scheduler/src Node/src`.
   - Ensure 100% test pass rate with zero linting or typing errors across Node and Scheduler repositories.
   - Write handoff.md in your working directory and notify parent via send_message when complete.
