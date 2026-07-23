# ARCHITECTURE

## Overview

Public Intelligence is designed as a collection of independent but interconnected systems that together form a globally distributed AI infrastructure.

Each repository has a single responsibility. Together they enable a decentralized network capable of hosting and serving frontier open-source AI models.

The architecture is intentionally modular so that components can evolve independently without compromising the overall system.

---

# High-Level Architecture

```
                 Users
                   │
                   ▼
              Website
                   │
                   ▼
              API Layer
                   │
                   ▼
              Scheduler
            ╱     │     ╲
           ╱      │      ╲
          ▼       ▼       ▼
      Node A   Node B   Node C
         │        │        │
         └────────┴────────┘
              Distributed
             AI Infrastructure
```

The Website explains the project and provides documentation.

The Scheduler coordinates the distributed network.

Nodes contribute compute resources and execute workloads.

Together these components behave as one globally distributed AI platform.

---

# Major Components

## Website

Purpose:

- Explain the project.
- Publish documentation.
- Publish research.
- Present the architecture.
- Grow the community.

The Website does not perform distributed inference.

It exists to communicate and document the project.

---

## Scheduler

Purpose:

Coordinate the global network.

Responsibilities include:

- Node registration.
- Resource tracking.
- Geographic scheduling.
- Load balancing.
- Health monitoring.
- Work assignment.

The Scheduler decides where inference workloads should execute.

---

## Node

Purpose:

Contribute compute resources to the network.

Responsibilities include:

- Advertise hardware capabilities.
- Report system health.
- Send periodic heartbeats.
- Execute inference workloads.
- Return results.
- Receive scheduler updates.
- Confine repository modifications and file editing sequences triggered by incoming agent payloads within isolated Git worktrees.

Nodes are independently operated by contributors around the world.

---

## Future Components

The platform will eventually expand beyond these core systems.

Potential future repositories include:

- Networking Protocols
- SDKs
- Monitoring
- Authentication
- Developer Tools
- Benchmarking
- Deployment Tooling
- Mobile Applications

Each repository should remain focused on a single responsibility.

---

# Request Flow

A simplified request flow is:

1. A user submits an inference request.
2. The Scheduler receives the request.
3. The Scheduler evaluates available nodes.
4. A suitable node (or set of nodes) is selected.
5. The selected node executes the workload.
6. Results are returned to the user.

Future versions may involve multiple nodes collaborating on a single inference request.

---

# Geographic Scheduling

One of the defining characteristics of Public Intelligence is geographic awareness.

The Scheduler should consider factors such as:

- Network latency.
- Geographic proximity.
- Resource availability.
- Current node load.
- Reliability.
- Health status.

This enables efficient global utilization of community-contributed compute.

---

# Design Philosophy

The architecture follows several principles.

## Modular

Every repository has a clear responsibility.

---

## Distributed

No single machine should become a permanent dependency for the network.

---

## Scalable

The architecture should support growth from a handful of nodes to thousands.

---

## Observable

The system should expose enough information to understand how it behaves.

---

## Evolvable

Individual components should be replaceable without redesigning the entire platform.

---

# Current Status

The architecture is currently in its first design iteration.

Many implementation details remain intentionally undecided.

Research and experimentation are expected to refine the design over time while preserving the overall architectural vision.