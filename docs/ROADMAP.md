# Public Intelligence Protocol Specification: Master Roadmap (`ROADMAP.md`)

This specification details the sequential architectural evolution of the Public Intelligence protocol—from foundational control plane mechanics (v0.1) to a fully autonomous, self-healing, distributed compute fabric (v1.0+).

## 📊 Master Architectural Progression Matrix

| Version Horizon | Protocol Phase | Key Capabilities (User / Contributor View) | Underlying Computer Science & Systems Invariants |
| :--- | :--- | :--- | :--- |
| **v0.1 (Realized)** | **Phases 0–2** | RS256 JWT auth, thread-safe token bucket rate-limiting, Two-Stage matchmaking, out-of-band SHA-256 persistence, 159 passing unit/integration assertions. | Asymmetric edge ingress proxy, Raft consensus core, decoupled control path with content-addressed `ArtifactStore`. |
| **v0.2 (Realized)** | **Phase 3** | Zenoh P2P heartbeats, dynamic 15.05s stale worker eviction under WAN drops, **+ Antigravity Sub-Agent Development Governance**. | Asynchronous P2P telemetry mesh, AEAD encrypted telemetry envelopes, closed-loop sub-agent verification rules. |
| **v0.3 (Realized)** | **Phase 4** | **Global P2P WAN Network Discovery & Node Join**, NAT Traversal, P2P Model Parallelism across consumer GPUs. | Public Zenoh router endpoints, P2P NAT traversal, tensor layer sharding & activation streaming over WAN. |
| **v0.35 (Realized)** | **Phase 4.5** | **Web Visual Control Plane, Host Telemetry Dashboard, Requester Chat Playground, OpenAI REST Gateway (`/v1/chat/completions`), and One-Click Host Installer (`install.sh`)**. | Visual Control Plane (WebUI/Next.js), real-time global telemetry gauges, prompt playground, OpenAI API gateway, and host node launcher harness. |
| **v0.40 (Realized)** | **Phase 4.6** | **Asymmetric Split-Inference & Local Boundary Isolation** M1/M2 boundary contracts: Layer 0 Embedding & LM Head retained locally; remote hidden stages executed over Zenoh activation channels with 504 timeout & 502 validation error guards. | Client edge boundary isolation, activation-only split-stage validation, zero prompt/token leakage tests, production remote activation-response collection over Zenoh tensor topics. |
| **v0.45 (Realized)** | **Phase 4.7** | **Speculative WAN Pipeline Engine & FP8 Activation Compression** (Local 8B draft speculation $K=5$, 75% RTT reduction, FP8 E4M3 quantization with dynamic scaling factor). | Multi-token candidate block verification over WAN, FP8 `FP8Quantizer` dynamic max-abs scaling (50%-75% bandwidth reduction). |
| **v0.50 (Planned)** | **Phase 4.8** | **Async KV-Cache Checkpointing & Dynamic State Rerouting** (Background KV replication over Zenoh gossip, seamless restitching on node drop). | Non-blocking `KVCacheSnapshot` gossip streaming, zero-recomputation pipeline rerouting upon stale worker eviction ($\Delta t > 15.05\text{s}$). |
| **v0.55 (Planned)** | **Phase 4.9** | **Workload-Aware System Routing (`/v1/chat/completions` vs `/v1/batch`), Apple Silicon Onboarding & Fiat Credit Exchange Ledger**. | Interactive single-node / LAN routing vs multi-node WAN batch processing (`POST /v1/batch`), Apple Silicon Metal Unified Memory profiling, tokenless fiat credit exchange ledger. |
| **v1.0 (Full Vision)** | **Phase 5** | Fully autonomous self-improving fabric (agents analyze GitHub issues, run WAN tests, and merge verified PRs). | LangGraph multi-agent orchestrator, n8n webhook event automation, self-correcting agent loops. |

---

## 🏛️ Detail Breakdown of Horizon Expansion

### Phase 3: Telemetry Mesh & Antigravity Sub-Agent Governance (v0.2 — Realized)
- **Zenoh Telemetry Pulse:** Compute nodes broadcast dynamic VRAM, RAM, and CPU state vectors out-of-band over `public-intelligence/net/nodes/<node_id>/telemetry` at 5.0s intervals.
- **Stale Node Eviction Boundary:** Strict dynamic eviction enforced when heartbeat silence exceeds $15.05\text{s}$ ($\Delta t > 15.0\text{s}$).
- **Antigravity Sub-Agent Governance:** Standardized sub-agent execution roles (`ORCHESTRATOR`, `ARCHITECT`, `CODER`, `AUDITOR`, `VERIFIER`) operating under shared project state, strict closed-loop verification (`pytest`, `ruff`, `mypy`), automated documentation logging, and git commit synchronization.

### Phase 4: Global P2P WAN Networking & Pipeline Parallelism (v0.3 — Realized)
- **Global P2P WAN Node Join & Discovery (Realized):** Exposed Zenoh WAN router endpoints and connection profiles enabling compute nodes behind home routers (NAT) and external WAN IPs to discover Schedulers and join the global network pool.
- **NAT Traversal & Dynamic Routing (Realized):** Auto-bootstrap router fallbacks (`bootstrap_routers: tcp/bootstrap.public-intelligence.net:7447`), dynamic WAN gossip scouting (`scouting/gossip/enabled`), and AEAD-encrypted telemetry mesh operating seamlessly across residential NATs.
- **Pipeline Parallelism (Layer Sharding - Realized):** Large language model weight matrices sharded across disparate physical nodes over P2P networks, passing activation tensors sequentially to execute models exceeding any single machine's VRAM. Implemented `LayerRange`, `PipelineStage`, `TensorPayload` data models and `SchedulingEngine.schedule_pipeline()` multi-node chain allocator.

### Phase 4.5: Visual Control Plane & Web Dashboard (v0.35 — Realized)
- **Visual Control Plane (Web Dashboard & Host Contributor UI - Realized):**
  - *Contributor Onboarding & Download*: One-click Host Installer script (`install.sh`), daemon launcher (`scripts/launch_host_node.sh`), and `public-intelligence-node` CLI with automatic GPU/VRAM hardware discovery.
  - *Contributor Dashboard:* Interactive "Start Host Node" toggle with real-time VRAM/CPU telemetry gauges, global WAN connection status, and Docker sandbox health indicators.
  - *Requester Playground:* Interactive chat playground (`/playground`) with SSE token streaming, model selection, and API Key/JWT management.
  - *OpenAI-Compatible REST API Gateway:* Public `/v1/chat/completions` and `/v1/models` endpoints with RS256 JWT authentication and token-bucket rate-limiting.
- **Sandboxed Ephemeral Execution:** Workloads executed inside memory-capped, network-restricted Docker containers or ephemeral Git worktrees with SSE log streaming.

---

### Phase 4.6: Asymmetric Split-Inference & Local Boundary Security (v0.40 — Realized)
- **M1 Boundary Contract (Realized):** Client/Edge node retains Layer 0 (Embedding) and final LM Head (Unembedding projection) locally. Scheduler constructs the asymmetric topology `client_local embedding -> remote hidden layers -> client_local lm_head`.
- **Activation-Only Remote Stage Contract (Realized):** Node and Scheduler `TensorPayload` models expose `validate_split_activation_boundary()` so remote split-stage execution rejects prompt-like tensor types, string dtypes, structured prompt dictionaries, empty payloads, and malformed activation shapes.
- **Gateway Boundary Alignment (Realized):** The OpenAI split-inference gateway resolves to the canonical local boundary engine and preserves the activation-only handoff contract while retaining raw prompts and token history inside local memory.
- **M2 Remote Activation Collection & Error Semantics (Realized):** Production remote activation-response collection over Zenoh tensor topics (`public-intelligence/net/tasks/{task_id}/tensors/{stage_index}`), Node runtime dynamic split stage topic subscriber, configurable response timeout with HTTP 504 Gateway Timeout, and strict activation boundary validation error handling with HTTP 502 Bad Gateway.

---

### Phase 4.7: Speculative WAN Pipeline Engine & FP8 Activation Compression (v0.45 — Realized)
- **Local Draft Speculation (Realized):** Local draft candidate generation ($K=5$) on client edge gateway (`LocalBoundaryEngine.generate_speculative_candidates`) producing `DraftBlockPayload` multi-token candidate blocks.
- **Batch Payload Packaging & Parallel WAN Verification (Realized):** Multi-token candidate blocks packaged into `TensorPayload` for single-pass verification over WAN links, reducing cross-node network round-trips by up to 75%.
- **FP8 (E4M3) Activation Compression (Realized):** FP8 quantization integrated via `FP8Quantizer` with dynamic max-abs scaling ($S = \frac{448.0}{\max(|x|) + 1e-8}$), halving payload sizes (50% bandwidth savings) while keeping perplexity degradation $<0.1\%$.

---

### Phase 4.8: Async KV-Cache Checkpointing & Dynamic State Rerouting (v0.50 — Planned)
- **Background KV-Cache Replication:** Non-blocking KV-cache state snapshots (`KVCacheSnapshot`) streamed over Zenoh gossip channels (`public-intelligence/net/tasks/<task_id>/kv_snapshots`) to neighbor pipeline nodes.
- **Dynamic Pipeline Re-stitching:** When worker eviction occurs ($\Delta t > 15.05\text{s}$), the scheduler automatically re-routes execution payloads to a replacement node holding identical weights, resuming computation from the restored KV checkpoint without restarting prompt evaluation.

---

### Phase 4.9: Workload-Aware System Routing & Fiat Credit Exchange Ledger (v0.55 — Planned)
- **Interactive Routing (`/v1/chat/completions`):** Target real-time streaming requests to single-node high-VRAM devices or co-located local LAN clusters.
- **Asynchronous Batch Routing (`POST /v1/batch`):** Dedicated endpoint for bulk asynchronous processing (synthetic data generation, document processing, offline agent loops) over multi-node WAN pipeline mesh where aggregate throughput supersedes TTFT constraints.
- **Apple Silicon Hardware Onboarding:** Targeted supply-side onboarding for Apple Silicon M1/M2/M3/M4 Max & Ultra (64GB–192GB Unified Memory) workstations operating as silent, low-power background layer hosts.
- **Tokenless Fiat Credit Ledger:** Credit-exchange model ($1\text{ GB VRAM-Hour Hosted} = \text{Fixed Credit Allocation}$) paired with standard fiat gateways for commercial API usage, eliminating Web3 wallet/gas fee friction.

---

### Phase 5: Autonomous Self-Improving Fabric (v1.0)
- **LangGraph Multi-Agent Orchestrator:** Closed-loop reasoning (Planner $\rightarrow$ Architect $\rightarrow$ Task Planner $\rightarrow$ Engineers $\rightarrow$ Reviewer $\rightarrow$ Verifier).
- **n8n Webhook Integration:** Automatic translation of tagged GitHub issues into execution missions, drafting, testing, and opening PRs autonomously.
