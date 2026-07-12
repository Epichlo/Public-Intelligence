# Public Intelligence Node Architecture

## Overview

The Public Intelligence Node is a lightweight compute worker that hosts local AI models and executes inference requests assigned by the Scheduler.

Each Node operates independently.

It communicates with the Scheduler through registration and heartbeat messages while exposing a local inference API for clients.

The Scheduler decides **where** work should execute.

The Node is responsible for **executing** that work.

Each component has a single responsibility.

---

# High-Level Architecture

```text
                    Public Intelligence

                  +--------------------+
                  |     Scheduler      |
                  +--------------------+
                           ▲
                           │
          Registration / Heartbeats
                           │
                           ▼
                +----------------------+
                |         Node         |
                +----------------------+
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
     Core Infrastructure  Inference API  Runtime
                           │
                           ▼
                    Ollama Client
                           │
                           ▼
                     Local AI Models
```

---

# Internal Architecture

The Node is composed of five major components.

---

## 1. Core Infrastructure

Provides the foundational services required by the Node.

Responsibilities:

- Configuration loading
- Logging
- Environment management
- Shared utilities

This layer contains no networking or inference logic.

---

## 2. Domain Models

Defines the data exchanged between components.

Examples include:

- Node
- Heartbeat
- ModelInfo
- InferenceRequest
- InferenceResponse

These models contain validation only.

They should never contain business logic.

---

## 3. External Clients

Responsible for communication with external systems.

### Scheduler Client

Responsibilities:

- Register Node
- Send heartbeats
- Gracefully unregister
- Retry failed requests

The Scheduler Client never performs scheduling.

It only communicates with the Scheduler.

### Ollama Client

Responsibilities:

- Discover locally available models
- Execute inference
- Return generated responses

The Ollama Client never communicates directly with the Scheduler.

---

## 4. Inference API

Exposes a local HTTP API for inference requests.

Responsibilities:

- Validate requests
- Invoke the Ollama Client
- Return generated responses

The API layer should remain thin.

Business logic belongs inside the underlying components.

---

## 5. Runtime

Coordinates the lifecycle of the Node.

Responsibilities:

- Startup
- Component initialization
- Scheduler registration
- Background heartbeat loop
- Graceful shutdown

The Runtime orchestrates components but contains no inference or scheduling logic.

---

# Component Relationships

```text
                Runtime
                   │
      ┌────────────┼────────────┐
      ▼            ▼            ▼
 Core Infrastructure  Inference API  Scheduler Client
      │            │
      │            ▼
      │      Ollama Client
      │            │
      └────────────▼
            Local Models
```

---

# Communication Flow

## Startup

```text
Start Node
      │
      ▼
Load Configuration
      │
      ▼
Initialize Ollama Client
      │
      ▼
Register with Scheduler
      │
      ▼
Start Heartbeat Loop
      │
      ▼
Wait for Inference Requests
```

---

## Registration

```text
Node
      │
POST /nodes/register
      │
      ▼
Scheduler
      │
      ▼
Node Registered
```

---

## Heartbeat

```text
Collect Runtime Metrics
      │
      ▼
POST /heartbeat
      │
      ▼
Scheduler Updates Runtime State
```

---

## Inference

```text
Client
      │
POST /infer
      │
      ▼
Inference API
      │
      ▼
Ollama Client
      │
      ▼
Local Model
      │
      ▼
Generated Response
      │
      ▼
Client
```

---

# Design Principles

Every component should have exactly one responsibility.

Business logic should remain isolated.

Communication between components should occur only through well-defined interfaces.

The Node should remain lightweight, modular, and easy to understand.

Replacing the inference backend (for example, Ollama with another engine) should require changes only to the corresponding client.

---

# Repository Structure

```text
src/node/

├── core/
│   ├── configuration.py
│   └── logging.py
│
├── models/
│
├── clients/
│   ├── scheduler.py
│   └── ollama.py
│
├── api/
│
├── runtime/
│
└── main.py
```

Each directory represents a single architectural component.

Implementation details should remain encapsulated within their respective modules.

Dependencies should flow inward:

Core Infrastructure → Clients → API → Runtime

No component should violate these architectural boundaries.