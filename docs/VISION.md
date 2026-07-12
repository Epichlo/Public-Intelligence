# Public Intelligence Node

## Vision

The Public Intelligence Node is the compute worker of the Public Intelligence network.

It enables anyone with compatible hardware to contribute compute resources to a globally distributed AI infrastructure.

A Node is responsible for hosting local AI models, reporting its capabilities and health to the Scheduler, and executing inference requests assigned to it.

The Node does not participate in scheduling or distributed coordination. Its responsibility is to reliably execute inference workloads and expose its capabilities to the network.

---

## Purpose

The purpose of the Node is to transform an ordinary computer into a participant in the Public Intelligence network.

Every Node contributes one or more locally hosted AI models that can be scheduled for inference.

The Scheduler decides where requests should execute.

The Node executes those requests.

---

## Responsibilities

A Node is responsible for:

- Hosting local AI models.
- Registering itself with the Scheduler.
- Sending periodic heartbeat updates.
- Reporting hardware capabilities.
- Accepting inference requests.
- Executing local inference.
- Returning generated responses.
- Gracefully shutting down and unregistering when possible.

---

## Non-Responsibilities

The Node is NOT responsible for:

- Scheduling requests.
- Choosing which node should execute a request.
- Load balancing.
- Geographic routing.
- Distributed coordination.
- Global system state.
- Persistent storage.
- User authentication.

These responsibilities belong to other components of Public Intelligence.

---

## Design Philosophy

The Node should remain small, reliable, and predictable.

Every feature should support one of three goals:

1. Accurate reporting of local resources.
2. Reliable execution of inference.
3. Simple communication with the Scheduler.

Business logic should remain minimal.

Decision making belongs to the Scheduler.

---

## Long-Term Vision

A future Public Intelligence network may consist of thousands of Nodes distributed across the world.

Each Node contributes compute while remaining independently owned and operated.

Together these Nodes form a decentralized AI infrastructure capable of serving open-source language models without relying on centralized cloud providers.

The Node software should remain lightweight, transparent, and easy to deploy so that anyone can contribute compute to the network.

---

## Repository Goal

This repository implements a single Public Intelligence Node.

Its purpose is to provide reliable local inference while integrating seamlessly with the Scheduler and the rest of the Public Intelligence ecosystem.