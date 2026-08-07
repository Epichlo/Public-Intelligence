# DEVELOPMENT WORKFLOW

## Purpose

This document defines the standard development workflow for Public Intelligence.

It applies equally to human contributors and AI coding agents.

The objective is to produce high-quality software through deliberate engineering rather than rapid iteration.

---

# Development Philosophy

Research before design.

Design before implementation.

Implementation before optimization.

Optimization before scale.

Every stage builds upon the previous one.

---

# Standard Workflow

Every feature should follow the same process.

```
Research
    ↓
Design
    ↓
Implementation Plan
    ↓
Approval
    ↓
Implementation
    ↓
Verification
    ↓
Documentation
    ↓
Commit
```

Skipping steps should be the exception rather than the rule.

---

# Before Every Task

Before making any change:

1. Understand the purpose of the task.
2. Read the relevant documentation.
3. Inspect the existing implementation.
4. Identify the affected components.
5. Explain the proposed solution.
6. Wait for approval before significant architectural changes.

Never begin implementation without understanding the existing system.

---

# During Implementation

While implementing:

- Change only what is necessary.
- Preserve architectural consistency.
- Prefer existing patterns over introducing new ones.
- Avoid unrelated refactoring.
- Keep changes focused on a single feature.

Small, well-defined changes are preferred over large, sweeping modifications.

---

# Verification

Before considering a task complete:

- Ensure the project builds successfully.
- Run linting.
- Run tests where available.
- Check for obvious regressions.
- Verify that the requested feature behaves as intended.

Never assume correctness without verification.

---

# Documentation

Documentation should evolve alongside the code.

Whenever a significant architectural decision is made:

- Update the relevant documentation.
- Explain the reasoning.
- Record important trade-offs.

Documentation is part of the implementation.

---

# Git Workflow

Commits should represent one logical unit of work.

Examples:

- Initialize website foundation
- Implement global layout and navigation
- Add scheduler node registration

Avoid combining unrelated changes into a single commit.

Commit messages should describe the feature, not the implementation details.

---

# AI Agent Responsibilities

AI agents are expected to:

- Read project documentation before making changes.
- Explain implementation plans.
- Ask for clarification instead of making assumptions.
- Preserve architectural consistency.
- Avoid unnecessary dependencies.
- Respect existing coding conventions.
- Verify changes before completion.
- Summarize modified files.

AI agents are collaborators, not autonomous decision-makers.

---

# Human Responsibilities

Human contributors remain responsible for:

- Project vision.
- Architectural decisions.
- Technical direction.
- Reviewing significant changes.
- Approving major design decisions.

AI assists implementation but does not replace engineering judgment.

---

# Definition of Done

A task is complete only when:

- The requested feature is implemented.
- The project builds successfully.
- Verification passes.
- Documentation is updated if necessary.
- Changes are summarized.
- The work is committed with a clear commit message.

Only then should development move to the next task.