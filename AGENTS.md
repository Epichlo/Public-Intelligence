# AGENTS.md

# Public Intelligence Node

This repository is part of the Public Intelligence project.

Read this document completely before making any changes.

---

# Project Goal

The Public Intelligence Node transforms a computer into a compute worker capable of participating in the Public Intelligence network.

A Node is responsible for:

- Hosting local AI models.
- Registering with the Scheduler.
- Sending heartbeats.
- Executing inference.
- Returning generated responses.

The Node is NOT responsible for:

- Scheduling.
- Load balancing.
- Distributed coordination.
- Request routing.

These responsibilities belong exclusively to the Scheduler.

---

# Required Reading

Before implementing any feature, always read:

1. docs/VISION.md
2. docs/ARCHITECTURE.md
3. docs/ROADMAP.md
4. docs/API.md
5. docs/DECISIONS.md
6. docs/STATUS.md

Never begin implementation without understanding the current architecture.

---

# Architecture Rules

The architecture defined in the documentation is authoritative.

Do not invent new architectural patterns.

Do not reorganize the project structure.

Do not introduce new layers without explicit justification.

If documentation and implementation disagree, update the documentation before considering the task complete.

---

# Design Principles

Follow these principles throughout the repository.

## Single Responsibility

Every module should have one responsibility.

Avoid mixing unrelated concerns.

---

## Thin APIs

FastAPI endpoints should:

- Validate input.
- Delegate work.
- Return responses.

Business logic belongs in underlying components.

---

## Explicit Dependencies

Avoid:

- Global state
- Singleton patterns
- Hidden dependencies

Pass dependencies explicitly whenever practical.

---

## Small Changes

Prefer small, focused implementations.

Do not perform unrelated refactoring.

Do not change completed features unless required.

---

# Code Quality

All code must include:

- Type hints
- Docstrings
- Clear naming
- Small functions
- Minimal complexity

Favor readability over cleverness.

---

# Testing

Every feature must include appropriate tests.

Tests should cover:

- Success cases
- Failure cases
- Edge cases

Do not reduce existing test coverage.

---

# Documentation Policy

Documentation is part of the implementation.

Every completed feature must update all affected documentation.

Update whenever necessary:

- docs/STATUS.md
- docs/ROADMAP.md
- docs/API.md
- docs/ARCHITECTURE.md
- docs/DECISIONS.md
- docs/VISION.md

A feature is not complete until both the implementation and documentation are consistent.

---

# Verification

Before completing any task, run:

ruff check .

ruff format --check .

mypy src

pytest

Fix all issues introduced by the current feature.

If unrelated issues remain, explicitly identify them.

---

# Completion Checklist

A feature is complete only if:

- Implementation is finished.
- Tests pass.
- Documentation is updated.
- Verification succeeds.
- The architecture remains consistent.

---

# Communication

When finishing a task, return only:

1. Files created
2. Files modified
3. Documentation updated
4. Verification results
5. Short summary

Avoid unnecessary explanations.

---

# Long-Term Vision

The Node is one component of the larger Public Intelligence ecosystem.

Always prioritize:

- Simplicity
- Reliability
- Maintainability
- Clear architecture

Short-term convenience should never compromise the long-term design of the system.

---

# Event Log

## 2026-07-16

- Successful activation of environment-driven ports (PORT and HOST) with a default fallback to 8080.
- Implemented live inference streaming support (`stream=True`) in the `/infer` endpoint utilizing FastAPI `StreamingResponse` and Ollama async generator.
- Implemented inter-service token validation using a secure `X-Network-Auth-Token` header.
- Added `NETWORK_AUTH_TOKEN` (alias `NODE_NETWORK_AUTH_TOKEN`) environment variable configuration.
- Secured registration, heartbeat, and scheduling endpoints under dependency validation.