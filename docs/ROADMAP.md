# Public Intelligence Protocol Specification: Master Master Roadmap (`ROADMAP.md`)

This specification details the sequential architectural evolution of the Public Intelligence protocol—from foundational control plane mechanics (v0.1) to a fully autonomous, self-healing, distributed compute fabric (v1.0+).

## 📊 Master Architectural Progression Matrix

| Version Horizon | Protocol Phase | Key Capabilities (User / Contributor View) | Underlying Computer Science & Systems Invariants |
| :--- | :--- | :--- | :--- |
| **v0.1 (Realized)** | **Phases 0–2** | RS256 JWT auth, thread-safe token bucket rate-limiting, Two-Stage matchmaking, out-of-band SHA-256 persistence, 159 passing unit/integration assertions. | Asymmetric edge ingress proxy, Raft consensus core, decoupled control path with content-addressed `ArtifactStore`. |
| **v0.2 (Realized)** | **Phase 3** | Zenoh P2P heartbeats, dynamic 15.05s stale worker eviction under WAN drops, **+ Antigravity Sub-Agent Development Governance**. | Asynchronous P2P telemetry mesh, AEAD encrypted telemetry envelopes, closed-loop sub-agent verification rules. |
| **v0.3 (Next Priority)** | **Phase 4** | **Global P2P WAN Network Discovery & Node Join**, NAT Traversal, P2P Model Parallelism across consumer GPUs. | Public Zenoh router endpoints, P2P NAT traversal, tensor layer sharding & activation streaming over WAN. |
| **v0.35 (Follow-up)** | **Phase 4.5** | **Web/Desktop Visual Control Plane (Interactive Playground & Host Dashboard)** reflecting live global network topology. | Visual Control Plane (WebUI/Desktop App), real-time global telemetry streaming, prompt playground. |
| **v1.0 (Full Vision)** | **Phase 5** | Fully autonomous self-improving fabric (agents analyze GitHub issues, run WAN tests, and merge verified PRs). | LangGraph multi-agent orchestrator, n8n webhook event automation, self-correcting agent loops. |

---

## 🏛️ Detail Breakdown of Horizon Expansion

### Phase 3: Telemetry Mesh & Antigravity Sub-Agent Governance (v0.2 — Realized)
- **Zenoh Telemetry Pulse:** Compute nodes broadcast dynamic VRAM, RAM, and CPU state vectors out-of-band over `public-intelligence/net/nodes/<node_id>/telemetry` at 5.0s intervals.
- **Stale Node Eviction Boundary:** Strict dynamic eviction enforced when heartbeat silence exceeds $15.05\text{s}$ ($\Delta t > 15.0\text{s}$).
- **Antigravity Sub-Agent Governance:** Standardized sub-agent execution roles (`ORCHESTRATOR`, `ARCHITECT`, `CODER`, `AUDITOR`, `VERIFIER`) operating under shared project state, strict closed-loop verification (`pytest`, `ruff`, `mypy`), automated documentation logging, and git commit synchronization.

### Phase 4: Global P2P WAN Networking & Pipeline Parallelism (v0.3 — Current Priority)
- **Global P2P WAN Node Join & Discovery:** Expose Zenoh WAN router endpoints and connection profiles enabling compute nodes behind home routers (NAT) and external WAN IPs to discover Schedulers and join the global network pool.
- **NAT Traversal & Dynamic Routing:** Seamless peer-to-peer session establishment across WAN networks with AEAD-encrypted telemetry and sliding-window backpressured WAN streams.
- **Pipeline Parallelism (Layer Sharding):** Large language model weight matrices are sharded across disparate physical nodes over P2P networks, passing activation tensors sequentially to execute models exceeding any single machine's VRAM.

### Phase 4.5: Visual Control Plane & Web Dashboard (v0.35 — Next Step)
- **Visual Control Plane (Web/Desktop Dashboard):**
  - *Contributor Onboarding & Download*: One-click "Download Host Node" Desktop App installer (`.dmg`, `.exe`, `.AppImage`) and automated single-line bash command (`curl -fsSL https://public-intelligence.net/install.sh | bash`) with automatic GPU/VRAM hardware discovery.
  - *Contributor Dashboard:* Interactive "Start Host Node" toggle with real-time VRAM/CPU telemetry gauges, global WAN connection status, and Docker sandbox health indicators.
  - *Requester Playground:* Interactive chat playground (`/playground`) with SSE token streaming, model selection, and API Key/JWT management.
  - *OpenAI-Compatible REST API Gateway:* Public `/v1/chat/completions` endpoint for seamless integration with external OpenAI-compatible SDKs, LangChain, and LlamaIndex.
- **Sandboxed Ephemeral Execution:** Workloads executed inside memory-capped, network-restricted Docker containers or ephemeral Git worktrees to prevent host machine contamination.

### Phase 5: Autonomous Self-Improving Fabric (v1.0)
- **LangGraph Multi-Agent Orchestrator:** Closed-loop reasoning (Planner $\rightarrow$ Architect $\rightarrow$ Task Planner $\rightarrow$ Engineers $\rightarrow$ Reviewer $\rightarrow$ Verifier).
- **n8n Webhook Integration:** Automatic translation of tagged GitHub issues into execution missions, drafting, testing, and opening PRs autonomously.