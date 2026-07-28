# Milestone 3 Implementation Report: Host Dashboard, Playground & API Proxies

**Author**: `worker_m3` (teamwork_preview_worker)  
**Date**: 2026-07-29  
**Subsystem**: `website/` (Next.js 16 + React 19 + Tailwind CSS v4)

---

## 1. Summary of Work Implemented

Milestone 3 has been fully implemented in `website/` without shortcuts or facades:

### R1. Host Contributor Telemetry Dashboard (`/dashboard`)
1. **Node Control Toggle** (`website/src/components/node-control-toggle.tsx`):
   - Interactive control component to start or stop the background host node execution runtime via POST `/api/node/control`.
   - Displays real-time status badges (`ACTIVE RUNTIME`, `STOPPED`, `UNREACHABLE`), action pending loading spinner, node ID readout, and error notifications.
2. **Real-time Telemetry Gauges** (`website/src/components/telemetry-gauge.tsx`):
   - **Hardware Gauges**: CPU utilization %, System RAM memory (Used/Total GB + %), GPU VRAM memory (Used/Total GB + %).
   - **AEAD Telemetry Guard Badge**: Cryptographic integrity status (`AES-256-GCM`), SHA-256 HMAC signature verification (`VERIFIED`), staleness boundary ($\Delta t \le 30.0\text{s}$), payload frame counter.
   - **Heartbeat Health Indicator**: Pulse vitality status (`Healthy (< 5s)`, `Lagging (< 15s)`, `Stale Evicted (> 15s)`), pulse delta $\Delta t$, dynamic herd dampening state.
   - **Global P2P WAN Connection State**: Connection status (`Connected (P2P Mesh)` / `Disconnected`), transport mode (`Zenoh / SharedMem IPC`), gossip scouting (`ENABLED`), flow control state.
3. **Docker Sandbox Log Viewer** (`website/src/components/sandbox-log-viewer.tsx`):
   - Real-time dark terminal UI connected to SSE stream endpoint `/api/sandbox/logs/stream`.
   - Live stream indicator pill, stream filtering (`All`, `STDOUT`, `STDERR`), keyword search filter, auto-scroll toggle, clear history button, and Docker container sandbox isolation specs summary.
4. **Dashboard Page Shell** (`website/src/app/dashboard/page.tsx`):
   - Assembles the dashboard components into a responsive dark layout with automated 2.5s polling.

### R2. Interactive Requester Chat Playground (`/playground`)
1. **Real-time SSE Token Streaming Chat Interface** (`website/src/app/playground/page.tsx` & `website/src/components/playground/`):
   - `chat-messages.tsx`: Conversation thread rendering system notes, user bubbles, and real-time streaming assistant token responses with blinking cursor (`▋`). Supports message copying and clearing conversation history.
   - `prompt-input.tsx`: Resizable textarea with `Enter` submit / `Shift+Enter` newline, "Submit Prompt", and "Stop Generation" (aborts `AbortController`).
2. **Model Selector & Parameter Controls**:
   - `model-selector.tsx`: Dynamically fetches available models from `/api/models`.
   - `playground-controls.tsx`: Interactive sliders/inputs for Temperature (0.0 - 2.0), Top-P (0.0 - 1.0), Max Tokens (64 - 4096), System Prompt editor, and custom RS256 Bearer JWT token header input.
3. **Latency Metrics Telemetry Card** (`website/src/components/playground/latency-metrics-card.tsx`):
   - Real-time readouts for **TTFT (Time To First Token in ms)**, **Generation Speed (tokens/sec)**, **Total Elapsed Duration (seconds)**, Prompt token count, Completion token count, and Total tokens.
4. **Error & Rate-Limit Alert Banner** (`website/src/components/playground/error-rate-limit-banner.tsx`):
   - Handles HTTP 429 (`Multi-Tenant Rate Limit Exceeded: 5 burst / 1 token per 2s`), HTTP 401 (`Unauthorized: Invalid RS256 JWT`), HTTP 503 (`Compute Node Unavailable`), and network errors with actionable guidance.

### R3. Next.js API Proxy Routes (`website/src/app/api/`)
1. `/api/chat/completions/route.ts`: Proxies POST to Scheduler `http://localhost:8000/v1/chat/completions` (supporting SSE `text/event-stream` body forwarding).
2. `/api/models/route.ts`: Proxies GET to Scheduler `http://localhost:8000/v1/models`.
3. `/api/node/telemetry/route.ts`: Proxies GET to Node `http://localhost:8080/api/v1/node/telemetry`.
4. `/api/node/control/route.ts`: Proxies POST to Node `http://localhost:8080/api/v1/node/control`.
5. `/api/sandbox/logs/stream/route.ts`: Proxies GET SSE stream to Node `http://localhost:8080/api/v1/sandbox/logs/stream`.
6. `/api/telemetry/all/route.ts`: Proxies GET to Scheduler `http://localhost:8000/nodes/telemetry`.

### R4. Header Navigation Update
- Updated `website/src/components/site-navigation.ts` to include `/playground` ("Playground") and `/dashboard` ("Dashboard") links in the primary navigation header.

---

## 2. File Modification & Creation Log

| File Path | Description | Status |
| :--- | :--- | :--- |
| `website/src/app/api/chat/completions/route.ts` | Next.js API proxy for `/v1/chat/completions` (SSE streaming) | Created |
| `website/src/app/api/models/route.ts` | Next.js API proxy for `/v1/models` | Created |
| `website/src/app/api/node/telemetry/route.ts` | Next.js API proxy for `/api/v1/node/telemetry` | Created |
| `website/src/app/api/node/control/route.ts` | Next.js API proxy for `/api/v1/node/control` | Created |
| `website/src/app/api/sandbox/logs/stream/route.ts` | Next.js API proxy for `/api/v1/sandbox/logs/stream` (SSE stream) | Created |
| `website/src/app/api/telemetry/all/route.ts` | Next.js API proxy for `/nodes/telemetry` | Created |
| `website/src/components/node-control-toggle.tsx` | Host node start/stop control toggle component | Created |
| `website/src/components/telemetry-gauge.tsx` | Telemetry gauges (CPU, RAM, VRAM, AEAD, Heartbeat, WAN) | Created |
| `website/src/components/sandbox-log-viewer.tsx` | Docker sandbox SSE log streaming terminal | Created |
| `website/src/app/dashboard/page.tsx` | Host Contributor Telemetry Dashboard page | Created |
| `website/src/components/playground/model-selector.tsx` | Model selector dropdown fetching `/api/models` | Created |
| `website/src/components/playground/latency-metrics-card.tsx` | Inference TTFT, t/s speed, elapsed time metrics card | Created |
| `website/src/components/playground/error-rate-limit-banner.tsx` | Rate-limit (429) & error notification banner | Created |
| `website/src/components/playground/playground-controls.tsx` | Temperature, Top_P, Max Tokens, System Prompt & JWT Auth controls | Created |
| `website/src/components/playground/chat-messages.tsx` | Chat thread rendering & real-time token streaming with cursor | Created |
| `website/src/components/playground/prompt-input.tsx` | Prompt textarea input with Submit & Stop buttons | Created |
| `website/src/app/playground/page.tsx` | Interactive Requester Chat Playground page | Created |
| `website/src/components/site-navigation.ts` | Updated navigation menu links | Modified |

---

## 3. Verification & Automated Test Results

1. **Next.js Build Check**:
   - Command: `cd website && npm run build`
   - Result: **Passed (0 errors)**. 19 static/dynamic pages and routes compiled cleanly with 0 TypeScript errors.

2. **Frontend Linter Check**:
   - Command: `cd website && npm run lint`
   - Result: **Passed (0 errors)**. All React 19 compiler rules (`react-hooks/purity`, `react-hooks/set-state-in-effect`, `react-hooks/exhaustive-deps`) passed cleanly.

3. **Backend Integration Regression Check**:
   - `Scheduler` PyTest: **111 passed** in 7.10s.
   - `Node` PyTest: **117 passed, 1 skipped** in 2.05s.
