# Public Intelligence

**An OpenAI-compatible control plane for hardware you already own.**

Point it at machines you or people you trust control — a workstation with a GPU, a
lab's spare box, three laptops in a research group — and it gives you one
authenticated `/v1/chat/completions` endpoint that routes across all of them. Nodes
dial *out* to the coordinator and answer over that connection, so a node behind NAT
needs no inbound port forwarding of its own — the coordinator is the one machine that
has to be reachable. How well that traverses a *real* NAT boundary is still unproven;
see "What is actually true" below.

It is not a marketplace and there is no network to join. You run both halves — it is
**self-hosted infrastructure for hardware you own**, not a service. See
[`docs/decisions/D8-the-wedge.md`](docs/decisions/D8-the-wedge.md) for why that is the
product, and [D2](docs/decisions/D2-economics.md) for the arithmetic that ruled out
the alternative.

**This is the v1.0.0 feature-complete milestone — not a maturity claim.** It means the
v1 scope is built and the gate is green, not that anyone has run this in anger. Read
"What is actually true" before relying on anything here.

## What is actually true, as of 2026-08-15

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

- **No node has served a request across a real NAT boundary.** On 2026-08-11 a node on
  a *second physical machine* registered and served a real request over the mesh — but
  both machines were on one LAN, so no NAT was crossed (`ROADMAP.md`, 1.5). A later
  attempt to test across a real NAT was blocked by the coordinator sitting on a managed
  network with no inbound reachability. The path is architecturally correct for NAT
  (nodes dial out) and works on a LAN; it is **unproven on genuinely separate
  networks**. This is the most load-bearing unproven claim in the project — see
  [`docs/PREMISES.md`](docs/PREMISES.md), P2.
- **Split inference, layer sharding, FP8 compression, speculative decoding and
  KV-cache checkpointing are not implemented.** They are cut from v1. The gateway
  answers **501** if you ask for split inference. It used to answer 200 with invented
  text; that was removed on 2026-08-07.
- **Credits are an accounting unit, not a currency.** They are not redeemable and
  there is no payout path — not "not yet", but a decision
  ([D2](docs/decisions/D2-economics.md)).
- **There is no content filtering, no meaningful rate limiting, and no backups**, and
  nothing verifies that a node ran the model it claims.
  [`docs/OPERATING.md`](docs/OPERATING.md) lists what you take on by running this.

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

A first external pass — two independent AI desk reviews of the market premises — is
recorded in [`docs/review/`](docs/review/). It found the demand for *cross-party
pooling* unevidenced and the *remote-access* problem already well solved by Tailscale,
which is why the honest framing of this project is self-hosted infrastructure for your
own trusted hardware, not a network to join. That is still not the human second
opinion D7 asks for.

## Host a node

One command fetches the project, installs it, and leaves a **running** node:

```bash
curl -fsSL https://raw.githubusercontent.com/Epichlo/Public-Intelligence/main/scripts/bootstrap.sh \
  | bash -s -- --scheduler-url https://your-scheduler --fleet-token TOKEN --invite-code CODE
```

Everything after `bash -s --` is forwarded to `install.sh` (`install.sh --help` lists the
flags). It clones into `~/public-intelligence` (override with `PI_DIR`), starts the
daemon, and re-running it updates in place. Prefer to read what runs first? Clone the
repo and run `./install.sh --start` yourself — the two paths are identical. Manage the
daemon with `./scripts/launch_host_node.sh {status,logs,stop}`.

You need Ollama running with at least one model pulled; and, against a Scheduler that
sets them, a fleet token and an invite code from its operator.

## Repository layout

| Path | What it is |
|---|---|
| `packages/scheduler/` | FastAPI control plane: registry, matchmaking, OpenAI gateway, Zenoh router |
| `packages/node/` | FastAPI host agent: local control API, telemetry, Ollama-backed inference |
| `packages/website/` | Next.js dashboard and playground |
| `specs/` | One document per change: what it does, why, and what is out of scope |
| `docs/decisions/` | The product decisions, and what each one costs |
| `docs/historical/` | Superseded design documents. **They describe intentions as if built.** |

## Developing it

One venv for everything:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e packages/shared \
  -e "packages/node[dev]" -e "packages/scheduler[dev]"
./scripts/install-hooks.sh
./scripts/verify.sh          # the single gate: lint, types, tests, security, installer
```

`scripts/verify.sh` is the only definition of "does this pass"; CI runs that file
and nothing else. See `CONTRIBUTING.md` for how to work here and `VERIFY.md` for what
a completion claim has to be backed by.

## Licence

[Apache-2.0](LICENSE). Patent grant included; warranty disclaimed. Security reports go
through [`SECURITY.md`](SECURITY.md), not the issue tracker.
