---
description: Rules that structurally prevent an agent from verifying its own work
---

# Verification independence (highest-priority constraint)

- **The agent that WROTE code may not decide it is verified.** Not "should not" —
  `.claude/hooks/require-proof-stop.py` enforces it.
- Implementers write beliefs to `zones/claimed/`. Only `./scripts/verify.sh` writes
  `zones/verified/`, because writing it requires having run the checks.
- The `independent-verifier` subagent runs in its own worktree, is denied `Write` and
  `Edit`, and reads only: (a) the git diff, (b) the spec's acceptance criteria,
  (c) test output it generated itself.
- If a claim and the evidence disagree, **the evidence wins and the task is not done.**

## What counts as evidence

A `zones/verified/latest.verified.json` with `verdict: pass` whose `commit` and
`state_fingerprint` match the tree *right now*. Editing anything after the gate ran
invalidates it, and the Stop hook recomputes rather than trusting the file's word.

These do **not** count, and asserting them is a policy violation:

- "The tests should pass."
- "This is a trivial change, so the gate is unnecessary."
- Output from an earlier session. `CLAUDE.md`: prior results don't carry over.
- A summary of what a command *would* print.

## When the gate cannot run

Say so, name the check, and say why. `VERIFY.md`: "A check you could not run is
`UNVERIFIED`, never `PASS`." An honest gap is a finding. A gap reported as a pass is
the failure this whole layer exists to prevent — and it has happened here, which is
why `docs/historical/` exists.

## The decision ledger

Decisions live in `docs/decisions/` (D1–D8) and `ROADMAP.md` is the plan of record.
Do not start a second ledger elsewhere; two lists means two answers.
