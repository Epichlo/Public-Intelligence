# ARCHITECTURE

## Overview

Public Intelligence is designed as a collection of independent but interconnected systems that together form a globally distributed AI infrastructure.

Each repository has a single responsibility. Together they enable a decentralized network capable of hosting and serving frontier open-source AI models over residential WAN networks.

The architecture is intentionally modular so that components can evolve independently without compromising the overall system.

---

# High-Level Architecture

```
                 Requesters / API Clients
                            │
                            ▼
              Website & Visual Control Plane
                            │
                            ▼
               API Ingress & Gateway Layer
             (/v1/chat/completions & /v1/batch)
                            │
                            ▼
                 Scheduler Control Plane
             (Raft Consensus & Matchmaker)
             ╱              │              ╲
            ╱               │               ╲
           ▼                ▼                ▼
     Local Client       Host Node A      Host Node B
    (Layer 0 / Head)   (Layers 1-16)    (Layers 17-32)
       └────────────────────┴────────────────┘
             Zenoh Asymmetric P2P WAN Mesh
```

The **Website** provides the public interface and developer playground.

The **Scheduler** coordinates global network state, two-stage node matchmaking, and workload-aware routing.

**Nodes** contribute compute resources, execute inference workloads, and participate in peer-to-peer layer sharding.

Together these components behave as one globally distributed AI platform.

---

# Key Architectural Directives & Design Pillars

## Directive 1: Asymmetric Split-Inference Architecture
- **Local Boundary Isolation:** The client/local edge node retains Layer 0 (Embedding) and the final LM Head (Unembedding / LM Head projection).
- **Intermediate Offloading:** Only intermediate hidden activation vectors (Layers 1 to N-1) flow across external Zenoh P2P channels.
- **Privacy Assurance:** External host nodes process only high-dimensional intermediate activation vectors, making prompt reconstruction mathematically impossible without local embedding weights.

## Directive 2: Speculative WAN Pipeline Engine
- **Local Draft Speculation:** Support for a local draft model (e.g. lightweight 8B variant) on the client edge gateway to generate blocks of candidate tokens ($K=5$).
- **Batch Payload Packaging:** The Zenoh tensor transport protocol (`TensorPayload`) packages multi-token candidate blocks into a single execution pass.
- **Parallel WAN Verification:** Pipeline stages verify candidate token blocks in parallel, reducing cross-node network round-trips by up to 75%.

## Directive 3: FP8 & Layer-Aware Activation Compression
- **Activation Serialization:** FP8 (E4M3 format) quantization integrated into `BackpressuredStreamRouter` for inter-node hidden state activations.
- **Bandwidth Savings:** Reducing payload sizes by 50% directly halves inter-node network transfer overhead while maintaining $<0.1\%$ perplexity degradation.

## Directive 4: Async KV-Cache Checkpointing & Dynamic State Rerouting
- **Background KV Replication:** Non-blocking KV-cache state snapshots (`KVCacheSnapshot`) streamed over Zenoh gossip channels to neighbor pipeline candidates.
- **Dynamic Pipeline Re-stitching:** Upon worker eviction ($\Delta t > 15.05\text{s}$), the scheduler automatically re-routes execution payloads to a replacement node holding identical weights, resuming computation from the restored KV checkpoint without restarting prompt evaluation.

## Directive 5: Workload-Aware System Routing
- **Interactive Routing (`/v1/chat/completions`):** Target real-time streaming requests to single-node high-VRAM devices (e.g. 64GB+ Apple Silicon Max/Ultra or workstations) or co-located local LAN clusters.
- **Asynchronous Batch Routing (`/v1/batch`):** Multi-node WAN pipeline mesh serves asynchronous bulk workloads (synthetic data generation, document processing, offline agent loops) where high aggregate throughput supersedes TTFT constraints.

---

# Major Components

## Website
- Publish documentation, research, architecture specs, and roadmap.
- Provide the Host Node Installer (`curl -fsSL https://public-intelligence.net/install.sh | bash` & Desktop app bundles).
- Host the Interactive Chat Playground (`/playground`) with SSE token streaming.

## Scheduler
- Node registration, Raft state consensus, and health monitoring.
- Workload-aware system routing (`/v1/chat/completions` vs `/v1/batch`).
- Two-stage matchmaking and dynamic KV-cache checkpoint rerouting.

## Node
- Advertise hardware capabilities (including Apple Silicon Metal Unified Memory).
- Execute inference workloads in isolated Docker sandboxes or Git worktrees.
- Stream AEAD encrypted telemetry pulses over Zenoh (`public-intelligence/net/nodes/<node_id>/telemetry`).

---

# Current Status

The core distributed architecture, visual control plane, and installer harness are realized through Phase 4.5. Upcoming architectural directives (Asymmetric Split-Inference, Speculative WAN Engine, FP8 Compression, Async KV Checkpointing, and Workload-Aware Batch Routing) are incorporated into the master roadmap (`ROADMAP.md`) for sequential execution in Phase 4.6+.
