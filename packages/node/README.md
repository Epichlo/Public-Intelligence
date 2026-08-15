# Public Intelligence Node

A Public Intelligence Node is a compute worker that registers with the Scheduler,
advertises the models Ollama actually has, executes inference locally, and holds an
authenticated Zenoh mesh session so it is reachable even from behind NAT — it dials
*out* to the coordinator rather than listening for inbound connections.

Part of the **`public-intelligence` monorepo** (Scheduler, Node, and Website were merged
into `packages/` on 2026-08-04). This document describes `packages/node`.

Version 1 establishes the complete lifecycle of a compute node. The distributed
(split) inference path is **not** implemented; the working path proxies to Ollama, and
that is the only backend `runtime.py` assigns.

---

## Current Features

- Scheduler registration
- Heartbeats
- Ollama integration
- Local inference API
- Runtime lifecycle management
- Graceful shutdown
- End-to-end demonstration
- Comprehensive test suite

---

## Architecture

```text
            Scheduler

               ▲

 Registration / Heartbeats

               │

               ▼

        Public Intelligence Node

               │

               ▼

          Ollama Client

               │

               ▼

             Ollama
```

---

## Running

Start Ollama

```bash
ollama serve
```

Run the Node

```bash
python -m node.main
```

---

## Demo

A walkthrough of the first working prototype is available on YouTube:
[Public Intelligence v1 Demo](https://www.youtube.com/watch?v=cGDWpOArB5I)

This video demonstrates the end-to-end integration of the Website, Scheduler, Node (showing the current v1 implementation), registration, heartbeats, and local inference.

A local end-to-end text demonstration is also available in [examples/demo.md](examples/demo.md).

---

## Version

Current Release

```
v1.0.0
```

---

## Future Work

Automatic hardware discovery shipped in v1 — the installer probes CPU, RAM, and GPU,
and registration advertises the measured figures rather than a hardcoded guess. What is
**not** in v1: split/distributed inference (the node runs whole models, not shards), and
a proven real-NAT path (the mesh works on a LAN; crossing a real NAT is unverified).

---

## Related components

Part of the `public-intelligence` monorepo: `packages/scheduler` (control plane) and
`packages/website` (dashboard). The pre-monorepo standalone repositories are archived
and tagged `pre-monorepo-2026-08-04`.

---

## License

Apache 2.0