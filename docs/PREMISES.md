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
**Confidence:** medium-low. **This is the premise most likely to be wrong**, and it is
also the one the pitch leans hardest on. It deserves the second opinion D7 asks for
before more is built on it.

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

---

## How to attack this list

- Pick the premise with the lowest stated confidence (**P2**), and ask whether the
  people it describes exist.
- Pick the one with the largest downstream commitment (**P3**), and check the inputs
  against a real electricity bill and a real card.
- Pick the one whose falsifier says "none available" (**P9**), and ask whether the
  process it justifies is proportionate.

Last reviewed: 2026-08-07. Reviewed by: the author. **That is the problem** — see
[D7](decisions/D7-second-pair-of-eyes.md).
