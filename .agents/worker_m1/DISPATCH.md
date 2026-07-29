## 2026-07-29T01:24:37Z

You are the CODER Sub-Agent for Milestone M1. Your working directory is `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/worker_m1`.

Read the following files before starting work:
- `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/ORIGINAL_REQUEST.md`
- `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/AGENTS.md`
- `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_2/analysis.md`
- `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/orchestrator_phase4_6/PROJECT.md`

Your tasks for Milestone M1:
1. Update `TensorPayload` in `Node/src/node/models/sharding.py` and `Scheduler/src/scheduler/models/pipeline.py`:
   - Add fields:
     - `target_stage_index: int = Field(default=0, ge=0, description="Target pipeline stage index")`
     - `is_split_inference: bool = Field(default=False, description="Flag indicating asymmetric split-inference mode")`
     - `tensor_type: str = Field(default="intermediate_activation", description="Type of tensor activation")`
     - `sequence_id: int = Field(default=0, ge=0, description="Sequence ID for token generation steps")`
   - Implement `to_framed_bytes(self) -> bytes`:
     - Construct binary frame: magic header `b"PITP"` + 4-byte big-endian int (metadata JSON length) + UTF-8 metadata JSON + raw payload bytes (if `data` is `bytes`) or JSON payload if `data` is not bytes.
   - Implement `from_framed_bytes(cls, raw: bytes) -> TensorPayload`:
     - Parse binary frame starting with `b"PITP"` or fall back to standard JSON parsing.
2. Update `PipelineStage` in `Node/src/node/models/sharding.py` and `Scheduler/src/scheduler/models/pipeline.py`:
   - Add fields:
     - `is_local_boundary: bool = Field(default=False, description="Whether stage runs locally on client boundary")`
     - `stage_type: str = Field(default="compute", description="Stage type: local_embedding, compute, or local_lm_head")`
     - `is_split_inference: bool = Field(default=False, description="Whether stage participates in split inference")`
3. Update `BackpressuredStreamRouter` and `BackpressuredReceiver` in `Node/src/node/core/transport.py` and `Scheduler/src/scheduler/core/transport.py`:
   - Add `async send_tensor_payload(self, payload: TensorPayload, publish_func: Callable[[str, bytes], Awaitable[None]] | None = None, is_local: bool = False) -> None` using framed bytes over Zenoh tensor topics (`get_tensor_topic`).
   - Add `async start_tensor_listener(self, task_id: str, stage_index: int, on_payload: Callable[[TensorPayload], Awaitable[None]]) -> Any` subscribing to `get_tensor_topic(task_id, stage_index)`.
4. Add unit tests for `TensorPayload` binary framing and `PipelineStage` extensions in `Node/tests/test_sharding.py` and `Node/tests/test_transport.py`.
5. Run full closed-loop verification:
   - `PYTHONPATH=Node/src:Scheduler/src pytest Node/tests Scheduler/tests`
   - `ruff check .`
   - `ruff format --check .`
   - `mypy Scheduler/src Node/src`

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Regularly update `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/worker_m1/progress.md` with timestamps. Deliver a complete handoff report in `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/worker_m1/handoff.md` and send a message when done.
