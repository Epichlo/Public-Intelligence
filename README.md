# Public Intelligence

**Archived on 2026-08-21. Development has ended. This repository is a record, not a
product.**

It was an OpenAI-compatible control plane for hardware you already own: point it at
machines you or people you trust control, and get one authenticated
`/v1/chat/completions` endpoint that routes across all of them. Nodes dial *out* to a
coordinator and answer over that connection, so a node behind NAT needs no inbound port
forwarding.

The code works, within the limits set out below. Nobody ever used it. Both of those are
findings, and this file exists to state them plainly rather than leave a green test
badge to imply the first and hide the second.

Nothing here is maintained. There is no support, no roadmap, and no security response —
`SECURITY.md` describes a process that is no longer staffed. If you run this, you own
it.

---

## Why it ended

Not because it broke. Because the question underneath it was answered, and the answer
was no.

The project rested on a register of stated, falsifiable premises
([`docs/PREMISES.md`](docs/PREMISES.md)). Two of the load-bearing ones failed while the
engineering was succeeding:

- **P3 — the economics do not close.** `scripts/economics.py`, tested by
  `tests/test_economics.py`, puts a realistic host at **~$2.26 per 1M tokens against a
  ~$0.15 commodity price** — roughly 15×. The conclusion survives doubling every power
  and throughput input and tripling utilisation. That killed the marketplace, and with
  it the reason a stranger would contribute hardware
  ([D2](docs/decisions/D2-economics.md)).
- **P2 — NAT traversal is not a differentiator.** An external desk review
  ([`docs/review/desk-review-2026-08-14.md`](docs/review/desk-review-2026-08-14.md))
  found the falsifier true as written: single-user remote access to a home GPU is a
  solved, SEO-saturated problem, and Tailscale is the free answer. What survives is
  *cross-party pooling*, which Tailscale is single-tenant-shaped and does not do — but
  that relocates the whole load onto P1 (*someone wants to serve inference from hardware
  they own, across parties*), for which there is **no evidence at all**, only assumption.

So the remaining pitch was: a thing that costs 15× the alternative, solving a problem
that is already solved for the single-machine case, for a multi-party demand nobody had
demonstrated. The correct response to that is to stop, and write down why, which is what
this is.

The one question that could have changed the answer —
[D7](docs/decisions/D7-second-pair-of-eyes.md), *a second pair of eyes* — never got a
human reviewer. Every judgement in this repository, including this one, was made by a
single party. That is itself part of what went wrong.

---

## What worked

Evidence, not recollection. Test counts below were produced by running the suites in the
session that wrote this file; the CI result was read from the GitHub API, not inferred.

**The core loop runs.** A node registers with the Scheduler, heartbeats over an
authenticated Zenoh mesh, advertises the models Ollama actually has (measured hardware,
never a hardcoded guess), and survives the Scheduler being unreachable. The Scheduler
matchmakes, dispatches over the mesh, meters usage, and serves an OpenAI-shaped gateway
behind RS256 JWT auth. On 2026-08-11 a node on a **second physical machine** registered,
held a mesh session, and served a real completion dispatched over that mesh.

**The tests pass, and they were run here.**

| Suite | Result |
|---|---|
| `packages/scheduler/tests` | 397 passed |
| `packages/node/tests` | 260 passed, 1 skipped |
| `tests` (cross-package) | 249 passed |
| **Total** | **906 passed, 1 skipped** |

**CI is green.** Run **#33** on `main` at `e5d1e7c` completed **success**. The matrix is
3 operating systems × Python 3.11, 3.12 and 3.14, plus a fresh-clone job — 10 jobs.

*`STATUS.md` says CI is `UNVERIFIABLE`, and both are right.* That file asks the `gh`
CLI, and reports `UNVERIFIABLE` wherever `gh` is absent — which is the honest word for
"I did not look", and is also the word that reads like "probably fine". The run above
was read straight from the GitHub API instead. That gap is listed under what failed
below; it is the mechanism by which a red build sat under a published release for eight
days, and it was never fixed.

**Persistence does what it says.** SQLite backs the registry, node credentials, the
credit ledger, the usage meter and invites. Observations — heartbeats, telemetry, mesh
reachability — are deliberately *not* restored, because reviving them would make dispatch
prefer a Zenoh session that died with the process. Persist facts, not observations.

**Real security holes were found and closed**, most of them by moving cut features out of
live paths rather than by a scanner:

- Streamed completions were being republished onto the shared mesh **in plaintext**, on a
  key any peer could subscribe to with a `**` wildcard — while a whole protocol change had
  been spent AES-encrypting *telemetry* on that same mesh.
- The same router deadlocked after four chunks, because nothing in the repository has ever
  sent an ACK. Streaming was broken on precisely the deployment this was built for.
- Every Scheduler boot started an **unauthenticated Raft consensus plane** on a wildcard
  key. A crafted `AppendEntries` could evict any host or inject one — and an injected node
  receives other people's prompts.
- Every node opened an unauthenticated wildcard subscriber that deserialised
  attacker-controlled bytes and, for a `shm://` payload, unlinked host shared memory by
  attacker-supplied name.
- One header carried two meanings, so every node's "per-node" credential was the fleet
  secret ([D9](docs/decisions/D9-admission-is-not-identity.md)).

**Fabricated output was removed rather than hidden.** The gateway used to answer
`x-split-inference: true` with **HTTP 200** and text from a toy engine — asking it for the
capital of France returned `token_556`, which every OpenAI-compatible client renders as
the model's answer. It now answers **501**, and the ~250-line execution block was deleted
rather than left behind a flag, because dead code behind a disabled flag is how it shipped
in the first place. `/v1/batch` likewise answers 501 instead of pretending to queue.

**The verification layer is the part worth keeping.** One gate (`scripts/verify.sh`) is
the only definition of "does this pass", and CI invokes that file and nothing else — with
a test that fails if CI ever grows a second list. Around it: ratchets on source parity,
route inventory (an unguarded route fails the build), line endings read from the git
index, environment-variable binding, version parity, and the experimental quarantine
boundary. Agent-written claims go to `zones/claimed/`; only the gate writes
`zones/verified/`, because writing it requires having run the checks.

**Decisions were written down with their costs.** [`docs/decisions/`](docs/decisions/README.md)
(D1–D9) records what was chosen, what it cost, and what changed in the code. When a
premise was falsified, the roadmap changed rather than the story.

---

## What failed

**The differentiator was never proven.** No request has ever been served across a real
NAT boundary. The 2026-08-11 two-machine test put both machines on adjacent private
subnets of one network — no NAT was crossed. [D8](docs/decisions/D8-the-wedge.md) makes
traversal *the* product, so the single most load-bearing claim in the project stayed
unearned for its entire life. A phone hotspot would have tested it. That test was never
run.

**Split inference never existed.** `LocalBoundaryEngine` is a **120-token vocabulary —
116 words plus 4 special tokens — against a declared `vocab_size` of 32,000, with two
seeded `random.gauss` matrices**; its "speculative candidates" are
`(prev * 7 + 13) % vocab_size`. It produces plausible-looking tensors and no inference
happens. For weeks it was wired to the live gateway and its output was served as a
successful completion. The distance from it to real sharding is a rewrite, not a fix.

**An entire node execution path is dead code, and the tests conceal it.**
`Runtime._worker_loop` consumes a `task_queue`, runs an `InferenceBackend`, saves to an
`ArtifactStore` and reports over Zenoh. **Nothing in `src` ever enqueues a task** — only
tests do. `self.inference_backend` is only ever assigned `EchoBackend`
(`packages/node/src/node/runtime.py:282`), and `OllamaBackend` is never constructed
outside a test file. The real serving path is the FastAPI route
`packages/node/src/node/api/inference.py`, which uses a *different* class
(`clients/ollama.py`). So the backend abstraction has one implementation, zero production
callers, and a test named `test_end_to_end_pipeline` that feeds the queue by hand — an
end-to-end test of a path production never takes.

**The gate's failures arrived by absence, never by a red test.** Every falsification of
"the gate is the definition of does this pass" was something the gate did not look at:
`tests/` were not linted, then the website, then `scripts/`, then `.claude/`, then
`install.ps1`.

- **`install.ps1` has never been executed, by anything, ever.** `install.sh` gets a real
  run against a throwaway tree; the PowerShell installer is only ever *read*. Every
  Windows install defect to date (W1–W5, W8) was therefore found by a person on a real
  machine. One of them reported *"Installation Complete! Host Node is Ready"* over a
  failed install and exited 0 — the third time this repository shipped that defect, in a
  third language.
- **`docker-compose.test.yml` has never run.** Two defects were found in it by reading.
- **The repository could not read its own CI.** `STATUS.md` shells out to `gh` and reports
  `UNVERIFIABLE` where it is absent — which is honest, and reads like "probably fine". It
  is the mechanism by which **CI was red on `main` for eight days, across the `v1.0.0`
  release commit**, and nothing noticed. Confirmed from the API: runs #26–#29 all failed;
  the last green before them was #25 on 2026-08-07.
- **A branch gets no CI at all** — the workflow triggers only on `push` to `main` and on
  PRs.
- **A local gate is one OS and one interpreter** against CI's nine. Three defects were
  structurally invisible locally: a cp1252 encoding, CRLF line endings, and wall-clock
  resolution. Python **3.13 is not in the matrix**, despite "3.11–3.14" reading as a
  contiguous range.

**A ratchet that cannot see the thing it names is worse than no ratchet.** Two happened
here:

- `test_compose_env_matches_settings.py` claimed in its own docstring that it "would have
  caught" the `NODE_ID` / `NODE_NODE_ID` bug. Its helper blessed the broken variable. The
  file was fixed by hand and the test took the credit.
- **The `v1.0.1` tag names a tree that declares itself `1.0.0`.** All four packages agree
  with each other at `25fe60c`, so `test_every_package_declares_the_same_version` passes —
  it only compares the packages to *each other*, never to the tag that names them. V3's
  own stated principle was "a tag names one tree"; the fix converged the four packages on
  the *previous* version and stopped there. Left as found: bumping it now would produce a
  tree claiming to be `v1.0.1` that is not the released `v1.0.1`, which is the same
  confusion wearing a different hat.

**A number nobody checked propagated across five documents.** Every doc in this
repository described `LocalBoundaryEngine` as having a "155-word vocabulary" —
`ROADMAP.md`, `CLAUDE.md`, `experimental/README.md`, `.claude/rules/node.md`, and the
first draft of this file. The actual list holds **116 words plus 4 special tokens**,
against a declared `vocab_size` of 32,000. Counted at closure, in one command. The
figure was wrong from its first use and was copied outward four times, including into
the rules file that governs how agents work here. `CLAUDE.md` warns in its own words
that "prose cannot notice when it goes stale" and moves measurements into a generated
`STATUS.md` for exactly this reason; this number was never in scope of that mechanism,
so nothing measured it. It is corrected everywhere as of this commit.

**The rest of what is missing, stated without softening.** No content filtering. No
meaningful rate limiting — what exists is a per-instance abuse dampener, not a quota. No
backups. No way to revoke a JWT; they are stateless by design, and the mitigations are a
TTL cap and key rotation. Nothing verifies a node ran the model it *claims* — canaries
catch a host running no model, not one running the wrong one. Credits are an accounting
unit with no payout path, by decision. Nodes installed before D9 keep the old
credential weakness until upgraded, deliberately, so that no running host is stranded.
Four module pairs in `experimental/` remain duplicated, with drift ratcheted rather than
eliminated.

**And there was never a fleet.** No hosts, no traffic, no users. `docs/PREMISES.md` puts
it exactly right: *"Nobody has metered a real node in this fleet, because there is no
fleet."* Every green test exercised this system talking to itself.

---

## What we would tell someone starting this

1. **Test the load-bearing claim first, with the cheapest possible experiment.** The NAT
   crossing was the entire product and it needed a phone hotspot and an afternoon. It was
   never done, across four months, while 906 tests were written around it.
2. **Do the arithmetic before the architecture.** `scripts/economics.py` is about a
   hundred lines. Run at the start, it would have redirected the project. Run at month
   three, it ended it.
3. **A test suite measures regression, never premise.** A ratchet asks "did this get
   worse"; a test asks "does it still do what I said". Neither can ask "should this exist
   at all". 906 passing tests said nothing about whether anyone wanted this.
4. **Absence is the failure mode, not failure.** Everything that went wrong here was
   outside what the gate looked at. When adding a check, the useful question is not "does
   this pass" but "what is still unwatched".
5. **Never let unfinished plumbing touch a live path.** Every serious security defect in
   this repository came from cut-feature code left wired in. A disabled flag is not a
   boundary; a different directory with an enforced import ban is.
6. **Get the second pair of eyes early.** D7 was open from the start and stayed open. A
   process that is rigorous and self-contained is still self-contained.

---

## Repository layout

| Path | What it is |
|---|---|
| `packages/scheduler/` | FastAPI control plane: registry, matchmaking, OpenAI gateway, Zenoh router |
| `packages/node/` | FastAPI host agent: local control API, telemetry, Ollama-backed inference |
| `packages/website/` | Next.js dashboard, playground, and public pages |
| `packages/shared/` | The modules both services must agree on byte for byte (`pi_shared`) |
| `experimental/` | Quarantined cut features. **Nothing here is part of the shipped system.** |
| `specs/` | One document per change: what it does, why, and what is out of scope |
| `docs/decisions/` | The product decisions (D1–D9), and what each one costs |
| `docs/PREMISES.md` | Every load-bearing assumption, with its falsifier |
| `docs/historical/` | Superseded design documents. **They describe intentions as if built.** |
| `zones/` | `claimed/` is what an agent believed; `verified/` is what the gate measured |

## Running it anyway

The code still runs. One venv for everything:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e packages/shared \
  -e "packages/node[dev]" -e "packages/scheduler[dev]"
./scripts/verify.sh          # the single gate: lint, types, tests, security, installer
```

The three suites must be invoked separately — a single `pytest` across all of them fails
on a conftest path collision:

```bash
.venv/bin/python -m pytest packages/scheduler/tests -q
.venv/bin/python -m pytest packages/node/tests -q
.venv/bin/python -m pytest tests -q
```

Hosting a node needs Ollama running with at least one model pulled, and — against a
Scheduler that sets them — a fleet token and an invite code:

```bash
./install.sh --start        # or scripts/bootstrap.sh for the one-line path
```

`STATUS.md` is generated by `python3 scripts/generate_status.py` and should never be
edited by hand.

## Licence

[Apache-2.0](LICENSE). Patent grant included; warranty disclaimed. The project is
archived and unmaintained: there is no security response process, and issues and pull
requests are not being monitored.
