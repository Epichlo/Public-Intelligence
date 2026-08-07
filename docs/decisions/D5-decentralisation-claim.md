# D5 — "Decentralised" versus one instance

**Date:** 2026-08-07
**Status:** Decided

## The question, restated

The pitch says community-owned decentralised infrastructure. The architecture is a
single FastAPI process holding the registry, the ledger and all matchmaking state,
originally in memory, on a free tier. Raft consensus code exists in the tree and is
explicitly out of v1. Either the claim narrows or the architecture changes.

This is the same failure mode as the documentation problem in ROADMAP N2: a story
the system does not implement. It is worse here, because the docs were fixable in an
afternoon and a positioning claim shapes what gets built for months.

## Decision

**Narrow the claim.** The accurate description of what this is:

> **Community-hosted compute, coordinated by one control plane you run yourself.**
> The hardware is distributed and belongs to the people who own it. The coordinator
> is a single instance, and whoever runs it is a trusted party.

"Decentralised" is not used, because the coordinator is a single point of trust and
a single point of failure, and using the word would be a claim about trust rather
than about topology.

**Raft stays in the tree, unexercised, quarantined.** Deleting 530 lines that work
and are tested, on the chance the answer changes, is not obviously right. Leaving
them where they look like part of the shipped system is what caused the problem.
They move to `experimental/` under ROADMAP C2, excluded from the shipped-code count,
so the number that gets reported means something.

## What this costs, stated plainly

- **The pitch loses its most fashionable word.** That word was doing marketing work
  the system could not support.
- **The single coordinator is a real limitation, now stated instead of implied.** If
  it is down, nothing dispatches. Under [D6](D6-is-there-a-network.md)'s
  self-hosted framing that is the operator's own machine and their own problem,
  which is a much more defensible place for it to be.
- Anyone who wants genuine multi-coordinator operation is not served by v1, and the
  docs now say so rather than letting them find out.

## What changes in the code

- README, `packages/website` copy, and `PROJECT.md` state the narrowed claim.
- `consensus.py` moves to `experimental/` (C2) with a header saying it is not part
  of the shipped system.
- Any surface that reports a count of "shipping" code excludes `experimental/`.
