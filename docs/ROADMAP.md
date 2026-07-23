# Public Intelligence Protocol Specification: Master Master Roadmap (`ROADMAP.md`)

This specification details the sequential architectural evolution of the Public Intelligence protocol—from foundational control plane mechanics (v0.1) to a fully autonomous, self-healing, distributed compute fabric (v1.0+).

## 📊 Master Architectural Progression Matrix

| Version Horizon | Protocol Phase | Key Capabilities (User / Contributor View) | Underlying Computer Science & Systems Invariants |
| :--- | :--- | :--- | :--- |
| **v0.1 (Realized)** | **Phases 0–2** | RS256 JWT auth, thread-safe token bucket rate-limiting, Two-Stage matchmaking, out-of-band SHA-256 persistence, 159 passing unit/integration assertions. | Asymmetric edge ingress proxy, Raft consensus core, decoupled control path with content-addressed `ArtifactStore`. |
| **v0.2 (Realized)** | **Phase 3** | Zenoh P2P heartbeats, dynamic 15.05s stale worker eviction under WAN drops, **+ Automated CI/CD Multi-Agent Code Auditors**. | Asynchronous P2P telemetry mesh, AEAD encrypted telemetry envelopes, automated lint/type check agents. |
| **v0.3 (Next Horizon)** | **Phase 3.5 / 4** | **+ Web/Desktop Visual Dashboard (One-click host & prompt playground)**, Sandboxed Docker runtimes, P2P Model Parallelism across consumer GPUs. | Visual Control Plane (WebUI/Desktop App), container isolation, P2P tensor layer sharding & sequential streaming. |
| **v1.0 (Full Vision)** | **Phase 5** | Fully autonomous self-improving fabric (agents analyze GitHub issues, run WAN tests, and merge verified PRs). | LangGraph multi-agent orchestrator, n8n webhook event automation, self-correcting agent loops. |

---

## 🏛️ Detail Breakdown of Horizon Expansion

### Phase 3: Telemetry Mesh & Automated Agent Code Auditors (v0.2 — Realized)
- **Zenoh Telemetry Pulse:** Compute nodes broadcast dynamic VRAM, RAM, and CPU state vectors out-of-band over `public-intelligence/net/nodes/<node_id>/telemetry` at 5.0s intervals.
- **Stale Node Eviction Boundary:** Strict dynamic eviction enforced when heartbeat silence exceeds $15.05\text{s}$ ($\Delta t > 15.0\text{s}$).
- **In-Code Multi-Agent Orchestrator:** Integrated `MultiAgentOrchestrator` engine into `Node` and `Scheduler` featuring `WorkerContext` task isolation, Pydantic delta models (`SharedStateDelta`), and `asyncio.Lock`-protected atomic state transitions ($S_{t+1} = S_t \oplus \Delta S_i$).
- **Automated CI/CD Multi-Agent Auditor Loop:** Deployed GitHub Actions workflow (`agent_auditor.yml`) and `scripts/run_agent_audit.py` runner triggering `ARCHITECT`, `AUDITOR`, and `VERIFIER` sub-agents on every pull request to enforce MyPy strict typing, `ruff` layout compliance, and pytest regression suites.

### Phase 3.5 / Phase 4: Visual Control Plane & Pipeline Parallelism (v0.3)
- **Visual Control Plane (Web/Desktop Dashboard):**
  - *Contributor View:* One-click "Start Host Node" toggle with real-time VRAM/CPU gauges and sandbox health indicators.
  - *Requester View:* Interactive prompt playground with live token streaming and API Key/JWT management.
- **Sandboxed Ephemeral Execution:** Workloads executed inside memory-capped, network-restricted Docker containers or ephemeral Git worktrees to prevent host machine contamination.
- **Pipeline Parallelism (Layer Sharding):** Large language model weight matrices are sharded across disparate physical nodes over P2P networks, passing activation tensors sequentially to execute models exceeding any single machine's VRAM.

### Phase 5: Autonomous Self-Improving Fabric (v1.0)
- **LangGraph Multi-Agent Orchestrator:** Closed-loop reasoning (Planner $\rightarrow$ Architect $\rightarrow$ Task Planner $\rightarrow$ Engineers $\rightarrow$ Reviewer $\rightarrow$ Verifier).
- **n8n Webhook Integration:** Automatic translation of tagged GitHub issues into execution missions, drafting, testing, and opening PRs autonomously.