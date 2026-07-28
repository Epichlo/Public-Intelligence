# Handoff Report: Host Installer, Sandbox Isolation & E2E Integration Test Suite (R4 & R5)

## 1. Observation
1. **Existing Codebase & File Structure**:
   - `Node/src/node/telemetry/collector.py`: Lines 20–46 define `TelemetryCollector.collect()` using `psutil` and `_collect_gpu_metrics()`. Lines 61–94 call `nvidia-smi --query-gpu=name,utilization.gpu,memory.total,memory.free,memory.used --format=csv,noheader,nounits`.
   - `Node/src/node/core/telemetry.py`: Lines 63–132 implement `get_cpu_utilization()` and `get_ram_usage_bytes()`. Line 88 calls `sysctl -n hw.memsize` and `vm_stat` on macOS (`darwin`); Line 108 reads `/proc/meminfo` on Linux. Lines 135–204 implement `TelemetryEmitter` running an encrypted loop every 5s using AES-256-GCM and SHA-256 HMAC.
   - `Node/src/node/core/runtime.py`: Lines 67–352 implement `WorktreeManager`. Line 267 (`execute_in_sandbox`) constructs Docker execution flags: `-v {worktree}:/workspace`, `-w /workspace`, `--memory 512m`, `--network none`, `--user {uid}:{gid}` (if non-root), and hard timeout of 60s. Lines 18–64 implement `SandboxLogBuffer` ring buffer (max 1000 entries).
   - `Node/src/node/api/control.py`: Lines 46–86 (`/api/v1/node/telemetry`), Lines 89–124 (`/api/v1/node/control`), Lines 126–140 (`/api/v1/sandbox/logs`), and Lines 142–186 (`/api/v1/sandbox/logs/stream`) expose host control and SSE sandbox log streaming.
   - `Scheduler/src/scheduler/api/openai.py`: Lines 62–330 implement `/v1/chat/completions` supporting non-streaming and streaming (`stream: true`) SSE responses, JWT authorization (`verify_jwt`), token bucket rate limiting (`TokenBucketLimiter`), node matchmaking, and Raft consensus proposals.
   - `Node/pyproject.toml` & `Scheduler/pyproject.toml`: Pytest test suites run cleanly across both sub-projects.

2. **Test Command Results**:
   - Node tests: `PYTHONPATH=Node/src:Scheduler/src ./Node/.venv/bin/pytest Node/tests` $\rightarrow$ **112 passed, 1 skipped in 1.53s**.
   - Scheduler tests: `./.venv/bin/pytest` in `Scheduler/` $\rightarrow$ **111 passed in 12.62s**.
   - Total test suite count: **223 passed tests** across Node and Scheduler.

## 2. Logic Chain
1. **Observation 1 (Hardware & Prerequisites Discovery)**: Hardware scrapers in `Node/src/node/telemetry/collector.py` and `Node/src/node/core/telemetry.py` demonstrate system call commands for macOS (`sysctl -n hw.memsize`, `system_profiler`) and Linux (`nvidia-smi`, `/proc/meminfo`, `nproc`). Therefore, `install.sh` can cleanly orchestrate these platform checks, verify Python >=3.10, Git, and Docker runtime daemon availability, and dynamically generate `Node/.env` configurations.
2. **Observation 1 & 2 (Node CLI & Control API)**: `Node/src/node/api/control.py` exposes `/api/v1/node/control` (`start`/`stop`) and `/api/v1/sandbox/logs/stream`. Adding a CLI entry point `public-intelligence-node` in `Node/pyproject.toml` and background daemon launch harness `scripts/launch_host_node.sh` bridges host shell management with the visual web control plane.
3. **Observation 1 (Docker Sandbox Isolation)**: `WorktreeManager.execute_in_sandbox()` in `Node/src/node/core/runtime.py` already enforces workspace volume mounting, 512MB RAM ceiling, air-gapped `none` network, non-root uid/gid, 60s hard process timeout, and ring-buffer log capture into `SandboxLogBuffer`.
4. **Observation 1 & 2 (E2E Test Strategy)**: Testing `/v1/chat/completions` (Scheduler), `/api/v1/node/telemetry` (Node), encrypted telemetry emission over Zenoh, and task submission proxy across Scheduler and Node completes closed-loop validation of R4 and R5 requirements.

## 3. Caveats
- Host GPUs using AMD ROCm on Linux require `rocm-smi` or `rocminfo` binaries; fallback is provided via Python `torch.cuda.is_available()`.
- Docker execution requires active Docker Desktop or `dockerd` service running on the host system.

## 4. Conclusion
The architecture and implementation specifications for Requirements **R4** (Host Installer Script, Hardware Discovery, Docker Sandbox Isolation) and **R5** (End-to-End Integration Test Suite) are fully defined and ready for execution by CODER sub-agents.

## 5. Verification Method
1. Inspect technical analysis report:
   `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_3/analysis.md`
2. Run pytest verification suites:
   - Node: `PYTHONPATH=Node/src:Scheduler/src ./Node/.venv/bin/pytest Node/tests`
   - Scheduler: `cd Scheduler && ./.venv/bin/pytest`
3. Invalidation conditions: Any test failure or unhandled hardware platform error.
