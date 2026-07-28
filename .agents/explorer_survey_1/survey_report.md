# Phase 4.5 Architecture Survey Report: Host Contributor Dashboard & System Telemetry

**Date**: 2026-07-26  
**Author**: Explorer 1 (`explorer_survey_1`)  
**Target Scope**: `website/`, `Scheduler/`, `Node/`, root governance, Telemetry, Docker Sandbox, Start/Stop Node Controls  

---

## 1. Executive Summary

This survey provides a comprehensive audit of the Public Intelligence codebase to inform the design and implementation of **Phase 4.5: Visual Control Plane & Interactive Web/Desktop Dashboard**. 

Key Findings:
1. **Existing Web Stack**: `website/` exists as a complete **Next.js 16.2.10** application using **React 19.2.4**, **TypeScript 5**, **Tailwind CSS v4**, and **shadcn UI** components. Building the Visual Dashboard and Requester Playground within Next.js App Router (or configuring Vite) satisfies the `npm run build` requirement.
2. **Telemetry Data Pipeline**: `Node` collects local CPU, RAM, GPU, and VRAM utilization via `TelemetryEmitter` (`Node/src/node/core/telemetry.py`), encrypts it with AES-256-GCM / SHA-256 HMAC, and broadcasts it over Zenoh. `Scheduler` receives and decrypts telemetry in `ZenohRouter` (`Scheduler/src/scheduler/core/zenoh_router.py`) and populates `registry._telemetry`.
3. **Telemetry & Log API Gaps**: `Scheduler` lacks a REST API endpoint to expose `registry._telemetry` to web/external clients. `Node` lacks a REST endpoint for Docker sandbox log streaming and a local start/stop lifecycle management route.
4. **Integration Blueprint for R1 (Host Contributor Dashboard)**:
   - **Telemetry**: Expose `GET /nodes/{node_id}/telemetry` (or `GET /nodes/telemetry`) on Scheduler and `GET /api/v1/node/telemetry` on Node.
   - **Start/Stop Host Node Controls**: Implement local process lifecycle controller / REST route (`POST /api/v1/node/control`) coupled with `GET /health/ready` pulse check.
   - **Docker Sandbox Log Viewer**: Expose log buffer / SSE stream endpoint on Node (`GET /api/v1/sandbox/logs`) feeding `WorktreeManager.execute_in_sandbox` execution output to the web frontend terminal viewer.

---

## 2. Repository Structure & Build Environment Audit

### 2.1 Directory Overview
```
Public-Intelligence/
├── .agents/                      # Multi-agent metadata and execution logs
├── AGENTS.md                     # Operational governance standard and event log
├── ORIGINAL_REQUEST.md           # Phase 4.5 prompt specifications & acceptance criteria
├── Node/                         # Compute worker subsystem (FastAPI + Zenoh + Ollama)
├── Scheduler/                    # Network control plane (FastAPI + Raft + Zenoh Router)
├── docs/                         # Protocol specs, Architecture, Development Workflow, Roadmap
├── src/                          # Shared package modules
├── tests/                        # Subsystem test suites
└── website/                      # Frontend Web Application (Next.js 16 + React 19)
```

### 2.2 `website/` Technical Stack Breakdown
- **Location**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/website`
- **Package Manifest (`website/package.json`)**:
  - `next`: `16.2.10`
  - `react`: `19.2.4`
  - `react-dom`: `19.2.4`
  - `typescript`: `^5`
  - `@tailwindcss/postcss` & `tailwindcss`: `^4`
  - `clsx` & `tailwind-merge`: `^2.1.1` / `^3.6.0`
  - `shadcn`: `^4.13.0`
- **Build Scripts**:
  - `npm run dev`: Starts `next dev`
  - `npm run build`: Executes `next build`
  - `npm run start`: Starts `next start`
  - `npm run lint`: Executes `eslint`
- **App Router Layout (`website/src/app`)**:
  - Main landing: `/` (`app/page.tsx`)
  - Sub-pages: `/architecture`, `/contribute`, `/research`, `/roadmap`, `/status`, `/vision`
  - Components: `architecture-diagram.tsx`, `system-diagram.tsx`, `logo.tsx`, `page-header.tsx`, etc.
- **Specification vs Existing Alignments**:
  While `ORIGINAL_REQUEST.md` mentions "Vite + React with Vanilla CSS", the codebase already has an existing Next.js 16 / React 19 App Router setup with Tailwind CSS. Implementing the Visual Dashboard (`/dashboard`) and Requester Playground (`/playground`) inside Next.js preserves existing pages, reuses UI components, and ensures `npm run build` succeeds cleanly.

---

## 3. Node Telemetry & Scheduler API Analysis

### 3.1 Node Telemetry Generation & Transport
1. **Local Metrics Collection**:
   - Location: `Node/src/node/core/telemetry.py`
   - Class: `TelemetryEmitter` (runs background loop every 5 seconds).
   - Collected metrics:
     - `cpu_utilization`: Retrieved via `os.getloadavg()` (or sysctl fallback on macOS).
     - `ram_usage_bytes`: Retrieved via `vm_stat` (macOS) or `/proc/meminfo` (Linux).
     - `gpu_utilization`: Initialized to `0.0` (placeholder for accelerator hooks).
     - `vram_usage_bytes`: Initialized to `0` (placeholder for accelerator hooks).
2. **Encryption & Authentication**:
   - Encrypted using AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
   - Signed using SHA-256 HMAC digest with key derived from `TELEMETRY_SECRET_KEY`.
   - Formatted into envelope `{"iv": iv_b64, "ciphertext": ciphertext_b64, "signature": sig}`.
   - Published over Zenoh to topic `public-intelligence/net/nodes/<node_id>/telemetry`.

### 3.2 Scheduler Telemetry Processing & In-Memory Storage
1. **Zenoh Telemetry Subscriber**:
   - Location: `Scheduler/src/scheduler/core/zenoh_router.py` (lines 93–95, 209–337).
   - Subscribes to `public-intelligence/net/nodes/*/telemetry`.
   - Decrypts envelope, verifies SHA-256 HMAC signature against `TELEMETRY_SECRET_KEY`.
   - Checks timestamp staleness ($\Delta t$ must be within $-10\text{s} \le \text{age} \le 30\text{s}$).
   - Updates `registry._telemetry[node_id] = data`.
2. **Node Registry Storage**:
   - Location: `Scheduler/src/scheduler/registry/node_registry.py` (line 24, 69, 130, 215).
   - In-memory dictionary `self._telemetry: dict[str, Any]` stores hardware metrics per `node_id`.

### 3.3 Existing REST Endpoint Matrix

#### Scheduler REST APIs (`Scheduler/src/scheduler/api/`)
| Method | Route | File | Auth | Purpose |
|---|---|---|---|---|
| `GET` | `/health` | `health.py` | None | Control plane liveness check |
| `POST` | `/nodes/register` | `nodes.py` | Token | Node registration with `NodeInfo` |
| `GET` | `/nodes` | `nodes.py` | None | List registered nodes |
| `GET` | `/nodes/{node_id}` | `nodes.py` | None | Get specific registered node info |
| `DELETE` | `/nodes/{node_id}` | `nodes.py` | Token | Gracefully unregister node |
| `POST` | `/heartbeat` | `heartbeat.py` | None | Send HTTP heartbeat |
| `GET` | `/heartbeat/{node_id}` | `heartbeat.py` | None | Retrieve latest HTTP heartbeat |
| `POST` | `/schedule` | `schedule.py` | None | Execute capability matchmaker |
| `POST` | `/api/v1/tasks/submit` | `ingress.py` | RS256 JWT | Multi-tenant ingress task gateway |

#### Node REST APIs (`Node/src/node/api/` & `main.py`)
| Method | Route | File | Auth | Purpose |
|---|---|---|---|---|
| `POST` | `/infer` | `inference.py` | None | Model generation, Radix prefix cache, SSE streaming |
| `GET` | `/models` | `inference.py` | None | List available hosted Ollama models |
| `GET` | `/health` | `inference.py` | None | Check Node & Ollama liveness |
| `GET` | `/health/ready` | `inference.py` | None | Check Node readiness, registration, `wan_connected` |

### 3.4 API Gaps & Missing Endpoints
1. **Scheduler Telemetry Endpoint Gap**: `Scheduler` has no REST route to query telemetry (`registry._telemetry`). A `GET /nodes/{node_id}/telemetry` endpoint is missing.
2. **Node Local Telemetry Endpoint Gap**: `Node` lacks an explicit REST endpoint returning hardware telemetry (`cpu_utilization`, `ram_usage_bytes`, `gpu_utilization`, `vram_usage_bytes`) formatted for UI gauges.
3. **Start / Stop Host Node Controls Gap**: Neither `Node` nor `Scheduler` currently exposes an administrative endpoint to start/stop the host node runtime process programmatically from the web UI.
4. **Docker Sandbox Log Stream Gap**: `WorktreeManager.execute_in_sandbox()` executes commands in isolated Docker containers, but stdout/stderr logs are not exposed via any REST/SSE log streaming endpoint.

---

## 4. Integration Blueprint for R1 (Host Contributor Visual Dashboard)

To realize **R1. Host Contributor Visual Dashboard** inside `website/`:

### 4.1 Telemetry Connection Architecture
- **Local Host Dashboard View**:
  The R1 Dashboard inside `website/` can query `http://localhost:8000/health/ready` and a newly added `GET /api/v1/node/telemetry` endpoint on the local Node.
  - **Gauge Indicators**:
    - **CPU Utilization**: Percentage (0–100%)
    - **RAM Usage**: Used vs Total GB
    - **VRAM Consumption**: Used vs Total GB
    - **P2P WAN Connection State**: Derived from `wan_connected` boolean in `/health/ready`.
- **Global Control Plane Telemetry View**:
  The Scheduler will expose `GET /nodes/{node_id}/telemetry` or `GET /nodes/telemetry`, allowing the Web Dashboard to display global cluster node metrics.

### 4.2 Start / Stop Host Node Controls
- **Mechanics**:
  1. Add a local Node management API endpoint or Next.js server route (`/api/node/control`) that controls the Node process state.
  2. When "Start Host Node" is toggled ON: spawns background Node runtime process (or sends start signal to service manager) and polls `http://localhost:8000/health/ready` until `status: "ready"`.
  3. When "Stop Host Node" is toggled OFF: sends graceful stop command (`POST /api/v1/node/stop` or SIGTERM to Node process), calling `runtime.stop()` to unregister from Scheduler and release Zenoh channels.

### 4.3 Docker Sandbox Health & Log Viewer
- **Mechanics**:
  1. Extend `WorktreeManager` / Node runtime to maintain an in-memory ring buffer (e.g. last 1,000 log lines) of sandboxed container executions.
  2. Expose `GET /api/v1/sandbox/logs` (JSON) and `GET /api/v1/sandbox/logs/stream` (SSE text/event-stream) on Node API.
  3. Build a high-aesthetic terminal log viewer component in `website/` (`components/sandbox-log-viewer.tsx`) that subscribes to the SSE log stream.

---

## 5. Next Steps & Recommendations for Sub-Agents

1. **Architect**:
   - Finalize REST API schemas for `GET /nodes/{node_id}/telemetry` (Scheduler) and `GET /api/v1/node/telemetry` & `GET /api/v1/sandbox/logs` (Node).
   - Design `/v1/chat/completions` translation spec in Scheduler (mapping OpenAI format $\rightarrow$ `/api/v1/tasks/submit` ingress requests).
2. **Coder**:
   - Build Host Contributor Dashboard UI (`website/src/app/dashboard/page.tsx` or `/contribute`) with gauges, Start/Stop toggle, and Sandbox log viewer.
   - Implement `POST /v1/chat/completions` in Scheduler and `/playground` UI in `website/`.
   - Create single-line `install.sh` installer script.
3. **Verifier / Auditor**:
   - Verify `npm run build` in `website/`.
   - Verify `pytest`, `ruff`, and `mypy` across `Scheduler/` and `Node/`.
