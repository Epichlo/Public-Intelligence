# AGENTS

## Purpose

This document is the authoritative entry point and operational governance standard for every AI agent (including Antigravity sub-agents) working on Public Intelligence.

Before making any changes, every agent must understand the project and adhere strictly to the execution invariants described herein.

---

## Required Reading

Read the following documents in order before attempting implementation:

1. docs/PROJECT_CONTEXT.md
2. docs/ARCHITECTURE.md
3. docs/ENGINEERING_PRINCIPLES.md
4. docs/DEVELOPMENT_WORKFLOW.md
5. docs/ROADMAP.md
6. docs/GLOSSARY.md

Treat these documents as the authoritative description of the project.

---

## DEFAULT MULTI-AGENT EXECUTION & DOCUMENTATION GOVERNANCE

BY DEFAULT, FOR EVERY SINGLE USER PROMPT OR FEATURE REQUEST, YOU MUST AUTOMATICALLY EXECUTE THIS MULTI-AGENT & DOCUMENTATION LOOP WITHOUT REQUIRING EXPLICIT PROMPTING:

1. AUTONOMOUS TASK DECOMPOSITION & SUB-AGENT SPANNING:
   - Upon receiving any request, immediately act as ORCHESTRATOR and decompose the work into subtasks assigned to isolated sub-agents:
     * ARCHITECT: Audits system invariants, WAN latencies, and spec alignments.
     * CODER: Writes minimal, modular, type-safe Python/TypeScript implementations.
     * AUDITOR: Checks security boundaries, race conditions, and memory leaks.
     * VERIFIER: Runs test suites (`pytest`), linter checks (`ruff`), and static typing (`mypy`).
   - Sub-agents share a read-only snapshot of the project state and return atomic mutations merged via an atomic reducer lock.

2. MANDATORY CLOSED-LOOP VERIFICATION & AUTONOMOUS DEBUGGING:
   - Automatically run `pytest`, `ruff check .`, `ruff format --check .`, and `mypy src` across modified sub-repositories.
   - If any test or type check fails, AUTOMATICALLY capture the stack trace, assign a fix task to the CODER/AUDITOR sub-agents, re-verify, and repeat until 100% clean.

3. MANDATORY DOCUMENTATION & AUDIT LOGGING:
   - For every feature implemented or bug fixed, automatically update:
     * `/docs/ROADMAP.md` (Root matrix)
     * `Scheduler/docs/STATUS.md` and `Node/docs/STATUS.md`
     * Append the execution log entry to `AGENTS.md` under current date `2026-07-23`.

4. AUTOMATIC GIT COMMIT & SYNCHRONIZATION:
   - Automatically run `git add .` and commit passing implementations with conventional commit messages (e.g., `feat(...)`, `fix(...)`, `docs(...)`).

---

## Workflow

Before implementing:
- Understand the task.
- Read the relevant documentation.
- Inspect the existing codebase.
- Explain your implementation plan.
- Wait for approval before major architectural changes.

During implementation:
- Keep changes focused.
- Preserve architectural consistency.
- Avoid unnecessary dependencies.
- Reuse existing patterns whenever possible.

After implementation:
- Run verification (lint, build, tests where applicable).
- Summarize every changed file.
- Explain important decisions.
- Stop after completing the requested task.

---

## Philosophy

You are an engineer contributing to a long-term infrastructure project.

Optimize for:
- Simplicity
- Maintainability
- Documentation
- Modularity
- Long-term thinking

Do not optimize for short-term speed or unnecessary complexity.

---

## Event Log

### 2026-07-17

- **P2P Transport Integration**: Introduced `eclipse-zenoh` as a core transport dependency for the decentralized node heartbeat network layer.
- **Scheduler Zenoh Router**: Created [zenoh_router.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/core/zenoh_router.py) to asynchronously subscribe to node heartbeats (`public-intelligence/net/*/heartbeat`) and update `NodeRegistry` thread-safely via FastAPI lifespan hooks.
- **Node Zenoh Client**: Created [zenoh_heartbeat.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/clients/zenoh_heartbeat.py) to publish serialized metrics to the node's dedicated path.
- **Runtime Lifecycle Integration**: Integrated Zenoh heartbeat client into Node's runtime lifecycle loop ([runtime.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/runtime.py)).
- **Tri-Factor Verification**: Verified both Scheduler and Node codebases using Ruff (styling), MyPy (100% type definition compliance), and PyTest (added [test_zenoh_integration.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/tests/test_zenoh_integration.py) and [test_zenoh_client.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/tests/test_zenoh_client.py)).
- **Zenoh Liveliness & Self-Correcting Group Resizing**: Implemented Zenoh Liveliness token declaration on Node startup ([zenoh_heartbeat.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/clients/zenoh_heartbeat.py)) that automatically broadcasts an implicit drop event across `public-intelligence/net/liveliness/*` on disconnection/crash. Configured the Scheduler's [zenoh_router.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/core/zenoh_router.py) to subscribe to this path, capture DELETE events (peer deathrattles), and trigger idempotent unregistration ([unregister_node](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/registry/node_registry.py)) in the `NodeRegistry` to clear all dynamic herd dampeners and resize the active cluster pool.
- **Docker Sandbox Integration**: Extended the `WorktreeManager` class in the Node's runtime isolation module ([runtime.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/core/runtime.py)) with a secure Docker execution harness (`execute_in_sandbox`). Spawns short-lived container runtimes mounting the branch's isolated git worktree as a read-write volume inside `/workspace`, running as non-root where possible, constrained strictly to 512MB memory and a 60 seconds timeout, and fully isolated from host network and environment flags. Added integration tests in [test_worktree_manager.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/tests/test_worktree_manager.py) (skipping cleanly if Docker is unavailable) and verified Ruff and MyPy compliance.
- **SGLang-Style Prefix Caching**: Created [radix_cache.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/core/radix_cache.py) implementing a bounded `RadixTrieCache` (maximum 500 prompts) with exact character-level token path lookup, insertion, and LRU eviction. Intercepted prompts in the POST `/infer` endpoint inside [inference.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/api/inference.py), routing only the remaining suffix to the serving model (Ollama) and appending the complete prompt path back to the trie upon completion. Added unit/integration tests in [test_radix_cache.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/tests/test_radix_cache.py).
- **Distributed State Consensus Replication**: Created [consensus.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/core/consensus.py) implementing `RaftConsensusEngine` to run a lightweight Raft consensus protocol (Leader Election, Log Replication, AppendEntries heartbeats, and Term check logic) over Zenoh channels (`public-intelligence/net/consensus/*`). Hooked node registration/unregistration in [node_registry.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/registry/node_registry.py) to propose states and wait for majority consensus quorum commitment before modifying the registry. Integrated consensus lifecycle into [zenoh_router.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/core/zenoh_router.py), and added comprehensive integration tests in [test_consensus.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/tests/test_consensus.py).
- **Zero-Copy Shared Memory & Backpressured WAN Transport**: Created [transport.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/core/transport.py) (Node) and [transport.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/core/transport.py) (Scheduler). Implemented zero-copy shared memory IPC using length-prefixed `multiprocessing.shared_memory` blocks for co-located clients to bypass serialization overhead, and `BackpressuredStreamRouter` utilizing a sliding window flow control protocol over Zenoh for WAN streams. Integrated this transport layer directly into the streaming logic of the POST `/infer` endpoint in [inference.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/api/inference.py) to transparently yield memory addresses or backpressured text chunks. Verified Ruff, MyPy, and wrote comprehensive unit/integration tests in both subsystems.

### 2026-07-18

- **Zero-Copy & Backpressured Data Transport Realization**: Enhanced transport subsystems in both Node ([transport.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/core/transport.py)) and Scheduler ([transport.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/core/transport.py)). Implemented automatic Zenoh-based streaming loop integration in `BackpressuredStreamRouter` and `BackpressuredReceiver` to handle both local co-located processes (allocating shared-memory blocks via `multiprocessing.shared_memory` and passing only the token `shm://` over Zenoh) and remote WAN connections (publishing raw data chunks with sliding window flow control backpressure). Integrated this directly into `POST /infer` endpoint ([inference.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/api/inference.py)) with double-cleanup safety guarantees to eliminate memory leaks. Verified Ruff, MyPy (100% type definition compliance), and PyTest integration test suites across both repositories.
- **Zenoh Telemetry Pipeline & Production Systemd Service**: Created [telemetry.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/core/telemetry.py) (Node) implementing `TelemetryEmitter` background task to publish system utilization metrics (CPU, RAM, accelerators placeholders) every 5 seconds over Zenoh (`public-intelligence/net/nodes/<node_id>/telemetry`). Subscribed to this feed in Scheduler's [zenoh_router.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/core/zenoh_router.py) to parse and map the hardware metrics straight into `NodeRegistry` metadata. Authored production-grade [public-intelligence-node.service](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/deploy/public-intelligence-node.service) with resource limits, auto-restart, and dropped privileges. Verified Ruff, MyPy compliance, and wrote integration tests in both Node and Scheduler.
- **Authenticated AEAD Telemetry Encryption & Signature Guards**: Implemented cryptography-based security layers in [telemetry.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/core/telemetry.py) (Node) and [zenoh_router.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/core/zenoh_router.py) (Scheduler) using AES-256-GCM and SHA-256 HMAC signature verification. Plaintext telemetry payloads are encrypted using `cryptography.hazmat.primitives.ciphers.aead.AESGCM` and signed using a pre-shared network key `TELEMETRY_SECRET_KEY` derived via SHA-256 key stretching. The Scheduler enforces strict constant-time signature checks (`hmac.compare_digest`) and drops altered/unsigned telemetry frames before mutating node registry state. Added unit and integration tests simulating secure broadcasts and tampered payload rejection.
- **Multi-Tenant Ingress Gateway & Token-Bucket Rate Limiting**: Created [ingress.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/api/ingress.py) implementing the exclusive `/api/v1/tasks/submit` edge proxy endpoint. It parses asymmetric tenant JWT tokens (RS256) from the `Authorization` header and validates signatures against configured public keys. Integrated [rate_limiter.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/core/rate_limiter.py) featuring an asynchronous, threadsafe `TokenBucketLimiter` to enforce dynamic multi-tenant rate boundaries (burst capacity of 5, refill rate of 1 token/2s) before passing validated proposals to the `RaftConsensusEngine` log replication plane. Verified Ruff, MyPy, and wrote integration tests covering invalid JWT rejections, rate exhaustion (HTTP 429), tenant isolation, and consensus forwarding.
- **Abstract Inference Backend & Test Harnesses**: Created [base.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/backends/base.py) (Node) defining `InferenceBackend` abstract class interface to standardize synchronous and streaming LLM generation. Implemented a production-grade [ollama.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/backends/ollama.py) client using `httpx.AsyncClient` that handles status/connection validation upon initialization and parses line-by-line JSON stream buffers. Authored a deterministic [mock.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/backends/mock.py) `EchoBackend` loop runner for offline integration unit tests. Verified Ruff and MyPy compliance, and wrote test cases verifying generation outputs, streaming chunk parsers, and connection failure traps.
- **End-to-End Task Integration Loop**: Refactored the `/submit` ingress gateway route ([ingress.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Scheduler/src/scheduler/api/ingress.py)) to submit tasks directly to the `SchedulingEngine` (which applies capability filtering and loading-based scoring) and propose allocation events to the Raft consensus ledger. Updated the compute node runtime ([runtime.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/src/node/runtime.py)) to consume assigned tasks from its internal queue, execute generations using the `InferenceBackend` client, write outputs to the out-of-band `LocalDiskArtifactStore`, and report the `ArtifactMetadata` payload back over Zenoh. Created a system-wide end-to-end integration test suite ([test_end_to_end_pipeline.py](file:///Users/atharvdeshpande/Desktop/Public-Intelligence/Node/tests/test_end_to_end_pipeline.py)) verifying pipeline functionality.

### 2026-07-21

- **Global Documentation & Protocol Ledger Synchronization Run (REG-ORG-SYNC-003)**: Executed workspace-wide specification and architecture alignment capturing Phase 1 and Phase 2 engineering invariants across Scheduler (`c2419db`) and Node (`e9b4f20`).
- **Ingress & Rate Limiting Controls**: Documented asymmetric `RS256` JWT Ingress Router deployed at `/api/v1/tasks/submit` coupled with `TokenBucketLimiter` enforcing per-`tenant_id` boundaries (Burst Capacity: 5 tokens, Refill Rate: 1 token per 2.0s, Overflow Trigger: instant HTTP 429 Too Many Requests response).
- **Out-of-Band Data Persistence (`ArtifactStore`)**: Documented `LocalDiskArtifactStore` binary streaming to `/tmp/public_intelligence/artifacts/{artifact_id}.bin` adhering to SHA-256 hash invariant `artifact_id = art_{task_id}_{checksum[:12]}`. Heavy payload transport bypassed over decoupled control plane, transmitting lightweight `ArtifactMetadata` across Zenoh channels (`public-intelligence/net/tasks/<task_id>/result`).
- **Two-Stage Capability Matchmaker Engine**: Synchronized Stage 1 Constraint Filtering Matrix (bounded by `backend`, `model_id`, `available_vram_bytes`, and active pulse check $\Delta t \le 15.0\text{s}$) and Stage 2 Fitness Scoring Formula: $\text{Score} = (\text{Reliability} \times 100.0) - (\text{QueueDepth} \times 15.0) - (\text{CPUUtilization} \times 0.5)$.
- **Verification Telemetry Benchmarks**: Recorded 159/159 total test pass rate (65 Node, 94 Scheduler), $15.05\text{ seconds}$ dynamic stale node eviction boundary under unannounced network drops ($\Delta t > 15.0\text{s}$), and 100% `ruff check`, `ruff format`, and strict zero-type-leak `mypy` compliance.

### 2026-07-23

- **Antigravity Multi-Agent Sub-Agent Governance Transition**: Standardized Antigravity IDE sub-agent execution governance (`ORCHESTRATOR`, `ARCHITECT`, `CODER`, `AUDITOR`, `VERIFIER`) across `Public-Intelligence/AGENTS.md`, `Scheduler/AGENTS.md`, and `Node/AGENTS.md`. Sub-agents operate with a shared project state model, strict closed-loop verification (`pytest`, `ruff`, `mypy`), mandatory documentation synchronization, and automated git commits.
- **Verification Telemetry**: Verified 162 total test suite assertions (68 Node, 94 Scheduler) with 100% pass rate and zero linting/typing errors across all sub-repositories.
- **Phase 4 Prioritization Update (Global P2P WAN Networking)**: Updated `docs/ROADMAP.md`, `Node/docs/STATUS.md`, and `Scheduler/docs/STATUS.md` prioritizing Global P2P WAN Networking, NAT Traversal, and Node Join (Phase 4) ahead of the Web Visual Control Plane (Phase 4.5), ensuring nodes across different home/cloud networks can connect globally before launching the web UI dashboard.
- **Host & Requester UX Specifications**: Updated `docs/ROADMAP.md` and `docs/ARCHITECTURE_OVERVIEW.md` detailing explicit One-Click Node Installer specifications (`curl -fsSL https://public-intelligence.net/install.sh | bash` & Desktop app bundles) and Requester Chat UI (`/playground`) with OpenAI-compatible REST API gateway (`/v1/chat/completions`).