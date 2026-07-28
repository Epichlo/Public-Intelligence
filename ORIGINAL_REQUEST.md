# Original User Request

## Initial Request — 2026-07-26T18:21:27+05:30

Build the **Phase 4.5 Visual Control Plane & Interactive Web/Desktop Dashboard** for Public Intelligence. This encompasses a Host Contributor Dashboard with live node hardware telemetry, a Requester Playground with SSE streaming & OpenAI-compatible REST API Gateway (`/v1/chat/completions`), and a single-line host installation script.

Working directory: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence`
Integrity mode: development

## Requirements

### R1. Host Contributor Visual Dashboard
Build a modern, high-aesthetic web application inside the `website/` directory using Vite + React with Vanilla CSS. The dashboard must include:
- A clear "Start / Stop Host Node" toggle.
- Real-time telemetry gauges showing CPU utilization, RAM usage, VRAM consumption, and active P2P WAN connection state.
- Docker sandbox runtime health and log stream viewer.

### R2. Requester Playground & OpenAI-Compatible REST Gateway
- An interactive prompt playground (`/playground`) in the web UI supporting real-time Server-Sent Events (SSE) token generation streaming.
- An OpenAI-compatible REST API gateway endpoint (`POST /v1/chat/completions`) in the Scheduler service that translates standard OpenAI payload specs to `/api/v1/tasks/submit` ingress requests and returns OpenAI-formatted JSON/SSE stream responses.

### R3. One-Click Host Installer Script
- Create a standalone host node installer script (`install.sh`) that detects local GPU/VRAM hardware, verifies Docker/Python environment prerequisites, configures WAN P2P endpoints, and bootstraps the Node runtime.

## Acceptance Criteria

### Visual Control Plane & UI Polish
- [ ] Visual dashboard in `website/` builds cleanly (`npm run build`) and connects to live Scheduler telemetry APIs.
- [ ] Real-time telemetry gauges dynamically update CPU, RAM, and VRAM states.
- [ ] Toggling "Start Host Node" cleanly launches or stops the background node execution process.

### Requester Playground & OpenAI API Gateway
- [ ] Interactive `/playground` streams AI response tokens in real-time.
- [ ] `POST /v1/chat/completions` endpoint correctly handles non-streaming and streaming (`stream: true`) requests, authenticates via JWT, and returns OpenAI-compliant responses.
- [ ] Multi-tenant rate limiting (429) and auth errors display actionable feedback.

### Verification & Automated Testing
- [ ] Automated test suite verifies `/v1/chat/completions` endpoint translation, header validation, and error states in the Scheduler.
- [ ] Full project verification passes: `pytest`, `ruff check .`, `ruff format --check .`, and `mypy` across modified sub-repositories with zero failures.

## Follow-up — 2026-07-29T00:50:14+05:30

Implement the Phase 4.5 Visual Control Plane for Public Intelligence, featuring an interactive Requester Chat Playground (/playground), real-time global Node topology and telemetry dashboard, Host Node launcher status view, and OpenAI-compatible REST API Gateway.

Working directory: /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence
Integrity mode: development

## Requirements

### R1. Visual Control Plane & Host Node Telemetry Dashboard
Implement a web-based dashboard exposing real-time Node registration, live VRAM/CPU/RAM telemetry metrics (via AEAD encrypted telemetry feed over Zenoh), heartbeat health status, and global P2P WAN connection state.

### R2. Interactive Requester Chat Playground (/playground)
Build a responsive chat interface supporting real-time Server-Sent Events (SSE) token streaming from the Scheduler/Node inference backend, model selection, prompt submission, and token-generation latency metrics.

### R3. OpenAI-Compatible REST Gateway Router (/v1/chat/completions)
Expose an OpenAI-compatible REST endpoint (POST /v1/chat/completions) and task submission proxy (POST /api/v1/tasks/submit) with RS256 JWT authorization and token-bucket rate-limiting.

### R4. Host Node Installer & Hardware Auto-Discovery Harness
Provide single-command host node installation script (install.sh) and launch integration with automatic GPU/VRAM hardware discovery and Docker sandbox isolation guarantees.

## Acceptance Criteria

### Technical & System Invariants
- [ ] End-to-end integration test suite verifying node telemetry, SSE token streaming, and API task submission.
- [ ] Automated code quality verification passing 100% cleanly (pytest, ruff check ., ruff format --check ., mypy src).
- [ ] Documentation updated across docs/ROADMAP.md, Scheduler/docs/STATUS.md, Node/docs/STATUS.md, and execution log in AGENTS.md.

