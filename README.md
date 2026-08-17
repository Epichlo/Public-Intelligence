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

**This is the v1.0.1 feature-complete milestone — not a maturity claim.** It means the
v1 scope is built and the gate is green on every supported platform, not that anyone
has run this in anger. Read "What is actually true" before relying on anything here.

## What is actually true, as of 2026-08-17

Verified, not aspirational. `STATUS.md` is generated from real test runs; this
section summarises it in prose.

**Works:** a node registers with the Scheduler, heartbeats over an authenticated
Zenoh mesh, advertises the models Ollama actually has, and survives the Scheduler
being unreachable. The Scheduler matchmakes, dispatches over the mesh (which is how
a node behind NAT is reachable at all), and exposes an OpenAI-shaped gateway behind
RS256 JWT auth. State can persist across restarts.

CI runs the gate on Linux, macOS and Windows across Python 3.11–3.14 — ten jobs — and
as of `25fe60c` all ten pass. Worth stating plainly rather than as a badge: **they did
not, from 2026-08-09 to 2026-08-17.** The three Windows legs were red for eight days,
across the `v1.0.0` release commit, and nothing in this repository noticed. See
"What we cannot see" below, because that gap is more instructive than the bug was.

**If `STATUS.md` and the paragraph above disagree, they are both right.** That claim
comes from reading the run directly; `STATUS.md` reports `UNVERIFIABLE` whenever it is
generated on a machine without the `gh` CLI, because that is the only way it knows how
to ask. Regenerate it where `gh` is installed and authenticated and the line resolves.

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
  nothing verifies that a node ran the model it claims. The rate limiter is a
  per-instance abuse dampener, not a quota. Canary checks catch a host running *no*
  model; they cannot catch a host running the *wrong* one.
  [`docs/OPERATING.md`](docs/OPERATING.md) lists what you take on by running this.
- **`/v1/batch` is not implemented** — it answers 501. It is authenticated and
  tenant-scoped, because those were real fixes to a real hole, but it dispatches
  nothing.
- **JWTs cannot be revoked.** They are stateless by design; the mitigations are a
  server-enforced TTL cap and key rotation. There is no revoke button and this is
  said plainly rather than implied away.
- **Nodes installed before [D9](docs/decisions/D9-admission-is-not-identity.md) keep
  the old weakness** — one header meaning both fleet admission and node identity —
  until they are upgraded. That is a deliberate compatibility choice, not an
  oversight: refusing them would strand every running host.

## What we cannot see

Distinct from the list above, which is what does not *work*. This is what this
project's own verification **cannot observe** — the gaps where a defect would not be
caught by anything here. It is written down because
[`docs/PREMISES.md`](docs/PREMISES.md) P8 records that every falsification of "the
gate is the definition of does this pass" has arrived by **absence rather than
failure**, and an unlisted absence is indistinguishable from an all-clear.

- **`install.ps1` has never been executed, by anything, ever.** `install.sh` gets a
  real run against a throwaway tree (`scripts/verify_install.sh`); the PowerShell
  installer is only ever *read* — `scripts/audit_system.py` greps it for strings and
  `tests/test_installer_parity.py` ratchets its structure. Every Windows install
  defect to date (W1–W5, W8) was therefore found by a person on a real machine, not
  by the gate. Assume the next one will be too.
- **The repository cannot read its own CI.** `scripts/generate_status.py` shells out
  to `gh`; where `gh` is absent it reports `UNVERIFIABLE — cannot query run history`.
  That is honest, and it reads like "no known problem". It is the mechanism by which
  a red build sat under a published release for eight days. **The fix is known and
  not yet made:** fall back to the GitHub REST API so the answer does not depend on
  which machine regenerated the file.
- **Work on a branch is unverified until it becomes a pull request.** The workflow
  triggers only on `push` to `main` and on PRs, so a feature branch gets no CI at all.
- **The local gate is one operating system and one interpreter.** CI is nine legs; a
  developer's run is one. Platform-specific defects are structurally invisible
  locally, and there have now been three: a cp1252 text encoding (2.9), CRLF line
  endings (V1), and wall-clock resolution (V2). A local `PASS` is a weaker claim than
  a CI `PASS` and the gate says so in its own output.
- **The gate skips checks it cannot run**, naming them as `DID NOT RUN`: a missing
  interpreter, `shellcheck` if absent, the website suite without `node_modules`. The
  honesty is real; the coverage still is not there.
- **`docker-compose.test.yml` has never run.** Two defects were found in it by
  reading (`tests/test_compose_env_matches_settings.py`) rather than by executing it.
- **Four module pairs in `experimental/` remain duplicated** — `quantization`,
  `local_boundary`, `kv_cache`, `transport`. Drift is ratcheted, not eliminated.
- **No human outside this project has reviewed any of it.** Two independent AI desk
  reviews of the market premises are in [`docs/review/`](docs/review/) and they
  converged, which is evidence but not independence.

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
