# Public Intelligence

A distributed compute control plane: a host runs a node on their own hardware, and
a developer sends an OpenAI-compatible request that the network routes to one of
those nodes.

**This is pre-alpha and not usable by anyone yet.** That sentence is doing real
work — see "What is actually true" below before relying on anything here.

## What is actually true, as of 2026-08-07

Verified, not aspirational. `STATUS.md` is generated from real test runs; this
section summarises it in prose.

**Works:** a node registers with the Scheduler, heartbeats over an authenticated
Zenoh mesh, advertises the models Ollama actually has, and survives the Scheduler
being unreachable. The Scheduler matchmakes, dispatches over the mesh (which is how
a node behind NAT is reachable at all), and exposes an OpenAI-shaped gateway behind
RS256 JWT auth. State can persist across restarts. 664 tests, green on Linux, macOS
and Windows across Python 3.11–3.14.

**Does not work, and is not claimed to:**

- **There is no live network.** The hosted Scheduler does not respond, and
  `bootstrap.public-intelligence.net` does not resolve. The installer currently
  points hosts at both. Until that is settled (`ROADMAP.md`, D6/C1), the only
  working configuration is entirely local.
- **No node on a genuinely separate machine has ever served a request.** The mesh
  transport is built and tested against a real Zenoh router, but in one process on
  loopback (`ROADMAP.md`, 1.5).
- **Split inference, layer sharding, FP8 compression, speculative decoding and
  KV-cache checkpointing are not implemented.** They are cut from v1. The gateway
  answers **501** if you ask for split inference. It used to answer 200 with
  invented text; that was removed on 2026-08-07.
- **Nothing is metered and no credit is earned.** The ledger is durable and empty.
- **There is no way for a developer to obtain a credential** except an operator
  script.

## What this project has not decided yet

`ROADMAP.md` opens with **Stage D**, which gates all further feature work. Those are
open product questions, not tasks — most importantly how a requester can know a node
really ran the model it was paid for, and whether the economics close at all. Until
they are answered, treat the architecture here as provisional.

## Repository layout

| Path | What it is |
|---|---|
| `packages/scheduler/` | FastAPI control plane: registry, matchmaking, OpenAI gateway, Zenoh router |
| `packages/node/` | FastAPI host agent: local control API, telemetry, Ollama-backed inference |
| `packages/website/` | Next.js dashboard and playground (**no test harness yet**) |
| `specs/` | One document per change: what it does, why, and what is out of scope |
| `docs/historical/` | Superseded design documents. **They describe intentions as if built.** |

## Running it

One venv for everything:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e "packages/node[dev]" -e "packages/scheduler[dev]"
./scripts/install-hooks.sh
./scripts/verify.sh          # the single gate: lint, types, tests, security, installer
```

`scripts/verify.sh` is the only definition of "does this pass"; CI runs that file
and nothing else. See `CLAUDE.md` for how to work here and `VERIFY.md` for what a
completion claim has to be backed by.

## Licence

**None yet.** No licence file has been added, which means default copyright applies
and you do not currently have permission to use, modify, or redistribute this. That
is a pending decision (`ROADMAP.md`, N3), not an intent to restrict.
