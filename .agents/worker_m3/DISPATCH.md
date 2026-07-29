## 2026-07-29T05:51:46Z
Assignee: CODER
Milestone: M3 (Matchmaker Split Allocation & OpenAI Gateway Split Streaming)

Milestone M3 Scope & Requirements:
1. Extend `SchedulingEngine` in `Scheduler/src/scheduler/core/engine.py`:
   - Implement `schedule_split_inference_pipeline(task: TaskProposal, total_layers: int = 32) -> list[PipelineStage]`:
     - Creates 3-tier asymmetric split-inference chain:
       * Stage 0 (Client Local Embedding): `stage_index=0`, `layer_range=LayerRange(start_layer=0, end_layer=0)`, `node_id="client_local"`, `is_local_boundary=True`, `stage_type=StageType.CLIENT_EMBEDDING`, `is_split_inference=True`.
       * Stages 1..K-1 (Remote Host Pipeline): Partition intermediate layers 1..total_layers-1 across eligible compute nodes based on available VRAM, `is_local_boundary=False`, `stage_type=StageType.REMOTE_HIDDEN`, `is_split_inference=True`.
       * Stage K (Client Local LM Head): `stage_index=K`, `layer_range=LayerRange(start_layer=total_layers, end_layer=total_layers)`, `node_id="client_local"`, `is_local_boundary=True`, `stage_type=StageType.CLIENT_LM_HEAD`, `is_split_inference=True`.
     - Validates local boundary placement and layer continuity.
2. Update OpenAI Gateway API in `Scheduler/src/scheduler/api/openai.py`:
   - Update `POST /v1/chat/completions`:
     - When split-inference execution path is enabled/requested, route execution through `LocalBoundaryEngine` and `schedule_split_inference_pipeline`.
     - Tokenize prompt and compute local Layer 0 embeddings H_0 via `LocalBoundaryEngine.embed_prompt(prompt)` at the local gateway.
     - Stream activation payload H_0 over Zenoh to remote stage 1.
     - Receive output activation vector H_(N-1) from remote stages.
     - Compute local Layer N LM Head unembedding/sampling via `LocalBoundaryEngine.unembed_logits(H_(N-1))` locally.
     - Return/stream OpenAI-compliant SSE completion chunks (`chat.completion.chunk`).
3. Unit Test Suites:
   - Create `Scheduler/tests/test_split_pipeline_scheduling.py` testing `schedule_split_inference_pipeline` (3-tier stage construction, boundary flags, layer ranges).
   - Create `Scheduler/tests/test_openai_split_inference.py` testing `POST /v1/chat/completions` split-inference routing and streaming response.
4. Closed-Loop Verification:
   - Run `pytest`, `ruff check .`, `ruff format --check .`, `mypy Scheduler/src Node/src`.
   - Ensure 100% test pass rate with zero linting or static typing errors across Node and Scheduler.
   - Write handoff.md in your working directory and notify parent via send_message when complete.
