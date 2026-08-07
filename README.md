# Public Intelligence

**An OpenAI-compatible control plane for hardware you already own.**

Point it at machines you or people you trust control — a workstation with a GPU, a
lab's spare box, three laptops in a research group — and it gives you one
authenticated `/v1/chat/completions` endpoint that routes across all of them,
**including the ones behind NAT**, with no port forwarding and no VPN.

It is not a marketplace and there is no network to join. You run both halves. See
[`docs/decisions/D8-the-wedge.md`](docs/decisions/D8-the-wedge.md) for why that is the
product, and [D2](docs/decisions/D2-economics.md) for the arithmetic that ruled out
the alternative.

**This is pre-alpha.** That sentence is doing real work — read "What is actually
true" before relying on anything here.

## What is actually true, as of 2026-08-07

Verified, not aspirational. `STATUS.md` is generated from real test runs; this
section summarises it in prose.

**Works:** a node registers with the Scheduler, heartbeats over an authenticated
Zenoh mesh, advertises the models Ollama actually has, and survives the Scheduler
being unreachable. The Scheduler matchmakes, dispatches over the mesh (which is how
a node behind NAT is reachable at all), and exposes an OpenAI-shaped gateway behind
RS256 JWT auth. State can persist across restarts. CI runs the gate on Linux, macOS
and Windows across Python 3.11–3.14; `STATUS.md` records the last measured result and
the commit it covers.

**Does not work, and is not claimed to:**

- **No node on a genuinely separate machine has ever served a request.** The mesh
  transport is built and tested against a real Zenoh router, but in one process on
  loopback (`ROADMAP.md`, 1.5). This is the single most load-bearing unproven claim
  in the project — see [`docs/PREMISES.md`](docs/PREMISES.md), P2.
- **Split inference, layer sharding, FP8 compression, speculative decoding and
  KV-cache checkpointing are not implemented.** They are cut from v1. The gateway
  answers **501** if you ask for split inference. It used to answer 200 with invented
  text; that was removed on 2026-08-07.
- **Credits are an accounting unit, not a currency.** They are not redeemable and
  there is no payout path — not "not yet", but a decision
  ([D2](docs/decisions/D2-economics.md)).
- **There is no content filtering, no meaningful rate limiting, and no backups.**
  `VERIFY.md` step 3 lists the known auth bypasses and default credentials, with
  `file:line`. They are pre-existing and tracked, not hidden.

## What this project has decided, and what it hasn't

The eight product questions this code had been assuming answers to are answered in
[`docs/decisions/`](docs/decisions/README.md). The short version: invite-only trusted
hosts, no marketplace, no operated network, one coordinator, and a self-hosted pitch.

**One question is still open and cannot be closed from inside:**
[D7](docs/decisions/D7-second-pair-of-eyes.md) asks for a second pair of eyes. Every
judgement here has been made by one party, and the verification process — strong as it
is — is structurally incapable of catching a wrong premise. The assumptions are laid
out in [`docs/PREMISES.md`](docs/PREMISES.md) specifically so they can be attacked.
**If you disagree with one, that is the contribution.**

## Repository layout

| Path | What it is |
|---|---|
| `packages/scheduler/` | FastAPI control plane: registry, matchmaking, OpenAI gateway, Zenoh router |
| `packages/node/` | FastAPI host agent: local control API, telemetry, Ollama-backed inference |
| `packages/website/` | Next.js dashboard and playground |
| `specs/` | One document per change: what it does, why, and what is out of scope |
| `docs/decisions/` | The product decisions, and what each one costs |
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
and nothing else. See `CONTRIBUTING.md` for how to work here and `VERIFY.md` for what
a completion claim has to be backed by.

## Licence

[Apache-2.0](LICENSE). Patent grant included; warranty disclaimed. Security reports go
through [`SECURITY.md`](SECURITY.md), not the issue tracker.
