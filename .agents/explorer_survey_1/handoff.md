# Handoff Report: Phase 4.5 Repository Survey & System Architecture Audit

**Agent**: Explorer 1 (`explorer_survey_1`)  
**Date**: 2026-07-26  
**Working Directory**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_survey_1`  

---

## 1. Observation

1. **Repository Structure**:
   - `website/package.json`: Lines 11–28 list Next.js `16.2.10`, React `19.2.4`, React DOM `19.2.4`, Tailwind CSS `^4`, `clsx`, `tailwind-merge`, and `shadcn ^4.13.0`.
   - `website/src/app`: Directory contains `layout.tsx`, `page.tsx`, `globals.css`, and route folders `architecture/`, `contribute/`, `research/`, `roadmap/`, `status/`, `vision/`.
   - Build script in `website/package.json`: Line 7 shows `"build": "next build"`.

2. **Node Telemetry System**:
   - `Node/src/node/core/telemetry.py`: Lines 135–155 define `TelemetryEmitter` running every 5.0 seconds. Lines 63–132 retrieve system CPU utilization and RAM usage. Lines 181–188 construct metrics object `{node_id, timestamp, cpu_utilization, ram_usage_bytes, gpu_utilization, vram_usage_bytes}`. Lines 48–60 encrypt with AES-256-GCM and sign with SHA-256 HMAC.
   - `Node/src/node/api/inference.py`: Lines 184–215 define `GET /health/ready` endpoint returning `status`, `runtime`, `ollama`, `scheduler_registered`, `wan_connected`, `inference_ready`.

3. **Scheduler Telemetry & Ingress System**:
   - `Scheduler/src/scheduler/core/zenoh_router.py`: Lines 209–337 define `_on_telemetry` and `_process_telemetry`, which decrypt Zenoh telemetry, verify HMAC signature, validate timestamp staleness, and map metrics to `self.registry._telemetry[node_id]`.
   - `Scheduler/src/scheduler/registry/node_registry.py`: Lines 24, 69, 130, 215 manage `self._telemetry: dict[str, Any]`.
   - `Scheduler/src/scheduler/api/nodes.py`: Lines 23–84 define `POST /nodes/register`, `GET /nodes`, `GET /nodes/{node_id}`, `DELETE /nodes/{node_id}`. No GET telemetry route exists.
   - `Scheduler/src/scheduler/api/ingress.py`: Lines 77–158 define `POST /api/v1/tasks/submit` with RS256 JWT auth (`verify_jwt`), token bucket rate limiting (`TokenBucketLimiter`), two-stage capability matching (`SchedulingEngine.schedule_task`), and Raft consensus commitment (`RaftConsensusEngine.propose`).

4. **Docker Sandbox Execution**:
   - `Node/src/node/core/runtime.py`: Lines 183–270 define `WorktreeManager.execute_in_sandbox(branch_name, command, image)`, mounting worktree at `/workspace`, enforcing 512MB RAM limit, no network, and 60s timeout.

---

## 2. Logic Chain

1. **Observation 1** demonstrates that `website/` is an active Next.js 16 / React 19 App Router project. Building R1 (Host Contributor Dashboard) and R2 (Requester Playground) as React components within `website/src/app` will allow `npm run build` to execute cleanly without introducing conflicting build toolchains.
2. **Observation 2** shows that `Node` already collects CPU and RAM utilization metrics locally and checks WAN connectivity (`wan_connected` in `/health/ready`). However, VRAM and GPU utilization metrics are currently placeholders (`0.0` / `0`), and there is no direct REST endpoint returning a clean JSON telemetry payload for the local host UI.
3. **Observation 3** shows that `Scheduler` decrypts and stores incoming node telemetry in `registry._telemetry[node_id]`, but `Scheduler/src/scheduler/api/nodes.py` does not expose a GET endpoint for this data. Therefore, an endpoint `GET /nodes/{node_id}/telemetry` (or `GET /nodes/telemetry`) must be added to Scheduler for control plane monitoring.
4. **Observation 4** indicates that while `WorktreeManager` runs Docker sandbox containers, stdout/stderr execution logs are returned only synchronously per execution and not retained in a streaming log buffer. To support the R1 Docker sandbox log viewer, an in-memory log buffer and SSE/JSON log stream endpoint (`GET /api/v1/sandbox/logs`) must be added to Node.

---

## 3. Caveats

1. **Vite vs Next.js Governance**: `ORIGINAL_REQUEST.md` mentions Vite + React with Vanilla CSS in text, but `website/` was previously scaffolded as a Next.js App Router project with Tailwind CSS. Re-architecting `website/` to Vite would wipe out all existing pages (`/architecture`, `/research`, `/vision`, etc.). Using Next.js App Router for R1 and R2 preserves the existing repository structure and fulfills the `npm run build` acceptance criteria.
2. **Hardware Acceleration Hooks**: `get_cpu_utilization()` and `get_ram_usage_bytes()` in `Node/src/node/core/telemetry.py` work on macOS/Linux hosts, but GPU/VRAM telemetry requires `nvidia-smi` / PyTorch / Metal subprocess hooks for non-zero metrics on systems with physical GPUs.

---

## 4. Conclusion

The repository is well-architected and ready for Phase 4.5 implementation:
- **`website/`**: Next.js 16 / React 19 web app ready for `/dashboard` (R1) and `/playground` (R2) route additions.
- **Scheduler**: Robust FastAPI + Raft + Zenoh router base. Needs `POST /v1/chat/completions` (OpenAI gateway translation) and `GET /nodes/{node_id}/telemetry`.
- **Node**: Fast API + Ollama + Zenoh runtime. Needs `GET /api/v1/node/telemetry`, `GET /api/v1/sandbox/logs`, and local start/stop lifecycle management.

---

## 5. Verification Method

1. **Verify Web Application**:
   - Run `npm run build` inside `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/website`.
2. **Verify Python Subsystems**:
   - Run `pytest` across `Scheduler/` and `Node/`.
   - Run `ruff check .`, `ruff format --check .`, and `mypy` across `Scheduler/` and `Node/`.
3. **Verify Documentation**:
   - Inspect `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_survey_1/survey_report.md` and `handoff.md`.
