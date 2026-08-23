# Premise register

Every load-bearing assumption this project rests on, stated as a falsifiable claim.

This exists because of [D7](decisions/D7-second-pair-of-eyes.md). The verification
process here is strong at catching regressions and **structurally incapable of
catching a wrong premise** — a ratchet asks "did this get worse", a test asks "does
it still do what I said", and neither can ask "should it do this at all". Every
judgement in this repository has been made by one party.

The purpose of this file is to make the assumptions attackable directly, so a
reviewer arriving cold does not have to reverse-engineer them out of 14,000 lines of
code. **If you disagree with one of these, that is the contribution.** Open an issue
naming the premise number.

Each premise has: the claim, what it supports, the evidence, and **what would falsify
it**. A premise with no falsifier is a belief, and is marked as one.

---

## P1 — Someone wants to serve inference from hardware they own

**Supports:** the entire project.
**Evidence:** Ollama and LM Studio have large user bases; the demand for local
inference is real. Data-residency requirements are real and common in regulated work.
**Falsifier:** local-inference users are satisfied by one machine and never need
routing, auth, or a fleet — in which case this is a solution to a problem people work
around trivially.
**Confidence:** medium. The *local inference* premise is well evidenced. The
*federation across several machines* premise is the assumed part, and it is the one
[D8](decisions/D8-the-wedge.md) rests on.

## P2 — NAT traversal for GPU hosts is the differentiator

**Supports:** [D8](decisions/D8-the-wedge.md); the whole Zenoh transport (ROADMAP 1.1).
**Evidence:** reaching a machine behind a home or campus NAT without port forwarding
is genuinely awkward, and the alternatives (Tailscale, ngrok, a VPN, a relay you
operate) are each a dependency or an ongoing cost.
**Falsifier:** the target user already runs Tailscale, in which case this is
re-solving a solved problem and the remaining value is only the OpenAI-compatible
routing layer.
**Confidence:** **low — the desk review (`docs/review/desk-review-2026-08-14.md`) found
the falsifier true as this premise is worded.** Single-user remote access to a home
GPU is a solved, SEO-saturated problem, and Tailscale is the free, "just works" answer
(Tailscale's own self-hosted-AI guidance; a dense field of 2026 "access Ollama with
Tailscale" guides). What the review did *not* falsify is a claim P2 does not actually
make — *multi-party* NAT traversal across many strangers' nodes, which Tailscale is
single-tenant-shaped and does not cleanly do. So any surviving differentiator is
**cross-party pooling, not NAT traversal**, which relocates the load-bearing claim onto
P1. That relocation is the finding, and it still needs the D7 review — a desk review by
the author is not it.

## P3 — The economics do not close for a marketplace

**Supports:** [D2](decisions/D2-economics.md), and through it the removal of all
payout machinery from v1.
**Evidence:** `scripts/economics.py`, tested by `tests/test_economics.py`. Hardware
amortisation alone exceeds commodity API pricing by ~12×, and the conclusion survives
doubling every power and throughput input and tripling utilisation.
**Falsifier:** commodity inference pricing rises by an order of magnitude, or the
target hardware stops being consumer GPUs, or hosts turn out to value something other
than money (which would not falsify the arithmetic but would change what it implies).
**Confidence:** high on the arithmetic, medium on the inputs. Nobody has metered a
real node in this fleet, **because there is no fleet**.

## P4 — Invite-only admission is adequate execution integrity for v1

**Supports:** [D1](decisions/D1-execution-integrity.md), [D4](decisions/D4-sybil-resistance.md).
**Evidence:** with no redemption (P3), the incentive to return garbage collapses to
"waste someone's time". Canary verification (implemented 2026-08-09,
`scheduler/core/canary.py`) catches a host not running a model at all -- a fixed
string, an echo, an empty completion -- and quarantines it from dispatch.
**Falsifier:** a trusted host degrades silently — a wrong model, a broken quantisation,
a stale weight file — and canaries at `temperature=0` do not catch it because the
canary is answerable by a smaller model too. **This is a known partial gap**, not a
solved problem: canaries prove *a* model ran, not *the* model.
**Confidence:** adequate for v1's scale, inadequate for anything open.

## P5 — A single coordinator is acceptable

**Supports:** [D5](decisions/D5-decentralisation-claim.md); the decision to leave Raft
in `experimental/`.
**Evidence:** under the self-hosted framing (D6) the coordinator is the operator's own
machine, so its availability is their problem and their choice.
**Falsifier:** the deployment shape turns out to be "one coordinator, many
organisations' nodes", where the coordinator's operator is a trusted third party
nobody agreed to trust.
**Confidence:** high, *conditional on D6 holding*. If a network is ever operated, this
premise fails immediately rather than gradually.

## P6 — Not persisting prompt text keeps data-protection exposure small

**Supports:** [D3](decisions/D3-terms-and-liability.md); the metering design.
**Evidence:** `tests/test_metering_privacy.py` fails if a field that could carry
prompt or completion text appears in a metering record.
**Falsifier:** prompts transit the coordinator regardless, so an operator who adds
request-body logging, or a memory dump, or a proxy in front, reintroduces the
exposure. The test constrains this codebase; it does not constrain a deployment.
**Confidence:** high for the code, **unknowable for a deployment**.

## P7 — Ollama is a sufficient inference backend

**Supports:** the entire working inference path; the decision to cut split inference.
**Evidence:** it works, it is what hosts already run, and `EchoBackend` is the only
other thing `runtime.py` has ever assigned.
**Falsifier:** the target user runs vLLM or llama.cpp directly and will not add
Ollama. The backend interface (`node/backends/base.py`) exists to make this
survivable, but no second backend has been written, so the abstraction is untested
against reality.
**Confidence:** medium. An abstraction with one implementation is a guess about the
shape of the second.

## P8 — The gate is the definition of "does this pass"

**Supports:** every completion claim in this repository.
**Evidence:** `scripts/verify.sh` is invoked by CI and nothing else;
`tests/test_source_parity.py` fails if CI grows its own check list.
**Falsifier:** **it has been falsified repeatedly, and each time by absence rather
than failure.** The gate did not lint `tests/`. It did not type-check `tests/`. It did
not touch the website. It ran an installer dry-run that returned early from every
step. Each gap was invisible precisely because the gate was trusted as total.

**2026-08-17 added a new shape of falsification, and it is worse than the others.**
The gate ran, CI ran, CI *failed* — and no one read it for eight days, across a
published `v1.0.0` release. Every prior instance was a check that did not exist. This
was a check that existed, executed, and reported red into a void, because
`scripts/generate_status.py` shells out to `gh` and reports `UNVERIFIABLE` where `gh`
is absent. "I could not look" is honest and scans as "nothing is wrong".

The current known gaps, enumerated so that an unlisted absence is not mistaken for an
all-clear (kept in sync with the README's "What we cannot see"):

- `install.ps1` has **never been executed by anything**; it is only ever read. Every
  Windows install defect so far was found by a person, not by the gate.
- The repository **cannot read its own CI** without `gh` on the PATH. Fix known
  (REST API fallback), not yet made.
- **Branches get no CI** — the workflow triggers on `push` to `main` and on PRs only.
- The local gate is **one OS and one interpreter**; platform-specific defects are
  structurally invisible to it. Three so far: cp1252 encoding, CRLF line endings,
  wall-clock resolution.
- **`docker-compose.test.yml` has never run.**

**Confidence:** high that it catches what it checks; **low that anyone knows what it
does not check**. The correct posture toward this file's own subject.

## P9 — Documentation that describes intentions as achievements is the failure mode

**Supports:** the existence of `VERIFY.md`, `STATUS.md` being generated, the
`docs/historical/` quarantine, and half the rules in `CLAUDE.md`.
**Evidence:** four separate instances found in one audit — `ARCHITECTURE_OVERVIEW.md`
claiming FP8 "integrated", `docs/ROADMAP.md` claiming "v0.1 (Realized)", the
orchestrator returning `verification_passed=True` for a stub, and a gateway returning
invented text as a successful completion.
**Falsifier:** none available. This is the one premise here that is a **belief** — an
interpretation of the project's own history rather than a claim about the world. It
is listed anyway because it drives more process than anything else on this page, and
process justified by an unfalsifiable belief is worth naming as such.

## P10 — Sending a prompt to a peer's machine is an acceptable trade for pooling

**Supports:** the whole multi-machine framing; whatever survives of P1's federation
half after the desk review.
**Evidence:** none gathered. This premise was surfaced by the 2026-08-14 desk review
as "the privacy paradox" and sat outside this register until 2026-08-17, which is
itself the finding — the register's own instruction is that an unregistered
assumption is one nobody can attack.

The tension is direct. The motivation for running models locally is usually *"nothing
leaves hardware I own."* Routing a request to somebody else's node breaks exactly that
property. P6 constrains what this **code persists**; it says nothing about where a
prompt **travels**, and the two are routinely conflated.

**Falsifier:** the users who want local inference want it for privacy, in which case
pooling across other people's machines is not a smaller version of the same product —
it is the opposite product, and the addressable set is only people who trust every
host in their pool. Note this does **not** fire for the self-hosted-fleet case
([D6](decisions/D6-is-there-a-network.md)), where every machine belongs to the same
person or organisation. It fires precisely for the cross-party pooling the desk review
identified as the one surviving differentiator.
**Confidence:** **low, and load-bearing.** If P10 fails, cross-party pooling fails
with it, and P2 has already been moved to low confidence — which would leave the
project's differentiator resting on two low-confidence premises at once.

---

## How to attack this list

- Pick either of the lowest-confidence premises (**P2**, **P10**) and ask whether the
  people they describe exist. They are now the same question from two sides: P2 asks
  whether anyone needs this to reach a machine, P10 asks whether anyone who does would
  accept where their prompt goes. A single answer can falsify both.
- Pick the one with the largest downstream commitment (**P3**), and check the inputs
  against a real electricity bill and a real card.
- Pick the one whose falsifier says "none available" (**P9**), and ask whether the
  process it justifies is proportionate.

Last reviewed: 2026-08-07. Reviewed by: the author. **That is the problem** — see
[D7](decisions/D7-second-pair-of-eyes.md).

Desk review 2026-08-14 (`docs/review/desk-review-2026-08-14.md`) attacked the market
premises against published external sources. It moved P2 to **low** confidence
(falsifier found true as worded), read P3 as weakly **supported** by competitor
behaviour, and split P1 into strong-local / unevidenced-federation. A second run
through a different model (Gemini Deep Research), on a different network and blind to
the first review's verdicts, converged on the same four verdicts and reached the
primary sources the first run's egress proxy blocked — the strongest single result of
the exercise. It also over-reached once, declaring the architecture physically
impossible by attacking WAN tensor-sharding, which v1 does not do (the working path
routes a whole request to one node); the codebase refutes that specific claim. See the
review's addendum. **Neither run closes D7** — two models gathered external evidence;
neither is an external human judge.

The candidate premise that review surfaced — **the privacy paradox** — was registered
as **P10** on 2026-08-17. It had sat outside this file for three days while the file's
own argument is that an unregistered assumption is one nobody can attack.

Last updated 2026-08-17: P8 gained the enumerated verification gaps, P10 was added.
**Still reviewed only by the author, and still the problem.**
