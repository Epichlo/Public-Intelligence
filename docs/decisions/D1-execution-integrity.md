# D1 — How does a requester know a node actually ran the model?

**Date:** 2026-08-07
**Status:** Decided
**Question owner:** the whole architecture — matchmaking, the ledger, and the pitch
all change with the answer.

## The question, restated

A host is paid — in credits — for serving inference. Nothing in the system checks
that the tokens it returned came from the model it claimed to run. A host that
returns cheap garbage earns exactly as much as a host that runs a 70B model, and
does so on a fraction of the electricity. That is not a hypothetical failure mode;
it is the *rational* one. The `token_556` bug (ROADMAP N1) was the accidental
version of it, and it reached HTTP 200 for weeks.

Petals survives without an answer here because its participants are semi-altruistic
researchers with nothing to gain from cheating. **Attaching payment removes that
protection.**

## Decision

**v1 is an invite-only trusted-host network, not an open marketplace.** Two
mechanisms, in this order:

1. **Admission control is the primary defence.** A node cannot register without an
   invite code issued by the operator (see [D4](D4-sybil-resistance.md)). Trust is
   established out-of-band, by a human, before any dispatch. This is the honest
   answer for v1: we do not detect cheating, we restrict who can attempt it.

2. **Canary verification makes the trust checkable rather than assumed.** The
   Scheduler periodically dispatches a *canary* — a prompt with a deterministic,
   low-entropy expected answer, sent at `temperature=0` and indistinguishable at
   the wire from a real request — and scores the reply. A node that fails canaries
   is quarantined from dispatch and the operator is told. This does not prove a
   given production response was genuine. It proves the host is *running a model at
   all*, which is precisely the gap the `token_556` class of failure lives in.

**Explicitly rejected for v1:** redundant execution on every request (doubles cost
for a network whose economics already do not close — see [D2](D2-economics.md)),
TEE attestation (excludes consumer hardware, which is the entire supply), and
stake-slashing (requires a token, which requires a legal apparatus this project does
not have).

## What this costs, stated plainly

- **It does not scale past people the operator can vouch for.** That is the trade.
  An open marketplace needs an answer this decision does not provide.
- **Canaries are detectable by a determined adversary.** A host that fingerprints
  canary prompts defeats them. Against a *trusted* host population the mechanism is
  a smoke detector, not a lock, and it is documented as one.
- **Sampling costs real tokens.** The canary rate is a setting, default low.

## What changes in the code

- `POST /nodes` requires an invite code — [D4](D4-sybil-resistance.md), implemented
  in `scheduler/core/invites.py`.
- Canary verification lives in `scheduler/core/canary.py`, with quarantine state on
  the node record and exclusion applied in the matchmaker.
- **Nothing may claim verified execution that has not been verified.** The ledger
  records which node served each request (ROADMAP 3.2) so that a later dispute has
  evidence; it does not assert the answer was correct.

## Consequence for the pitch

The word "marketplace" is not usable for v1. See [D8](D8-the-wedge.md), which
positions this as self-hosted infrastructure for hardware you already control —
a framing under which D1 is a much smaller problem, because the host and the
requester are frequently the same person.
