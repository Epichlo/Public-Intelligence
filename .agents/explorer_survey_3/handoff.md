# Handoff Report — Explorer 3: Node Architecture, Host Controls & Installer Specification

## 1. Observation
- **Node Runtime Lifecycle (`Node/src/node/runtime.py`)**:
  - `Runtime.__init__` (lines 23–64) initializes `Settings`, `SchedulerClient`, `OllamaClient`, `ZenohHeartbeatClient`, `LocalDiskArtifactStore`, and `asyncio.Queue`.
  - `Runtime.start()` (lines 65–110) lists Ollama models, builds `NodeInfo`, registers with Scheduler via HTTP POST `/nodes/register`, starts `ZenohHeartbeatClient`, initializes `TelemetryEmitter` (AES-256-GCM encrypted metrics every 5.0s on `public-intelligence/net/nodes/{node_id}/telemetry`), and launches `_heartbeat_loop()` and `_worker_loop()`.
  - `Runtime.stop()` (lines 111–146) cancels worker/heartbeat background tasks, stops telemetry emitter, undeclares Zenoh liveliness token (`public-intelligence/net/liveliness/{node_id}`), and issues HTTP DELETE `/nodes/{node_id}` to Scheduler.
- **Client Interfaces (`Node/src/node/clients/`)**:
  - `zenoh_heartbeat.py` lines 37–65: Opens Zenoh session in client mode connecting to `zenoh_router_url`, `zenoh_peer_endpoints`, and `bootstrap_routers` (`tcp/bootstrap.public-intelligence.net:7447`). Configures gossip scouting (`scouting/gossip/enabled`).
  - `scheduler.py` lines 88–134: Issues HTTP requests (`/nodes/register`, `/heartbeat`, `/nodes/{node_id}`) with optional `X-Network-Auth-Token`.
  - `ollama.py` lines 33–83: Queries local Ollama server at `NODE_OLLAMA_HOST` for installed LLMs.
- **Core Systems & Sandbox Isolation (`Node/src/node/core/`)**:
  - `runtime.py` lines 183–270 (`WorktreeManager.execute_in_sandbox`): Spawns `docker run --rm -v {worktree_path}:/workspace -w /workspace --memory 512m --network none --user {uid}:{gid} python:3.11-slim` with 60s timeout.
  - `telemetry.py` lines 63–133: Scrapes CPU load via `os.getloadavg()` and RAM via macOS `sysctl`/`vm_stat` or Linux `/proc/meminfo`.
  - `configuration.py` lines 17–140: Defines Pydantic settings with `NODE_` prefix, handling JSON/comma-separated lists for `zenoh_peer_endpoints` and `bootstrap_routers`.
- **Hardware Telemetry Scraper (`Node/src/node/telemetry/`)**:
  - `collector.py` lines 61–94: Runs `nvidia-smi --query-gpu=name,utilization.gpu,memory.total,memory.free,memory.used --format=csv,noheader,nounits` to collect GPU name and VRAM bytes.
  - `heartbeat.py` lines 104–150: Registers SIGINT/SIGTERM handlers to broadcast `OFFLINE` deadman switch payload before exit.
- **Node API (`Node/src/node/api/inference.py`)**:
  - `GET /health/ready` (lines 184–215): Returns readiness status JSON containing `runtime`, `ollama`, `scheduler_registered`, `wan_connected`, `inference_ready`.
- **Systemd Unit Template (`Node/deploy/public-intelligence-node.service`)**:
  - Defines systemd daemon unit for Linux (`User=pi-node`, `ExecStart=uvicorn node.main:app`, `Restart=on-failure`).

## 2. Logic Chain
1. *Observation*: `Runtime.start()` registers the compute worker with the Scheduler via HTTP and opens a Zenoh P2P session in client mode while declaring a liveliness token. `Runtime.stop()` undeclares the token, sends an `OFFLINE` frame, and unregisters.
   *Reasoning*: Host Node Start/Stop controls on the dashboard can be driven by invoking system service management (`systemctl` / `launchctl`) or a host management proxy API, while monitoring node status via `GET /health/ready`.
2. *Observation*: `WorktreeManager.execute_in_sandbox()` executes isolation workloads inside Docker with `--memory 512m` and `--network none`. `TelemetryCollector` scrapes NVIDIA GPU metrics via `nvidia-smi` and RAM via `sysctl`/`/proc/meminfo`.
   *Reasoning*: Sandbox health can be verified via Docker socket responsiveness (`docker ping`) and active container inspection (`docker ps`), while live container stdout/stderr log streams can be exposed via SSE endpoints (`GET /api/sandbox/logs/stream`).
3. *Observation*: Hardware detection in `telemetry/collector.py` and `core/telemetry.py` relies on `nvidia-smi`, `sysctl`, `/proc/meminfo`, and PyTorch CUDA/MPS flags.
   *Reasoning*: The `install.sh` single-line host installer must perform systematic OS detection (Linux vs macOS), GPU/VRAM hardware detection (NVIDIA CUDA vs Apple Silicon UMA RAM vs CPU fallback), prerequisite checks (Python 3.10+, Docker, Git worktree, Ollama, Zenoh WAN), `.env` file generation, and system daemon bootstrap (`systemd` / `launchctl`).

## 3. Caveats
- Sandbox execution currently logs output after container execution finishes (`proc.communicate()`). Real-time log streaming requires attaching stream readers directly to the sub-process stdout/stderr streams.
- On macOS, Docker Desktop or Colima must be running for Docker sandbox execution to function.
- Apple Silicon Macs share unified RAM between CPU and GPU; VRAM capacity for Ollama/PyTorch MPS acceleration should be calculated as ~75% of total UMA RAM.

## 4. Conclusion
The Compute Node architecture (`Node/src/node/`) is clean, modular, and fully prepared for Phase 4.5 integration. Host Node Start/Stop controls can leverage `GET /health/ready` and OS service management (`systemctl`/`launchctl`), while `install.sh` can be implemented as a POSIX bash script following the detailed 6-step specification established in `survey_report.md`.

## 5. Verification Method
- **Survey Report Verification**:
  Inspect `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_survey_3/survey_report.md`.
- **Automated Test Verification**:
  Run `pytest Node/tests/` (78 passing assertions).
  Run `ruff check Node/` and `ruff format --check Node/`.
  Run `mypy Node/src`.
