---
description: Host-agent rules for packages/node
paths: ["packages/node/**"]
---

# packages/node — the host agent

FastAPI. Local control API, telemetry, Docker sandbox runtime, Ollama-backed
inference.

- **It must not import scheduler internals.** It talks over the documented API and
  the mesh, nothing else.
- **The distributed inference path is not implemented.** `runtime.py` never assigns
  `self.inference_backend` anything but `EchoBackend`. The working path is the
  non-split one that proxies to Ollama. Do not describe split inference as working,
  and do not wire `LocalBoundaryEngine` into anything — it is a 120-token vocabulary
  over seeded random matrices.
- **Hardware figures are measured, never assumed.** Registration once hardcoded
  16 GB of VRAM for every node, so matchmaking filtered against fiction. Every probe
  degrades to `cpu-only` rather than blocking startup, and a CPU-only node must stay
  representable — that is why the VRAM floor is `ge=0`, not `gt=0`.
- **A Scheduler outage is survivable; a bug is not.** Registration failure is
  non-fatal and retries with exponential backoff plus **full jitter** — the fleet all
  retries the moment a Scheduler returns, so plain backoff lands a synchronised herd.
  Only `SchedulerError` is survivable; let real bugs abort startup.
- **The node re-reads its own model catalogue** and pushes only when the names
  changed. An unreachable Ollama keeps the previous catalogue rather than
  unadvertising the node.

Telemetry crosses the mesh as an AES-256-GCM envelope keyed on this node's own
`NODE_NETWORK_AUTH_TOKEN`. Never send an unsigned message that mutates registry state.
