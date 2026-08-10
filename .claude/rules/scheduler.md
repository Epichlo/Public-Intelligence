---
description: Control-plane rules for packages/scheduler
paths: ["packages/scheduler/**"]
---

# packages/scheduler — the control plane

FastAPI. Node registry, matchmaking, the OpenAI-compatible gateway
(`/v1/chat/completions`, `/v1/models`, `/v1/batch`), and the Zenoh router.

- **It must not contain inference logic.** It matches, dispatches, meters, and
  accounts. Model execution belongs to `packages/node`.
- **Every route is authenticated unless it is a probe.** `/health` and
  `/health/ready` are public because a probe needing a secret reports unhealthy when
  the secret is wrong. Everything else takes a dependency. There is a route-inventory
  ratchet; if you add an unguarded route it fails, and that is the ratchet working.
- **Gateway auth is RS256 with `kid`-based selection.** `kid` is a hint for choosing
  a key, never an assertion of validity — an unknown one must fall through to trying
  every active key, and a token verifying under none is refused. That distinction is
  how a `kid`-aware verifier turns into a bypass.
- **Do not fabricate a response.** `/v1/batch` and the old split-inference path both
  returned plausible text having run no model. Both are now 501, and the code was
  deleted rather than left behind a flag, because dead code behind a disabled flag is
  how it happened. A 501 is honest; a synthesised completion is not.
- **`mesh_protocol` and `mesh_auth` live in `packages/shared` as `pi_shared`.** One
  copy. If you are about to add a second, that is the bug.

State is a `SchedulerStore` Protocol with a SQLite implementation. Persist facts, not
observations: nodes and credentials survive a restart; heartbeats, telemetry and mesh
reachability must not, because restoring them makes dispatch prefer a session that
died with the process.
