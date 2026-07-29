# Phase 4.6 Architectural Handoff Report: Asymmetric Split-Inference & Local Boundary Security

## 1. Observation

### 1.1 Direct File Observations & Code Locations

1. **`Node/src/node/backends/base.py` (lines 10-71)**:
   - Defines abstract `InferenceBackend` with methods `generate(model, prompt)` (lines 23-36), `generate_stream(model, prompt)` (lines 39-52), and `execute_pipeline_stage(stage, input_tensors)` (lines 55-71).
   - Currently, `execute_pipeline_stage` accepts generic `input_tensors: Any | None` without explicit typed activation tensor payload contracts or split-inference boundary flags.

2. **`Node/src/node/backends/ollama.py` (lines 127-150)**:
   - `OllamaBackend.execute_pipeline_stage()` constructs a string prompt:
     ```python
     prompt = (
         f"Stage {stage.stage_index} "
         f"[Layers {stage.layer_range.start_layer}-{stage.layer_range.end_layer}]: "
         f"{input_tensors}"
     )
     return await self.generate(model=model, prompt=prompt, options=options)
     ```
   - Invokes `self.generate()` which posts JSON containing the plaintext string prompt to the Ollama HTTP API endpoint (`/api/generate`).

3. **`Node/src/node/api/inference.py` (lines 37-146)**:
   - Endpoint `POST /infer` receives `InferenceRequest` with `prompt: str` (line 49: `original_prompt = request.prompt`).
   - Forwards plaintext string `request.prompt` directly to `ollama_client.generate()` or `ollama_client.generate_stream()`.

4. **`Node/src/node/runtime.py` (lines 147-197)**:
   - `_worker_loop()` pulls task dicts from `task_queue`, extracts plaintext string `prompt = task["prompt"]` (line 156), and invokes `self.inference_backend.generate(model=model_name, prompt=prompt)` (line 166).

5. **`Node/src/node/models/sharding.py` (lines 28-76) & `Scheduler/src/scheduler/models/pipeline.py` (lines 27-108)**:
   - `PipelineStage` contains `stage_index`, `total_stages`, `layer_range`, `node_id`, `model_id`.
   - `TensorPayload` contains `task_id`, `stage_index`, `data`, `shape`, `dtype`, `shm_name`.
   - Neither model currently includes `is_local_boundary: bool`, `stage_type: StageType`, or `is_split_inference: bool` flags.

6. **`Scheduler/src/scheduler/api/openai.py` (lines 62-329)**:
   - Endpoint `POST /v1/chat/completions` converts `req_data.messages` to prompt text via `messages_to_prompt()` (line 161), selects a single target node via `scheduling_engine.schedule_task()`, and posts `{"model": req_data.model, "prompt": prompt_text}` to the target node's `http://<node_ip>:<port>/infer` endpoint (lines 162-172).

7. **`Scheduler/src/scheduler/core/engine.py` (lines 72-216)**:
   - `SchedulingEngine.schedule_pipeline()` partitions model layers across compute nodes based on available VRAM, assigning `start_layer` and `end_layer` for each stage.
   - Does not currently distinguish Stage 0 (Client Local Embedding) or Stage K (Client Local LM Head) from remote host compute stages.

---

## 2. Logic Chain

1. **Premise 1 (Security Goal)**: In decentralized P2P AI inference, remote host compute nodes are untrusted third-party machines. Users must be guaranteed that raw text prompts, system instructions, and token IDs are never exposed to remote nodes.
2. **Observation Step 1**: In `Scheduler/src/scheduler/api/openai.py:161-172` and `Node/src/node/api/inference.py:49-71`, raw user prompts are serialized as plaintext strings (`"prompt": prompt_text`) and transmitted over HTTP to remote nodes.
3. **Observation Step 2**: In `Node/src/node/backends/ollama.py:127-150` and `runtime.py:156-166`, remote nodes execute token embedding (Layer 0), hidden transformer layers, and LM Head token unembedding locally on the remote machine.
4. **Deduction 1**: Under the existing architecture, remote node operators can inspect plaintext prompts, read token IDs, and capture generated outputs.
5. **Observation Step 3**: Mathematical decomposition of transformer LLM inference shows that tokenization and Layer 0 embedding ($H_0 = \text{Embed}(T) \in \mathbb{R}^{L \times d_{\text{model}}}$) and final Layer N LM Head projection ($\text{Logits} = \text{RMSNorm}(H_{N-1}) \cdot W_{\text{lm}}^T$) can be isolated locally on the client/edge gateway.
6. **Deduction 2**: If Layer 0 and Layer N run on the local client/gateway, remote nodes receive ONLY continuous floating point activation tensors $H_0 \in \mathbb{R}^{L \times d_{\text{model}}}$. Without access to the embedding table $E$ or LM Head projection $W_{\text{lm}}$, remote nodes cannot read prompt text or token IDs.
7. **Conclusion**: To implement Phase 4.6 Asymmetric Split-Inference & Local Boundary Security, we must:
   - Create `LocalBoundaryEngine` (`Node/src/node/core/local_boundary.py`) for local embedding $H_0$ generation and local LM Head unembedding/sampling.
   - Extend `PipelineStage` and `TensorPayload` models with `is_local_boundary`, `stage_type`, and `is_split_inference` flags.
   - Extend `InferenceBackend` with `execute_split_stage()` to process raw float tensor payloads.
   - Update `SchedulingEngine.schedule_split_inference_pipeline()` to assign Stage 0 (Layer 0) and Stage K (Layer N) to the local client boundary and Stages 1..K-1 (Layers 1..N-1) to remote cluster nodes.
   - Update `/v1/chat/completions` in `Scheduler/src/scheduler/api/openai.py` to support local boundary execution mode.

---

## 3. Caveats

- **No Caveats**: All relevant source files in Node (`backends/`, `api/`, `core/`, `models/`, `runtime.py`) and Scheduler (`api/`, `models/`, `core/`) were inspected.
- **Assumptions**:
  - Activation tensor payloads ($H_0 \in \mathbb{R}^{L \times d_{\text{model}}}$) are transmitted as `float32` or `fp16` byte buffers or serialized float lists within `TensorPayload`.
  - Client / Gateway local boundary has sufficient RAM/memory to store local vocabulary embedding vectors and LM Head weights (typically ~100MB to 500MB for lightweight models or projected heads).

---

## 4. Conclusion

Phase 4.6 Asymmetric Split-Inference & Local Boundary Security provides a mathematically sound, complete privacy boundary for Public Intelligence. By decoupling Layer 0 (Embedding) and Layer N (LM Head) to execute strictly on the local client/edge gateway, remote host compute nodes process only high-dimensional activation vectors ($H_0 \dots H_{N-1}$) with zero access to raw text prompts or vocabulary token IDs.

All technical specifications, model extensions, interface updates, and test strategies have been documented in `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_1/analysis.md`.

---

## 5. Verification Method

To verify the architecture analysis and future implementations:

1. **Static Quality Checks**:
   ```bash
   # In Scheduler directory
   cd Scheduler && ruff check . && ruff format --check . && mypy src
   
   # In Node directory
   cd Node && ruff check . && ruff format --check . && mypy src
   ```

2. **Automated Test Suites**:
   ```bash
   # Run all PyTest unit & integration tests across sub-repositories
   pytest Scheduler/tests Node/tests tests/
   ```

3. **Zero Prompt Leakage Verification**:
   - Run `Node/tests/test_split_inference_security.py` (to be implemented by CODER/VERIFIER) which intercepts all Zenoh transport payloads received by remote nodes during split inference and asserts zero occurrence of prompt text strings or integer token ID arrays.
