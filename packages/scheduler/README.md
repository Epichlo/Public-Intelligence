# Public Intelligence Scheduler

**Archived on 2026-08-21 along with the rest of the project. See the root
[`README.md`](../../README.md) for what worked, what failed, and why it stopped.**

The Scheduler is the control plane. It maintains a registry of compute nodes, receives
heartbeats over an authenticated Zenoh mesh, matchmakes requests to a node that has the
requested model, dispatches over the mesh (which is how a node behind NAT is reachable),
and exposes an OpenAI-compatible gateway.

It does not run inference itself — model execution belongs to the Node. It matches,
dispatches, meters, and accounts.

Part of the **`public-intelligence` monorepo** (the Scheduler, Node, and Website were
merged into `packages/` on 2026-08-04). This document describes `packages/scheduler`.

---

## Demo

A walkthrough of the first working prototype is available on YouTube:
[Public Intelligence v1 Demo](https://www.youtube.com/watch?v=cGDWpOArB5I)

This video demonstrates the end-to-end integration of the Website, Scheduler (showing the current v1 implementation), Node, registration, heartbeats, and local inference.

---

## Current Features

- Node registration and unregistration, admission-controlled (invite codes, decision D4)
- Two-secret registration (decision D9): a shared admission token, and each node's own
  credential stored separately and used to verify that node's mesh envelopes
- Heartbeats and telemetry over an authenticated Zenoh mesh
- Matchmaking to a node that actually advertises the requested model
- Dispatch over the mesh, with HTTP as a fallback
- OpenAI-compatible gateway (`/v1/chat/completions`, `/v1/models`) behind RS256 JWT auth
- Persistent store (SQLite): registry, credentials, credit ledger, usage meter, invites
- Usage metering that never records prompt or completion text
- Route-inventory ratchet: an unguarded route fails the build
- Comprehensive test suite; one gate (`scripts/verify.sh`) for lint, types, tests,
  security, and a real installer run

---

## Architecture

```text
               Client

                  │

                  ▼

            Scheduler API

                  │

                  ▼

          Scheduling Algorithm

                  │

                  ▼

            Node Registry

                  ▲

      Registration / Heartbeats

                  │

                  ▼

                 Nodes
```

---

## Running

```bash
python -m scheduler.main
```

or

```bash
uvicorn scheduler.main:app --reload
```

---

## Version

`pyproject.toml` declares **`1.0.0`**. The last release tag is **`v1.0.1`** — the two do
not match. That discrepancy is recorded rather than papered over in the root
[`README.md`](../../README.md); the version-parity ratchet compares the four packages to
each other, never to the tag that names them.

---

## What was never finished

There is no roadmap — the project is archived. Request routing, mesh dispatch and
OpenAI-compatible serving all shipped. What did not, and was never pretended to (see the
root [`README.md`](../../README.md) and [`docs/PREMISES.md`](../../docs/PREMISES.md)):

- **A proven real-NAT path.** The mesh works on a LAN; crossing a real NAT boundary was
  never demonstrated (`ROADMAP.md`, 1.5) — and it was the differentiator the project
  rested on.
- **Split / distributed inference** (sharding one model across nodes). Cut from v1; the
  gateway answers `501`, it does not fabricate a completion. It used to answer `200` with
  text from a toy engine.
- **`/v1/batch`.** Authenticated and tenant-scoped, because those were real fixes to a
  real hole — but it answers `501` and dispatches nothing.
- **Any payout / marketplace.** Credits are an accounting unit, not a currency
  ([D2](../../docs/decisions/D2-economics.md)).
- **Execution integrity beyond admission control.** Canaries catch a host running *no*
  model; nothing catches one running the *wrong* one.
- **Revocable tokens, content filtering, real quotas, or backups.** None of these exist.
  JWTs are stateless by design; the mitigations are a TTL cap and key rotation.

---

## Related components

Part of the `public-intelligence` monorepo: `packages/node` (host agent) and
`packages/website` (dashboard). The pre-monorepo standalone repositories are archived
and tagged `pre-monorepo-2026-08-04`.

---

## License

Apache 2.0