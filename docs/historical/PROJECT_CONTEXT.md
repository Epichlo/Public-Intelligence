# PROJECT_CONTEXT

## What is Public Intelligence?

Public Intelligence is an open engineering initiative building a globally distributed, community-owned AI infrastructure.

Its purpose is to allow individuals and organizations around the world to collectively contribute compute resources—GPUs, CPUs, storage, memory, and bandwidth—to host, serve, and improve frontier open-source AI models.

Rather than concentrating AI infrastructure inside a small number of organizations, Public Intelligence seeks to create public infrastructure that anyone can contribute to, build on, and benefit from.

The project is open source, modular, and designed for long-term sustainability.

---

# Mission

To democratize access to frontier AI by building globally distributed infrastructure that is owned and operated by its community rather than a single organization.

---

# Why This Project Exists

Today, frontier AI requires enormous computational resources that are controlled by a relatively small number of companies.

Open-source models are becoming increasingly capable, but deploying them at scale remains difficult due to the cost and complexity of infrastructure.

Public Intelligence exists to lower this barrier.

The long-term goal is to make serving powerful open-source AI models possible through a decentralized network of independently operated nodes that collectively function as one global AI platform.

---

# Long-Term Vision

Public Intelligence aims to become public infrastructure for AI in the same way Linux became public infrastructure for operating systems.

The project will consist of multiple focused repositories that together form a complete distributed AI platform.

These repositories will evolve independently while sharing a common architectural vision.

Examples include:

- Website
- Scheduler
- Node
- Protocols
- SDKs
- Developer Tools
- Monitoring
- Documentation

No single repository represents Public Intelligence.

Each repository is one component of a larger ecosystem.

---

# Core Principles

Public Intelligence is guided by several long-term principles.

## Community Ownership

Infrastructure should be owned by its community rather than centralized entities.

## Open Source

The entire platform should be openly developed and freely inspectable.

## Documentation First

Architecture and reasoning should be documented before implementation whenever practical.

## Long-Term Thinking

Every design decision should optimize for maintainability over years rather than rapid short-term development.

## Simplicity

Prefer simple, understandable systems over unnecessarily complex solutions.

## Modularity

Components should remain loosely coupled so that individual parts can evolve independently.

## Transparency

Architectural decisions should be explicit, documented, and easy to understand.

---

# Current Stage

Public Intelligence has completed its initial foundation and core distributed
systems implementation. The current baseline includes the Website, Scheduler,
and Node repositories, P2P WAN connectivity, encrypted telemetry, scheduler
state consensus, and pipeline model-layer sharding.

The immediate priorities are:

- Synchronizing organization and repository documentation with the implemented
  architecture.
- Defining the first usable Phase 4.5 visual control-plane slice.
- Making node onboarding and network operation understandable to contributors.
- Preserving verification, observability, and maintainability as the system
  expands.

The project is moving from core infrastructure realization toward a carefully
scoped contributor and requester experience. The Website should describe the
system accurately without presenting planned interfaces as already available.

---

# High-Level Architecture

The current architecture consists of several major components.

## Website

The public face of the project.

Responsible for documentation, research, architecture explanations, roadmap, and community onboarding.

## Scheduler

The global scheduling system responsible for assigning inference workloads to nodes based on resource availability, health, latency, and geographic considerations.

## Node

Software contributed by participants that advertises available resources, maintains communication with the scheduler, executes inference workloads, reports health, and participates in the distributed network.

For Repository Engineers, the Node enforces a secure sandboxed execution environment. All repository modifications and file editing sequences triggered by incoming agent payloads are confined strictly within programmatic, isolated Git worktrees.

Future repositories will expand this architecture while preserving the overall design philosophy.

---

# Inspirations

Public Intelligence learns from many existing systems while intending to develop its own architecture.

Important inspirations include:

- Petals
- Ray
- Kubernetes
- Linux
- Volunteer Computing
- Distributed Systems Research
- Peer-to-Peer Networks

The objective is not to replicate these projects but to combine their strongest ideas into a coherent global AI infrastructure.

---

# Success Criteria

Public Intelligence succeeds if it becomes infrastructure that remains useful for many years.

Success is measured not by the number of repositories or features, but by the quality of the architecture, the clarity of the documentation, the strength of the community, and the ability for anyone to contribute compute to a globally distributed AI network.

Every decision should move the project closer to that long-term vision.
