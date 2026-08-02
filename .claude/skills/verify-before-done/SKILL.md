---
name: verify-before-done
description: Run before saying a task is done, complete, working, fixed, or passing. Enforces that every completion claim is backed by a command actually run in this session, and routes through VERIFY.md. Triggers on - "is it done", "did that work", marking a task complete, writing a status or summary line, reporting test or CI results, or any phrasing like "should work", "now passes", "all green", "fully implemented".
---

# Verify before claiming done

A completion claim is a factual assertion. It needs evidence from **this session**,
not from a previous run, not from what the code looks like it should do.

## The rule

> Every claim of the form "X works / X passes / X is done" must be traceable to a
> command run in this session whose output you have seen.

If you have not run it, you do not know. Say you have not run it.

## Before writing any completion claim

Ask, in order:

1. **What command proves this?** If no command could prove it, the claim is an
   opinion — phrase it as one.
2. **Did I run that command in this session?** Not "is it likely to pass." Did it
   run, and did you read the output?
3. **Did I read the output, or the exit code alone?** A pytest run that collects
   zero tests exits 0. A build that skips a broken target exits 0. Read the summary
   line.
4. **Am I about to describe a subset as the whole?** "Tests pass" after running one
   of three suites is false. Name what ran.

## Then run VERIFY.md

For any code change, `VERIFY.md` at the repo root is the checklist. Work through it
as a **separate pass** from the one that wrote the code — not a re-read of your own
diff, an actual re-execution.

It ends in an explicit PASS / FAIL / UNVERIFIED per item. A PASS with any item
UNVERIFIED is not a PASS.

## Language that is not allowed without evidence

| Don't write | Unless you |
|---|---|
| "Tests pass" | ran the suites this session and can paste the counts |
| "This should work" | ran it — otherwise say "I have not run this" |
| "CI is green" | queried CI and saw the result |
| "Fixed" | reproduced the failure first, then saw it stop |
| "Fully implemented" | checked the spec's "Done looks like" list item by item |
| "No secrets" | ran the greps in VERIFY.md step 3 |

## What to say when you can't verify

Name the gap. This is a complete, acceptable answer:

> Node and Scheduler suites pass (157 and 137, run just now — output above). I could
> not verify CI: there is no git remote configured, so the workflow has never
> executed. Treating CI as UNVERIFIED, not as passing.

Compare with the failure mode this skill exists to prevent — a confident summary
that reads as verified and isn't:

> All tests pass, CI green, phase fully realized. ✅

That sentence is how this repo accumulated four phases of "100% realized" claims
over a codebase whose distributed inference path is an echo stub.

## Reporting honestly is not failure

A FAIL that is accurate is more useful than a PASS that is not. Nobody is helped by
a green summary that the next person has to re-derive from scratch — and once one
summary turns out to be wrong, every prior one has to be re-checked too.
