# Historical documents — DO NOT READ THESE AS A DESCRIPTION OF THE SYSTEM

Everything in this directory describes what Public Intelligence was *intended* to
be. Much of it describes those intentions in the past tense, as things that were
built. **They were not.**

Moved here on 2026-08-07 (ROADMAP N2) rather than deleted, because the reasoning in
them is worth keeping and the git history should not pretend they never existed.

Specific claims in these files that are false as of the date above:

| File | Claim | Reality |
|---|---|---|
| `ARCHITECTURE_OVERVIEW.md:60` | FP8 (E4M3) quantization "integrated into `BackpressuredStreamRouter`" | Never implemented. The module exists and nothing on the request path calls it. |
| `ARCHITECTURE_OVERVIEW.md:94` | "realized through Phase 4.5" | Phases 4.6–4.9 were described as realized over code that does not do what the labels claim. |
| `ARCHITECTURE_OVERVIEW.md:41` | Nodes "participate in peer-to-peer layer sharding" | Sharding is cut from v1. No node has ever sharded anything. |
| `ROADMAP.md` | "v0.1 (Realized)", "v0.2 (Realized)" | Both list features that were not working when the label was applied. |
| `PROJECT_CONTEXT.md:97` | "pipeline model-layer sharding" | Cut from v1. |

The split-inference path these documents describe **did exist as a reachable API
route**, and returned invented text as a normal HTTP 200 — asking it "What is the
capital of France?" returned `token_556`. That was removed on 2026-08-07
(ROADMAP N1); the endpoint now answers 501 Not Implemented.

## Where to look instead

| For | Read |
|---|---|
| What is true right now, generated from real test runs | `../../STATUS.md` |
| What is planned, in dependency order, with honest status | `../../ROADMAP.md` |
| How to work in this repo | `../../CLAUDE.md` |
| What each change was supposed to do and why | `../../specs/` |
| Whether a change was actually verified | `../../VERIFY.md` |

**`ROADMAP.md` supersedes `ROADMAP.md` in this directory.** Where they disagree, the
one at the repository root is correct.
