# D7 — A second pair of eyes

**Date:** 2026-08-07
**Status:** **Open. Not resolved, and not resolvable from inside this repository.**

## The question, restated

The process here is stronger than most production teams have: a single gate that CI
and local both invoke, red-green with observed failure, drift ratchets on duplicated
modules, a wire-contract test that feeds one service's real serialiser to the other's
real models, and a verification checklist that forbids self-certification in the same
pass as the code.

It caught none of the following: a dead DNS name shipped in every installer, a
reachable code path that returned invented text as a successful completion, a missing
licence, and a roadmap that described intentions as achievements.

The reason is structural. **Every one of those is a wrong premise, and the process
only tests conclusions.** A ratchet asks "did this get worse". A test asks "does it
still do what I said". Neither can ask "should it do this at all". Every judgement in
this repository to date has been made by one party.

## Why this record exists rather than a decision

The other seven Stage D questions can be answered by the person asking them. This one
cannot: an answer produced by the same party is the failure mode, not the fix. Marking
it "decided" would be the most on-the-nose possible instance of the problem it names.
**It stays open.**

## What was done instead, and what that is worth

Two substitutes, both weaker than the real thing, both better than nothing:

1. **A premise register** — `docs/PREMISES.md`. Every load-bearing assumption this
   project rests on, each one stated as a falsifiable claim with the evidence for it
   and what would disprove it. The value is not that it is checked; it is that a
   reviewer arriving cold can attack the list directly instead of reverse-engineering
   it from 14,000 lines of code. It converts "find the wrong assumption" from an
   archaeology problem into a review problem.

2. **An adversarial audit pass** — the audit that produced ROADMAP Stage C and the
   Stage D list, run against the premises rather than against the tests. It found the
   dead DNS, the fabricating endpoint and the missing licence, all of which the gate
   had been green over for weeks. That is evidence the technique works, and equally
   evidence that it works *only when someone runs it*, which nothing forces.

Neither substitute is a second party. A self-audit finds the errors you are capable
of recognising, and the interesting ones are definitionally the others.

## What closing this actually requires

One named person, not connected to the work, who has read `docs/PREMISES.md` and
[D1](D1-execution-integrity.md)–[D8](D8-the-wedge.md) and is willing to say "this
premise is wrong". Candidate forms, cheapest first:

- Post the premise register publicly and invite disagreement. Apache-2.0 and
  `CONTRIBUTING.md` (ROADMAP N3) exist partly to make this possible at all — until
  2026-08-07 nobody could legally fork this to critique it.
- One security review of the auth surface by someone who does that professionally.
  The known bypasses in `VERIFY.md` step 3 are a good first artefact to hand over.
- One conversation with somebody who has operated a compute marketplace, about
  [D2](D2-economics.md). That decision — that the economics do not close — is the
  most consequential and the least externally validated thing in this directory.

## Status of dependent work

D7 blocks nothing in the code, deliberately. Blocking the tree on a question that
requires another person would stop all work indefinitely. It blocks something else:
**operating this for anyone other than yourself**, which is also gated by
[D3](D3-terms-and-liability.md), for related reasons.
