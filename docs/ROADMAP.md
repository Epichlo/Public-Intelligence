# Public Intelligence Node Roadmap

## Overview

The Public Intelligence Node will be developed incrementally.

Each feature builds upon previously completed functionality.

No feature should be implemented until its dependencies are complete.

Every completed feature must include:

- Unit tests
- Documentation updates
- Verification using Ruff, MyPy, and Pytest

---

# Version 1.0

The goal of Version 1.0 is to produce a fully functional compute node capable of participating in the Public Intelligence network.

At the end of Version 1.0 a user should be able to:

- Run a Node on their computer.
- Register with a Scheduler.
- Send heartbeats.
- Host one or more local AI models.
- Receive inference requests.
- Execute inference locally.
- Return generated responses.

---

# Feature Roadmap

## Phase 1 — Repository Foundation

Create the project structure.

Implement:

- project configuration
- development tooling
- logging
- configuration management
- health endpoint
- testing infrastructure

Status:

- [x] Completed

---

## Phase 2 — Configuration

Implement configuration loading.

Responsibilities:

- Scheduler URL
- Node ID
- Hostname
- Region
- Hosted models
- Heartbeat interval
- API configuration

Status:

- [x] Completed

---

## Phase 3 — Domain Models

Implement all core data models.

Models include:

- NodeInfo
- Heartbeat
- InferenceRequest
- InferenceResponse
- ModelInfo

These models should contain validation only.

Status:

- [x] Completed

---

## Phase 4 — Scheduler Client

Implement communication with the Scheduler.

Features:

- Register Node
- Send Heartbeats
- Graceful Unregister
- Retry failed requests

Status:

- [x] Completed

---

## Phase 5 — Ollama Integration

Implement local model execution.

Features:

- Discover models
- Verify model availability
- Execute inference
- Handle execution failures

Status:

- [x] Completed

---

## Phase 6 — Inference API

Expose the Node API.

Endpoints include:

- POST /infer
- GET /health
- GET /models

Business logic should remain minimal.

Status:

- [x] Completed

---

## Phase 7 — Runtime

Implement the Node lifecycle.

Features:

- Startup
- Registration
- Background heartbeat loop
- Graceful shutdown

Status:

- [x] Completed

---

## Phase 8 — End-to-End Demonstration

Demonstrate a complete workflow.

The demonstration should show:

1. Node startup.
2. Scheduler registration.
3. Heartbeats.
4. Local model execution.
5. Successful inference response.

This concludes Version 1.0.

Status:

- [x] Completed

---

## Phase 9 — Abstract Inference Backends & Out-of-Band Artifact Store

Implement provider-agnostic inference backend abstraction and out-of-band persistence layer.

Features:

- `InferenceBackend` abstract interface (`OllamaBackend` via `httpx.AsyncClient`, `EchoBackend` mock)
- `LocalDiskArtifactStore` persistence (`/tmp/public_intelligence/artifacts/{artifact_id}.bin`)
- Content-addressed SHA-256 hash invariant (`artifact_id = art_{task_id}_{checksum[:12]}`)
- Decoupled payload transport emitting lightweight `ArtifactMetadata` over Zenoh mesh

Status:

- [x] Completed

---

## Phase 10 — Protocol Synchronization & Verification Benchmarks (REG-ORG-SYNC-003)

Validate system benchmarks and synchronize cross-repository architecture specifications.

Results:

- 65 / 65 Node unit & integration tests passing (159 total system tests)
- Dynamic stale node eviction boundary: $15.05\text{s}$ under unannounced network drops ($\Delta t > 15.0\text{s}$)
- 100% ruff check, ruff format, and strict mypy zero-type-leak compliance

Status:

- [x] Completed

---

# Future Versions

## Version 0.2 (Next Baseline — Phase 3)
- Early CI/CD Agent Code Auditors (lint/type check agents validating MyPy strict typing, ruff layout compliance, and pytest regression suites on every PR).

## Version 0.3 (Accelerated — Phase 3.5 / 4)
- Web/Desktop Visual Dashboard (One-click host with VRAM/CPU gauges & interactive prompt playground).
- P2P Model Parallelism across consumer GPUs (tensor layer sharding & sequential streaming).

## Version 1.0 (Full Vision — Phase 5)
- Fully autonomous self-improving fabric (agents analyze GitHub issues, run WAN tests, and merge verified PRs).

These features are intentionally excluded from Version 1.0.

---

# Completion Criteria

Version 1.0 is complete when a user can:

1. Start a Node.
2. Register with a Scheduler.
3. Host a local AI model.
4. Receive inference requests.
5. Execute inference successfully.
6. Return generated responses.
7. Shut down gracefully.

At that point the Node is considered production-ready for the initial Public Intelligence prototype.