# Public Intelligence Node

**Archived on 2026-08-21 along with the rest of the project. See the root
[`README.md`](../../README.md) for what worked, what failed, and why it stopped.**

A Public Intelligence Node is a compute worker that registers with the Scheduler,
advertises the models Ollama actually has, executes inference locally, and holds an
authenticated Zenoh mesh session so it is reachable even from behind NAT — it dials
*out* to the coordinator rather than listening for inbound connections.

Part of the **`public-intelligence` monorepo** (Scheduler, Node, and Website were merged
into `packages/` on 2026-08-04). This document describes `packages/node`.

Version 1 establishes the complete lifecycle of a compute node. The distributed
(split) inference path is **not** implemented.

## Which path actually serves a request

Worth stating precisely, because this file got it wrong until 2026-08-21. It used to say
the Ollama proxy was "the only backend `runtime.py` assigns". It is not a `runtime.py`
backend at all, and there are two separate Ollama integrations:

- **The live path** is the FastAPI route `src/node/api/inference.py`, which calls
  `clients/ollama.py` (`OllamaClient`). This is what serves every real request.
- **The `backends/` abstraction is dead code in production.** `runtime.py:282` assigns
  `self.inference_backend` an `EchoBackend` and nothing else, ever; `OllamaBackend` is
  never constructed outside a test file. `Runtime._worker_loop` consumes a `task_queue`
  that **nothing in `src` ever enqueues onto** — only tests do, including the one named
  `test_end_to_end_pipeline`, which is an end-to-end test of a path production never
  takes.

So `backends/base.py` is an interface with one implementation and zero production
callers. It was written to make a second backend survivable and never got one.

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

`pyproject.toml` declares **`1.0.0`**. The last release tag is **`v1.0.1`** — the two do
not match. That discrepancy is recorded rather than papered over in the root
[`README.md`](../../README.md); the version-parity ratchet compares the four packages to
each other, never to the tag that names them.

---

## What was never finished

There is no future work — the project is archived. What did not get done:

- **A proven real-NAT path.** The mesh works on a LAN, and on 2026-08-11 a node on a
  second physical machine served a real request over it. Both machines were on adjacent
  subnets of one network, so **no NAT boundary was ever crossed** — and NAT traversal was
  the differentiator the whole project rested on.
- **Split / distributed inference.** Cut from v1; the node runs whole models, never
  shards. The gateway answers `501` rather than fabricating a completion.
- **A second inference backend.** `backends/base.py` exists to make one survivable and
  never got one, so the abstraction is untested against reality.

Automatic hardware discovery *did* ship: the installer probes CPU, RAM and GPU, and
registration advertises the measured figures rather than a hardcoded guess.

---

## Related components

Part of the `public-intelligence` monorepo: `packages/scheduler` (control plane) and
`packages/website` (dashboard). The pre-monorepo standalone repositories are archived
and tagged `pre-monorepo-2026-08-04`.

---

## License

Apache 2.0