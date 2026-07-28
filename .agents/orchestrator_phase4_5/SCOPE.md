# Project: Public Intelligence Phase 4.5 — Visual Control Plane & Interactive Dashboard

## Architecture
Public Intelligence Phase 4.5 builds the Visual Control Plane and Developer/Host Experience layer on top of the decentralized P2P compute network established in Phase 4.

```
+-----------------------------------------------------------------------------------+
| website/ (Next.js 16 + React 19 + Tailwind CSS v4)                                |
|                                                                                   |
|  +-------------------------------------+  +------------------------------------+  |
|  | /dashboard (Host Contributor UI)    |  | /playground (Requester Prompt UI)  |  |
|  | - Start/Stop Node Toggle            |  | - Real-time SSE Token Streaming    |  |
|  | - Telemetry Gauges (CPU/RAM/VRAM)   |  | - System Prompt & Temperature      |  |
|  | - Sandbox Log Viewer                |  | - Auth Token / JWT Input           |  |
|  +------------------+------------------+  +-----------------+------------------+  |
+---------------------|---------------------------------------|---------------------+
                      | HTTP/REST / SSE                       | HTTP REST / SSE
                      v                                       v
+----------------------------------------+  +---------------------------------------+
| Node Local Control API (Node/)         |  | Scheduler OpenAI Gateway (Scheduler/) |
| - GET /api/v1/node/telemetry           |  | - POST /v1/chat/completions           |
| - POST /api/v1/node/control            |  |   (RS256 Auth, Rate Limiter 429, SSE) |
| - GET /api/v1/sandbox/logs/stream      |  | - GET /v1/models                      |
| - Docker Sandbox Worktree Runtime      |  | - GET /nodes/{node_id}/telemetry      |
+----------------------------------------+  +---------------------------------------+
                      ^                                       ^
                      |               Zenoh P2P Network       |
                      +---------------------------------------+
```

---

## Feature Inventory

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Scheduler OpenAI Gateway Models | Pydantic data schemas for OpenAI Chat Completions and Models requests/responses | M1 | R2 |
| F2 | `POST /v1/chat/completions` Endpoint | OpenAI-compatible completion endpoint supporting JSON & SSE streaming (`stream: true`), RS256 JWT auth, and TokenBucket rate limiting (429) | M1 | R2 |
| F3 | `GET /v1/models` Endpoint | Aggregate model discovery endpoint listing active models from registered nodes | M1 | R2 |
| F4 | Scheduler Telemetry API | `GET /nodes/{node_id}/telemetry` REST endpoint exposing decrypted telemetry metrics | M1 | R1 |
| F5 | Scheduler CORS & App Wireup | Add CORSMiddleware to `main.py` allowing cross-origin web client calls | M1 | R1/R2 |
| F6 | Node Local Telemetry API | `GET /api/v1/node/telemetry` exposing CPU, RAM, GPU, VRAM, and P2P connection state | M2 | R1 |
| F7 | Node Host Control API | `POST /api/v1/node/control` enabling start/stop of node execution runtime | M2 | R1 |
| F8 | Sandbox Log Stream API | `GET /api/v1/sandbox/logs` & SSE endpoint yielding Docker container execution logs | M2 | R1 |
| F9 | Host Contributor Dashboard UI | `/dashboard` page inside `website/` with Start/Stop toggle, telemetry gauges, and log viewer | M3 | R1 |
| F10 | Requester Playground UI | `/playground` page inside `website/` with interactive prompt runner & SSE token streaming | M3 | R2 |
| F11 | Next.js API Proxy Routes | API proxy endpoints in `website/src/app/api/` forwarding to Scheduler & Node services | M3 | R1/R2 |
| F12 | One-Click Installer (`install.sh`) | Single-line POSIX installer detecting hardware, checking prerequisites, configuring WAN P2P, and bootstrapping node service | M4 | R3 |
| F13 | Daemon Launcher & Node CLI | Launch script `scripts/launch_host_node.sh` and CLI entry point `public-intelligence-node` | M4 | R3 |
| F14 | End-to-End Integration Test Suite | System-wide E2E integration tests in `tests/test_phase4_5_e2e.py` verifying full telemetry, SSE streaming, and API gateway translation | M5 | R5 |
| F15 | Documentation & Governance Ledger | Synchronize `/docs/ROADMAP.md`, `Scheduler/docs/STATUS.md`, `Node/docs/STATUS.md`, and `AGENTS.md` | M5 | Governance |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Scheduler OpenAI Gateway & Telemetry Endpoints | Implement `scheduler/models/openai.py`, `scheduler/api/openai.py`, `scheduler/api/telemetry.py`, and wire CORS in `main.py` | None | DONE |
| M2 | Node Local Telemetry, Host Control & Sandbox Log APIs | Implement `node/api/control.py`, sandbox log ring buffer, and local telemetry REST endpoints | None | DONE |
| M3 | Host Dashboard & Requester Playground Web UI | Implement `/dashboard` and `/playground` pages, components, and proxy API routes in `website/` | M1, M2 | IN_PROGRESS |
| M4 | One-Click Host Installer & Launch Harness | Implement POSIX `install.sh` script, `scripts/launch_host_node.sh`, and CLI entry point | M2 | IN_PROGRESS |
| M5 | E2E Testing, Documentation & Governance Sync | Full closed-loop verification (`pytest`, `ruff`, `mypy`, `npm run build`), E2E test suite, status updates, and AGENTS.md log entry | M1, M2, M3, M4 | PLANNED |

---

## Interface Contracts

### 1. OpenAI Chat Completion Gateway Contract (`POST /v1/chat/completions`)
- **Headers**:
  - `Authorization: Bearer <RS256_JWT>`
  - `Content-Type: application/json`
- **Request Body**:
  ```json
  {
    "model": "llama3",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello!"}
    ],
    "stream": false,
    "temperature": 0.7
  }
  ```
- **Response (Non-streaming, `stream: false`)**: `200 OK`, JSON matching OpenAI `chat.completion`.
- **Response (Streaming, `stream: true`)**: `200 OK`, `Content-Type: text/event-stream` yielding SSE chunks (`data: {...}\n\n`) terminating with `data: [DONE]\n\n`.
- **Error Responses**:
  - `401 Unauthorized`: Invalid or missing JWT.
  - `429 Too Many Requests`: `{"detail": "Rate limit exceeded. Multi-tenant quota exhausted."}`

### 2. Node Local Telemetry & Control Contract
- `GET /api/v1/node/telemetry`: Returns `NodeTelemetryResponse` JSON.
- `POST /api/v1/node/control`: Request `{"action": "start" | "stop"}`, Response `{"status": "ok", "action": "start", "runtime_running": true}`.

### 3. Docker Sandbox Log Streaming Contract
- `GET /api/v1/sandbox/logs`: Returns recent log entries JSON `{"logs": ["line 1", "line 2"]}`.
- `GET /api/v1/sandbox/logs/stream`: `text/event-stream` yielding SSE log lines.

---

## Code Layout

### Scheduler (`Scheduler/src/scheduler/`)
- `models/openai.py`: Pydantic schemas for OpenAI API requests/responses.
- `api/openai.py`: FastAPI router for `/v1/chat/completions`, `/v1/models`.
- `api/telemetry.py`: FastAPI router for `/nodes/{node_id}/telemetry`.
- `main.py`: CORS middleware and router inclusion.

### Node (`Node/src/node/`)
- `api/control.py`: FastAPI router for `/api/v1/node/telemetry`, `/api/v1/node/control`, `/api/v1/sandbox/logs`.
- `core/runtime.py`: Extended log buffer integration for Docker sandbox executions.

### Website (`website/src/`)
- `app/dashboard/page.tsx`: Host Contributor Dashboard page.
- `app/playground/page.tsx`: Requester Prompt Playground page.
- `app/api/`: Next.js API proxy routes for backend services.
- `components/`: UI components for gauges, control toggle, log viewer, and chat playground.

### Root (`/`)
- `install.sh`: One-click host node installation script.
- `scripts/launch_host_node.sh`: Host node daemon launcher script.
- `tests/test_phase4_5_e2e.py`: End-to-end integration test suite.
