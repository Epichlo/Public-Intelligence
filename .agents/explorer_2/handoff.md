# Handoff Report: R1 & R2 Frontend Architecture Analysis

**Author**: `explorer_2` (teamwork_preview_explorer)  
**Recipient**: `parent` (Orchestrator conversation ID: `e436f93a-97e7-4b41-88fd-47b47b3f8097`)  
**Date**: 2026-07-29  
**Working Directory**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_2`

---

## 1. Observation

1. **Website Framework & Environment**:
   - `website/package.json`: Next.js `16.2.10`, React `19.2.4`, Tailwind CSS `v4`, TypeScript `^5`.
   - Existing pages: `page.tsx`, `vision/page.tsx`, `architecture/page.tsx`, `research/page.tsx`, `roadmap/page.tsx`, `contribute/page.tsx`, `status/page.tsx`.
   - Existing proxy route: `website/src/app/api/status/route.ts` proxies to `SCHEDULER_URL` (`http://localhost:8000`) and `NODE_URL` (`http://localhost:8080`).

2. **Backend API Capability Audit**:
   - **Scheduler API** (`Scheduler/src/scheduler/api/`):
     - `POST /v1/chat/completions`: Accepts `ChatCompletionRequest`, requires JWT header (RS256), applies token-bucket rate limiting (`429`), returns streaming SSE (`text/event-stream`) or JSON response.
     - `GET /v1/models`: Returns list of models available across registered nodes.
     - `GET /nodes/telemetry`: Returns decrypted hardware telemetry for all active nodes.
   - **Node API** (`Node/src/node/api/control.py`):
     - `POST /api/v1/node/control`: Takes `{"action": "start" | "stop"}`, starts/stops node runtime loop.
     - `GET /api/v1/node/telemetry`: Returns `NodeTelemetryResponse` (`cpu_utilization`, `ram_used_bytes`, `ram_total_bytes`, `gpu_utilization`, `vram_used_bytes`, `vram_total_bytes`, `wan_connected`, `status`).
     - `GET /api/v1/sandbox/logs`: Returns recent Docker sandbox logs array.
     - `GET /api/v1/sandbox/logs/stream`: Returns real-time Docker sandbox logs as SSE stream (`text/event-stream`).

---

## 2. Logic Chain

1. **API Proxy Layer Rationale**:
   - Client-side React components in Next.js executing in browsers require clean API access without triggering CORS errors or exposing internal tokens.
   - Creating Next.js App Router API proxy routes (`/api/chat/completions`, `/api/models`, `/api/node/control`, `/api/node/telemetry`, `/api/sandbox/logs/stream`, `/api/telemetry/all`) enables standard server-side request forwarding, streaming response pipe-through (`new Response(upstreamRes.body)`), and environment variable isolation (`SCHEDULER_URL`, `NODE_URL`).

2. **R1 Host Contributor Telemetry Dashboard Architecture**:
   - Modularized into `HostControlCard` (toggle start/stop), `TelemetryGauges` (CPU, RAM, VRAM), `AEADTelemetryBadge` (AES-256-GCM / SHA-256 HMAC verification & staleness check), `P2PWanStatus` (Zenoh mesh state), `HeartbeatHealthCard` (pulse & eviction boundary $\Delta t \le 15.0\text{s}$), and `DockerSandboxLogViewer` (real-time SSE log terminal).

3. **R2 Interactive Requester Chat Playground Architecture**:
   - Modularized into `ChatPlayground` (main layout), `ChatMessageList` (token stream rendering & blinking cursor), `ChatInputForm` (prompt submission), `PlaygroundSettings` (model selector, temperature slider, max tokens, top-P, RS256 JWT auth input), `LatencyMetricsCard` (TTFT ms calculation, tokens/sec rate, total elapsed time), and `ErrorRateLimitBanner` (handles 429 Too Many Requests, 503 No Node Available, 401 Unauthorized).

---

## 3. Caveats

1. **Docker Sandbox Log Stream Availability**:
   - Docker sandbox log streaming (`/api/v1/sandbox/logs/stream`) relies on the host node runtime being active (`status === "ready" || status === "running"`). If the node is stopped, the stream will return heartbeat keep-alives or close gracefully.
2. **Local Environment Defaults**:
   - If `SCHEDULER_URL` or `NODE_URL` environment variables are omitted, proxy routes default to `http://localhost:8000` and `http://localhost:8080` respectively.

---

## 4. Conclusion

The complete architectural plan, directory layout, component interfaces, state models, and API proxy routing specs for R1 (Host Telemetry Dashboard) and R2 (Requester Chat Playground) have been analyzed and documented in detail in `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_2/analysis.md`. The design is ready for immediate implementation by the `CODER` agent.

---

## 5. Verification Method

1. **Next.js Compilation & Type Verification**:
   - Command: `cd /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/website && npm run build`
   - Invalidation condition: Any Next.js compilation errors, broken imports, or TypeScript type mismatches.
2. **Frontend Linter Check**:
   - Command: `cd /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/website && npm run lint`
   - Invalidation condition: Any ESLint rules or syntax violations.
3. **Backend Service Health Check**:
   - Commands:
     - `curl -s http://localhost:8000/health/live` (Scheduler live check)
     - `curl -s http://localhost:8080/health/live` (Node live check)
