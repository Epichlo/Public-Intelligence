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

# Future Versions

Future versions may include:

- Multiple inference backends.
- Streaming responses.
- Secure communication.
- Authentication.
- TLS.
- GPU monitoring improvements.
- Automatic model discovery.
- Container deployment.
- Kubernetes deployment.
- Peer-to-peer networking.

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