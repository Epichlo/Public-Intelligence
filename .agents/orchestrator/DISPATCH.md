# DISPATCH

## 2026-07-26T18:21:41Z

You are the Project Orchestrator for Public Intelligence Phase 4.5.

Original Request Location: /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/ORIGINAL_REQUEST.md
Working Directory: /Users/atharvdeshpande/Desktop/Projects/Public-Intelligence/.agents/orchestrator

Your mission is to decompose and manage the complete implementation of Phase 4.5 Visual Control Plane & Interactive Web/Desktop Dashboard according to the AGENTS.md governance standard.

Requirements to implement:
R1. Host Contributor Visual Dashboard inside `website/` (Vite + React with Vanilla CSS):
  - Start / Stop Host Node toggle.
  - Real-time telemetry gauges (CPU, RAM, VRAM, active P2P WAN connection state).
  - Docker sandbox runtime health and log stream viewer.
R2. Requester Playground & OpenAI-Compatible REST Gateway:
  - Interactive prompt playground (`/playground`) with SSE token streaming.
  - OpenAI-compatible REST API gateway endpoint `POST /v1/chat/completions` in Scheduler service translating standard OpenAI payload specs to `/api/v1/tasks/submit` ingress requests, with JSON and streaming (`stream: true`) SSE responses, handling auth (JWT) and rate limiting (429).
R3. One-Click Host Installer Script (`install.sh`):
  - Detect GPU/VRAM hardware, verify Docker/Python prerequisites, configure WAN P2P endpoints, bootstrap Node runtime.

Governance & Verification Rules:
1. Multi-agent execution loop with subagents (ARCHITECT, CODER, AUDITOR, VERIFIER).
2. Closed-loop verification: `pytest`, `ruff check .`, `ruff format --check .`, `mypy` across all modified sub-repositories must pass 100% cleanly.
3. Mandatory documentation updates: update `/docs/ROADMAP.md`, `Scheduler/docs/STATUS.md`, `Node/docs/STATUS.md`, and append execution log entries to `AGENTS.md` under `2026-07-26` (or today's date).
4. Update `progress.md` continuously in your working directory (`.agents/orchestrator/progress.md`).
5. When all milestones are verified and complete, send a message claiming victory and output your handoff report to `.agents/orchestrator/handoff.md`.
