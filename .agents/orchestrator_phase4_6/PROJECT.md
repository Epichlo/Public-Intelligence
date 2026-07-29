# Project: Public Intelligence — Phase 4.6 Asymmetric Split-Inference & Local Boundary Security

## Architecture
- **Local Boundary Isolation**: Decouples Layer 0 (Embedding $E$) and final Layer N (LM Head $W_{\text{lm}}$ + Sampler) onto local client/edge gateway.
- **Activation Vector Transport**: Intermediate layers (Layers 1..N-1) execute on remote P2P host nodes. Vector activations $H \in \mathbb{R}^{L \times d_{\text{model}}}$ stream over Zenoh via `TensorPayload` binary framing (`PITP` header + payload bytes).
- **Matchmaker Allocation**: `SchedulingEngine.schedule_split_inference_pipeline()` creates Stage 0 (Client Local Embedding), Stages 1..K-1 (Remote Host Pipeline), Stage K (Client Local LM Head).
- **Security & Privacy**: Zero access to raw prompt text or token IDs on remote host nodes.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | TensorPayload Binary Framing & Split Flags | Extend `TensorPayload` & `PipelineStage` with `is_split_inference`, `target_stage_index`, `to_framed_bytes()`, `from_framed_bytes()` | M1 | R2 |
| 2 | Zenoh Activation Stream Transport | Extend `BackpressuredStreamRouter` & `BackpressuredReceiver` with `send_tensor_payload()` & `start_tensor_listener()` | M1 | R2 |
| 3 | Local Boundary Isolation Engine | Implement `LocalBoundaryEngine` for local Layer 0 token embedding and local Layer N LM Head token sampling | M2 | R1 |
| 4 | Backend Split-Inference Interfaces | Extend `InferenceBackend` with `execute_split_stage()` and update `OllamaBackend` & `EchoBackend` | M2 | R1, R3 |
| 5 | Matchmaker Split-Inference Chain Allocator | Implement `SchedulingEngine.schedule_split_inference_pipeline()` for 3-tier boundary allocation | M3 | R3 |
| 6 | OpenAI Gateway Split-Inference Support | Update `POST /v1/chat/completions` in `openai.py` for split-inference mode | M3 | R3 |
| 7 | Zero Prompt Leakage Security Audit Test Suite | Create `test_split_inference_security.py` verifying remote node payload payloads contain 0 raw prompt tokens | M4 | R4 |
| 8 | End-to-End Split-Inference Integration Test Suite | Create `test_split_inference_pipeline.py` verifying E2E activation streaming and generation | M4 | R4 |
| 9 | Tri-Factor Static Typing & Documentation Sync | Achieve 100% `pytest`, `ruff check`, `ruff format --check`, `mypy` pass & update ROADMAP/STATUS/AGENTS logs | M4 | R5 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Transport & Data Models | `TensorPayload`, `PipelineStage`, `BackpressuredStreamRouter` activation transport | None | DONE |
| M2 | Local Boundary Engine & Backends | `LocalBoundaryEngine`, `InferenceBackend.execute_split_stage`, backend integration | M1 | DONE |
| M3 | Matchmaker & OpenAI Gateway | `schedule_split_inference_pipeline`, `POST /v1/chat/completions` integration | M1, M2 | DONE |
| M4 | Verification, Security Audit & Docs | E2E tests, zero prompt leakage audit, mypy/ruff/pytest compliance, docs update | M1, M2, M3 | DONE |

## Code Layout
- Node:
  - `Node/src/node/models/sharding.py` (`TensorPayload`, `PipelineStage`)
  - `Node/src/node/core/transport.py` (`BackpressuredStreamRouter`, `BackpressuredReceiver`)
  - `Node/src/node/core/local_boundary.py` (`LocalBoundaryEngine`)
  - `Node/src/node/backends/base.py`, `ollama.py`, `mock.py` (`execute_split_stage`)
  - `Node/tests/test_sharding.py`, `test_transport.py`, `test_local_boundary.py`, `test_split_inference_pipeline.py`, `test_split_inference_security.py`
- Scheduler:
  - `Scheduler/src/scheduler/models/pipeline.py` (`TensorPayload`, `PipelineStage`)
  - `Scheduler/src/scheduler/core/transport.py` (`BackpressuredStreamRouter`, `BackpressuredReceiver`)
  - `Scheduler/src/scheduler/core/engine.py` (`SchedulingEngine.schedule_split_inference_pipeline`)
  - `Scheduler/src/scheduler/api/openai.py` (`POST /v1/chat/completions`)
  - `Scheduler/tests/test_split_pipeline_scheduling.py`, `test_openai_split_inference.py`
- Documentation:
  - `docs/ROADMAP.md`
  - `Scheduler/docs/STATUS.md`
  - `Node/docs/STATUS.md`
  - `AGENTS.md`
