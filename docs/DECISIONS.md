# Public Intelligence Node Engineering Decisions

## Purpose

This document records the major architectural decisions made during the development of the Public Intelligence Node.

It exists to explain *why* the system is designed the way it is.

Future changes should respect these decisions unless there is a compelling architectural reason to change them.

---

# Repository Scope

The Node is responsible only for local inference.

It is **not** responsible for:

- Scheduling
- Load balancing
- Global coordination
- Request routing
- Network state

These responsibilities belong exclusively to the Scheduler.

---

# Single Responsibility Principle

Every major component should have one clearly defined responsibility.

Examples:

- Core → configuration and logging
- Models → validation only
- Scheduler Client → communication with Scheduler
- Ollama Client → local inference
- API → request validation and delegation
- Runtime → lifecycle management

No component should assume responsibilities belonging to another.

---

# Thin API Layer

FastAPI endpoints should remain minimal.

Endpoints should:

- Validate input.
- Delegate work.
- Return responses.

Business logic belongs inside the underlying components.

---

# Scheduler as Source of Truth

The Scheduler maintains the global state of the network.

The Node reports information but never makes scheduling decisions.

This ensures consistent decision making across the network.

---

# Ollama Abstraction

Inference execution is isolated behind the Ollama Client.

The rest of the codebase should never communicate directly with Ollama.

This allows future inference backends to be introduced without affecting the rest of the architecture.

---

# Runtime Separation

Startup and shutdown logic belong to the Runtime component.

Registration, heartbeat loops, and graceful shutdown should never be implemented inside API routes.

---

# Stateless API

The HTTP API should remain stateless.

Runtime state belongs inside the Runtime and Clients.

No request should depend on previous requests.

---

# Configuration First

All configurable values should be loaded through the configuration system.

Avoid hardcoded:

- URLs
- Ports
- Time intervals
- Model names

Configuration should remain centralized.

---

# Explicit Dependencies

Components should receive dependencies explicitly.

Avoid:

- Global variables
- Singleton patterns
- Hidden shared state

Dependency injection should be preferred whenever practical.

---

# Documentation Policy

Documentation is part of the implementation.

A feature is not complete until:

- Documentation is updated.
- Tests pass.
- Verification succeeds.

Implementation and documentation should always remain synchronized.

---

# Version 1 Philosophy

Version 1 prioritizes:

- Simplicity
- Reliability
- Correctness
- Readability

It intentionally excludes:

- Authentication
- TLS
- Streaming responses
- Multiple inference backends
- Persistence
- Advanced monitoring

These capabilities belong to future versions after the architecture has been validated.

---

# Long-Term Direction

The architecture should remain modular enough that future capabilities can be added without major refactoring.

New functionality should be introduced by extending existing components rather than violating established boundaries.