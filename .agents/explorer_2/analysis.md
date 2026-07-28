# Architectural Analysis & Implementation Specification: Phase 4.5 Web Visual Control Plane

**Author**: `explorer_2` (teamwork_preview_explorer)  
**Working Directory**: `/Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/explorer_2`  
**Date**: 2026-07-29  
**Target Subsystem**: `website/` (Next.js 16 + React 19 + Tailwind CSS v4)

---

## 1. Executive Summary

This report establishes the technical architecture, component breakdown, state management model, styling standards, and API integration paths for building **R1 (Host Contributor Telemetry Dashboard)** and **R2 (Interactive Requester Chat Playground)** inside `website/`.

### Key Findings
1. **Existing Stack**: `website/` is a Next.js 16 (App Router) project built with React 19, TypeScript 5, Tailwind CSS v4 (`@import "tailwindcss"; @import "shadcn/tailwind.css";`), `clsx`, and `tailwind-merge`.
2. **Backend API Readiness**:
   - **Scheduler API** (`http://localhost:8000`): Offers `/v1/chat/completions` (OpenAI-compatible SSE streaming & non-streaming with RS256 JWT auth + token-bucket rate limiting), `/v1/models`, `/nodes`, `/nodes/telemetry` (AEAD decrypted hardware telemetry feed over Zenoh).
   - **Node API** (`http://localhost:8080`): Offers `/api/v1/node/control` (`start` / `stop` host runtime), `/api/v1/node/telemetry` (CPU, RAM, VRAM, WAN state), `/api/v1/sandbox/logs` and `/api/v1/sandbox/logs/stream` (Docker sandbox log SSE stream).
3. **Integration Strategy**:
   - Create Next.js API Proxy Routes in `website/src/app/api/` to avoid browser CORS/mixed-content issues, manage environment variables (`SCHEDULER_URL`, `NODE_URL`, `SCHEDULER_NETWORK_AUTH_TOKEN`), and safely stream SSE payloads.
   - Implement `/dashboard` (or update `/status`) for R1 (Host Contributor Telemetry) and `/playground` for R2 (Requester Chat Playground).
   - Update navigation in `website/src/components/site-navigation.ts` and `SiteHeader` to provide seamless navigation.

---

## 2. Existing Website Audit

| File Path | Purpose | Key Imports / Dependencies |
| :--- | :--- | :--- |
| `website/package.json` | Project dependencies | Next 16.2.10, React 19.2.4, Tailwind v4, clsx 2.1.1, tailwind-merge 3.6.0 |
| `website/src/app/globals.css` | Styling & CSS variables | Tailwind CSS v4 `@theme` configuration using OKLCH color variables |
| `website/src/app/page.tsx` | Main landing page | `PageShell`, `Logo`, `SystemDiagram`, `TwitterTimeline` |
| `website/src/app/status/page.tsx` | Legacy status page | Client component polling `/api/status` and running inference probe |
| `website/src/app/api/status/route.ts` | Legacy proxy route | Next.js GET/POST route proxying to `SCHEDULER_URL` and `NODE_URL` |
| `website/src/components/site-navigation.ts` | Navigation config | Array of nav items (`/vision`, `/architecture`, `/research`, `/roadmap`, `/contribute`) |
| `website/src/components/site-header.tsx` | Navigation bar | Renders logo and navigation links |
| `website/src/components/page-shell.tsx` | Layout wrapper | Enforces max-width container and renders `SiteFooter` |

---

## 3. R1 Specification: Host Contributor Telemetry Dashboard (`/dashboard`)

The Host Contributor Telemetry Dashboard enables node operators to monitor host health, toggle runtime execution, inspect AEAD-encrypted telemetry feeds, verify P2P WAN connectivity, and view real-time Docker sandbox execution logs.

### 3.1 Components Breakdown

#### `HostControlCard` (`src/components/dashboard/host-control-card.tsx`)
- **Function**: Interactive control panel to launch or halt host node background runtime.
- **Controls**: "Start Host Node" / "Stop Host Node" action button with confirmation state and pulse ring.
- **State**:
  - `status`: `"ready" | "running" | "stopped" | "unreachable" | "transitioning"`
  - `actionPending`: boolean lock during POST `/api/v1/node/control` requests.
- **Data Call**: POST `/api/node/control` with body `{ "action": "start" | "stop" }`.

#### `TelemetryGauges` (`src/components/dashboard/telemetry-gauges.tsx`)
- **Function**: Visual progress gauges & numeric readouts for hardware utilization.
- **Gauges**:
  - **CPU Utilization**: Percentage readout (0-100%) with color thresholding (Green < 70%, Yellow < 90%, Red >= 90%).
  - **RAM Utilization**: Used GB / Total GB readout + percentage bar.
  - **VRAM Utilization**: Used GB / Total GB readout + percentage bar (specifically for GPU acceleration).
- **Data Source**: `GET /api/node/telemetry` or `GET /api/telemetry/all`.

#### `AEADTelemetryBadge` (`src/components/dashboard/aead-telemetry-badge.tsx`)
- **Function**: Visual indicator verifying end-to-end cryptographic telemetry integrity.
- **Metrics**:
  - Cipher: `AES-256-GCM`
  - Signature Check: `SHA-256 HMAC` signature constant-time verification status (`Verified` / `Tampered / Dropped`).
  - Staleness Boundary: Check $\Delta t \le 30.0\text{s}$ against host clock.
  - Payload Pulse Counter: Number of telemetry frames received in current session.

#### `P2PWanStatus` (`src/components/dashboard/p2p-wan-status.tsx`)
- **Function**: Network connection state and Zenoh router P2P topology status.
- **Display**:
  - WAN Connection Badge: `Connected (P2P Mesh)` or `Disconnected / Direct`.
  - Zenoh Endpoints: Configured peer endpoints and listen addresses.
  - Scouting Mode: Gossip scouting status (`gossip enabled`).

#### `HeartbeatHealthCard` (`src/components/dashboard/heartbeat-health-card.tsx`)
- **Function**: Monitors Scheduler registration and pulse vitality.
- **Display**:
  - Heartbeat status: `Healthy (< 5s)` / `Lagging (< 15s)` / `Stale Evicted (> 15s)`.
  - Dynamic herd dampening factor and registered node ID.

#### `DockerSandboxLogViewer` (`src/components/dashboard/docker-sandbox-log-viewer.tsx`)
- **Function**: Live streaming log console for short-lived Docker sandbox executions (512MB RAM, 60s timeout, non-root user isolation).
- **Features**:
  - SSE Stream Client connected to `/api/sandbox/logs/stream`.
  - Auto-scroll lock toggle (stick to bottom on new log line).
  - Search / Filter by level (`stdout`, `stderr`, `info`, `error`).
  - Clear log history button.
  - Formatted dark terminal styling (`font-mono text-xs`).

---

## 4. R2 Specification: Interactive Requester Chat Playground (`/playground`)

The Requester Chat Playground provides an OpenAI-compatible interactive chat interface with real-time SSE token generation streaming, detailed performance metrics (TTFT, t/s), and parameter customization.

### 4.1 Components Breakdown

#### `ChatPlayground` (`src/app/playground/page.tsx` & `src/components/playground/chat-playground.tsx`)
- **Function**: Layout container housing message thread, prompt input form, settings sidebar, and performance metrics panel.
- **State Management**:
  - `messages`: Array of `ChatMessage` (`role: "user" | "assistant" | "system"`, `content: string`, `timestamp?: string`).
  - `selectedModel`: String (e.g. `llama3.2`, default selected from available models list).
  - `temperature`: Number (0.0 to 2.0, default 0.7).
  - `maxTokens`: Number (64 to 4096, default 1024).
  - `topP`: Number (0.0 to 1.0, default 0.9).
  - `systemPrompt`: String custom system message.
  - `jwtToken`: Custom RS256 Bearer JWT string for authentication.
  - `isGenerating`: Boolean flag indicating active streaming.
  - `metrics`: `{ ttftMs: number | null, tokensPerSec: number | null, totalTokens: number, promptTokens: number, completionTokens: number, elapsedTimeMs: number }`.
  - `errorState`: `{ statusCode: number | null, message: string | null }`.

#### `ChatMessageList` (`src/components/playground/chat-message-list.tsx`)
- **Function**: Renders conversation history with distinct styling for System, User, and Assistant roles.
- **Features**:
  - Real-time token append animation during SSE streaming.
  - Blinking cursor (`█` or pulsing emerald dot) attached to the active assistant response chunk.
  - Copy code block / copy message content button.
  - Clear chat history trigger.

#### `ChatInputForm` (`src/components/playground/chat-input-form.tsx`)
- **Function**: User input text area with submit/stop controls.
- **Controls**:
  - Auto-resizing multi-line text area.
  - Keyboard shortcuts (`Enter` to submit, `Shift+Enter` for new line).
  - "Stop Generation" button when streaming is active (aborts `Fetch` signal).

#### `PlaygroundSettings` (`src/components/playground/playground-settings.tsx`)
- **Function**: Side drawer/panel for tuning inference parameters and auth headers.
- **Controls**:
  - Model Dropdown: Populated dynamically via GET `/api/models`.
  - Temperature Slider (0.0 - 2.0).
  - Max Tokens Input/Slider (64 - 4096).
  - Top-P Slider (0.0 - 1.0).
  - JWT Authorization Header Input (Configures `Authorization: Bearer <jwt>`).
  - System Prompt Editor.

#### `LatencyMetricsCard` (`src/components/playground/latency-metrics-card.tsx`)
- **Function**: Displays real-time generation performance telemetry.
- **Readouts**:
  - **TTFT (Time To First Token)**: Measured in ms from request click to first SSE token chunk.
  - **Generation Speed**: Tokens per second (t/s) calculated continuously during streaming.
  - **Elapsed Time**: Total inference duration in seconds.
  - **Token Counts**: Estimated prompt, completion, and total tokens.

#### `ErrorRateLimitBanner` (`src/components/playground/error-rate-limit-banner.tsx`)
- **Function**: Actionable warning and error alerts.
- **Triggers**:
  - **HTTP 429**: "Rate limit exceeded. Token bucket quota exhausted (5 burst / 1 token per 2s). Please wait before submitting another query."
  - **HTTP 503**: "No active compute node available serving model '{model_id}'."
  - **HTTP 401**: "Unauthorized. Invalid RS256 JWT signature or missing tenant claim."
  - **Network Error**: "Connection reset or gateway timeout."

---

## 5. API Integration & Proxy Architecture

To guarantee security, bypass CORS restrictions, and support SSE streaming across environments, Next.js API routes will be implemented under `website/src/app/api/`.

### 5.1 Route Handler Mapping

```
Browser Client (React)
    │
    ├── POST /api/chat/completions ────> Scheduler (http://localhost:8000/v1/chat/completions) [SSE Stream]
    ├── GET  /api/models           ────> Scheduler (http://localhost:8000/v1/models)
    ├── GET  /api/telemetry/all    ────> Scheduler (http://localhost:8000/nodes/telemetry)
    ├── GET  /api/node/telemetry   ────> Node      (http://localhost:8080/api/v1/node/telemetry)
    ├── POST /api/node/control     ────> Node      (http://localhost:8080/api/v1/node/control)
    └── GET  /api/sandbox/logs/stream ─> Node     (http://localhost:8080/api/v1/sandbox/logs/stream) [SSE Stream]
```

### 5.2 SSE Stream Handling Implementation Details
In Next.js 16 App Router, streaming SSE from an upstream FastAPI service is handled using `ReadableStream`:

```ts
// Example: src/app/api/chat/completions/route.ts
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const body = await request.json();
  const authHeader = request.headers.get("authorization");

  const schedulerUrl = (process.env.SCHEDULER_URL ?? "http://localhost:8000").replace(/\/$/, "");
  const upstreamUrl = `${schedulerUrl}/v1/chat/completions`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (authHeader) {
    headers["Authorization"] = authHeader;
  }

  const upstreamRes = await fetch(upstreamUrl, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  if (!upstreamRes.ok || !upstreamRes.body) {
    const errorText = await upstreamRes.text();
    return NextResponse.json(
      { error: errorText || "Upstream request failed" },
      { status: upstreamRes.status }
    );
  }

  return new Response(upstreamRes.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
    },
  });
}
```

---

## 6. Proposed Directory & Component Structure

Below is the exact file tree to be created in `website/`:

```
website/
├── src/
│   ├── app/
│   │   ├── api/
│   │   │   ├── chat/
│   │   │   │   └── completions/
│   │   │   │       └── route.ts         # Proxy for Scheduler POST /v1/chat/completions
│   │   │   ├── models/
│   │   │   │   └── route.ts             # Proxy for Scheduler GET /v1/models
│   │   │   ├── node/
│   │   │   │   ├── control/
│   │   │   │   │   └── route.ts         # Proxy for Node POST /api/v1/node/control
│   │   │   │   └── telemetry/
│   │   │   │       └── route.ts         # Proxy for Node GET /api/v1/node/telemetry
│   │   │   ├── sandbox/
│   │   │   │   └── logs/
│   │   │   │       └── stream/
│   │   │   │           └── route.ts     # Proxy for Node GET /api/v1/sandbox/logs/stream
│   │   │   └── telemetry/
│   │   │       └── all/
│   │   │           └── route.ts         # Proxy for Scheduler GET /nodes/telemetry
│   │   ├── dashboard/
│   │   │   └── page.tsx                 # R1: Host Contributor Telemetry Dashboard
│   │   ├── playground/
│   │   │   └── page.tsx                 # R2: Interactive Requester Chat Playground
│   │   └── ...
│   ├── components/
│   │   ├── dashboard/
│   │   │   ├── aead-telemetry-badge.tsx
│   │   │   ├── docker-sandbox-log-viewer.tsx
│   │   │   ├── heartbeat-health-card.tsx
│   │   │   ├── host-control-card.tsx
│   │   │   ├── p2p-wan-status.tsx
│   │   │   └── telemetry-gauges.tsx
│   │   ├── playground/
│   │   │   ├── chat-input-form.tsx
│   │   │   ├── chat-message-list.tsx
│   │   │   ├── chat-playground.tsx
│   │   │   ├── error-rate-limit-banner.tsx
│   │   │   ├── latency-metrics-card.tsx
│   │   │   └── playground-settings.tsx
│   │   ├── site-navigation.ts           # Add /dashboard and /playground
│   │   └── ...
```

---

## 7. Styling & UX Design Language Invariants

1. **Color Palette**: Strict adherence to the dark infrastructure theme defined in `globals.css`:
   - Primary accents: Emerald Green `#86EFAC` / Lime `#D9F99D` for active statuses, connected states, and metrics.
   - Backgrounds: Dark slate OKLCH (`var(--background)`), card containers (`var(--card)`).
   - Borders: Subtle border opacity `border-border/40`.
2. **Typography**: Mono accents (`font-mono`) for node IDs, timestamps, token counts, and terminal logs.
3. **Accessibility & Responsive Grid**: Flexbox and grid layouts (`md:grid-cols-2`, `lg:grid-cols-3`) with screen reader `aria-labelledby` attributes.

---

## 8. Implementation Guidance for CODER Role

1. **Step 1**: Create API Proxy routes under `website/src/app/api/`.
2. **Step 2**: Implement R1 Dashboard components under `website/src/components/dashboard/` and `/dashboard/page.tsx`.
3. **Step 3**: Implement R2 Playground components under `website/src/components/playground/` and `/playground/page.tsx`.
4. **Step 4**: Update `site-navigation.ts` to expose Playground and Dashboard in the header.
5. **Step 5**: Run `npm run build` in `website/` to verify zero TypeScript errors or build failures.

---
