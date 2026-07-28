## 2026-07-29T00:53:04Z
Implement Milestone 3 in website/:
1. Host Contributor Telemetry Dashboard (/dashboard):
   - Host node start/stop toggle component (components/node-control-toggle.tsx) making POST /api/node/control.
   - Real-time telemetry gauges (components/telemetry-gauge.tsx) displaying CPU %, RAM usage/total, VRAM usage/total, AEAD encrypted telemetry status, heartbeat health indicator, and global P2P WAN connection state.
   - Real-time Docker sandbox log viewer (components/sandbox-log-viewer.tsx) connecting to SSE endpoint /api/sandbox/logs/stream.
2. Interactive Requester Chat Playground (/playground):
   - Responsive chat interface (app/playground/page.tsx & components) supporting real-time Server-Sent Events (SSE) token streaming from /api/chat/completions.
   - Model selector (fetching /api/models), prompt submission form, temperature/top_p/max_tokens controls, JWT token auth field.
   - Latency metrics card (Time To First Token [TTFT ms], tokens/sec generation rate, total elapsed time).
   - Rate limit (429) & error notification banner with actionable advice.
3. Next.js API Proxy Routes in website/src/app/api/:
   - /api/chat/completions/route.ts -> proxies POST to Scheduler http://localhost:8000/v1/chat/completions (supporting SSE streaming).
   - /api/models/route.ts -> proxies GET to Scheduler http://localhost:8000/v1/models.
   - /api/node/telemetry/route.ts -> proxies GET to Node http://localhost:8080/api/v1/node/telemetry.
   - /api/node/control/route.ts -> proxies POST to Node http://localhost:8080/api/v1/node/control.
   - /api/sandbox/logs/stream/route.ts -> proxies GET SSE to Node http://localhost:8080/api/v1/sandbox/logs/stream.
   - /api/telemetry/all/route.ts -> proxies GET to Scheduler http://localhost:8000/nodes/telemetry.
