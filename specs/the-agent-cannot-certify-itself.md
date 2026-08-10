# Spec: The agent cannot certify itself

Implements Pillars 1–3 of [`docs/CLAUDE_CODE_ARCHITECTURE.md`](../docs/CLAUDE_CODE_ARCHITECTURE.md),
translated to this repository. Pillar 4 and the worktree scripts are deliberately
out of scope; see below.

## What this does

Today the rule "do not certify your own work" lives in `CLAUDE.md`, `VERIFY.md` and
two skills. All four are **instructions to a probabilistic model**. They are followed
most of the time, which is a different property from being enforced.

This change makes the rule an OS-level fact. A session that modified code cannot end
while claiming success unless `scripts/verify.sh` actually ran against **that exact
code state** and passed. The Stop hook recomputes the fingerprint of the working tree
and compares; it does not read the model's account of what it ran.

It also gives the repo the structural separation the architecture doc is built
around: an `implementer` subagent that may write code but may not declare it
verified, and an `independent-verifier` subagent that runs in its own worktree, is
denied `Write`/`Edit`, and sees only the diff, the spec, and test output it generates
itself.

## Why the layer that exists is not enough

- **The pre-push hook fires too late.** `scripts/install-hooks.sh` is deterministic
  and real, but it runs at `git push` — *after* the session has already said "done".
  The claim reaches the user before the gate reaches the code.
- **Sessions that never push bypass it entirely.** Answering a question, writing a
  doc, editing a spec, reporting status — none of those touch the pre-push path, and
  those are exactly the sessions that produce prose claims about test state.
- **The repo has the receipts.** `VERIFY.md`'s verdict block records a session that
  found "four security holes and two false statements *in my own work from earlier in
  the same session*". `CLAUDE.md` records a session that reported "CI unverifiable"
  for a change whose CI run had already failed. Both are self-certification, and both
  happened under the current instructions.

## Design decisions, and why

Every one of these is a **deviation from the blueprint**, made because the blueprint
targets a repo that does not exist. Recorded here so the deviation is arguable rather
than accidental.

**1. `scripts/verify.sh`, never `make verify`.** The blueprint says `make verify`
throughout. `CLAUDE.md` is explicit that CI invokes `scripts/verify.sh` "and nothing
else… Adding a check means editing `scripts/verify.sh`". Introducing a Makefile would
create the second definition of "does this pass" that `tests/test_source_parity.py`
exists to prevent. No Makefile is added.

**2. Service names are translated.** `services/control-api` → `packages/scheduler`,
`services/inference` → `packages/node`, plus `packages/website`, which the blueprint
has no slot for. The blueprint's `npm ci`/`uv sync` commands are replaced by the one
venv this repo actually uses.

**3. No root `DECISIONS.md`.** The blueprint asks for an append-only ledger at the
root. This repo already has one: `docs/decisions/` (D1–D8, each with a decision, its
cost, and what changes in the code), plus `ROADMAP.md` as the plan of record. Adding
a root ledger would split decisions across two locations — the same "two lists, two
answers" failure the CI consolidation fixed. The rules file points at
`docs/decisions/` instead.

**4. `CLAUDE.md` is not replaced by the blueprint's template.** The template describes
`services/control-api (Node.js)`, RS256-only auth, and `make verify` — three claims
that would be false in this tree the moment they landed. Writing false architecture
into the file every session loads is the precise failure `docs/historical/` exists to
memorialise. The existing `CLAUDE.md` (112 lines, under the ~150 ceiling the blueprint
argues for) keeps its content and gains a pointer to `.claude/rules/`.

**5. Evidence is keyed to a state fingerprint, not to mtime.** The blueprint's Stop
hook does `sorted(glob("zones/verified/*.verified.json"), key=os.path.getmtime)[-1]`
and trusts the newest file. That passes on a **stale** artifact: run the gate, then
edit code, then stop — the newest bundle still says PASS about code that no longer
exists. This repo already understood the problem (`CLAUDE.md`: "if that file's commit
is not `HEAD`, whatever it says is about code that no longer exists") and only solved
half of it, since the receipt records `working_tree_dirty` as a boolean and a dirty
tree can change freely afterwards. The bundle here records `commit` **and** a
`state_fingerprint` — a SHA-256 over `git diff HEAD` plus the sorted hashes of
untracked non-ignored files. The hook recomputes it. Editing anything after the gate
runs invalidates the evidence.

**6. `verified/` means machine-generated, `claimed/` means model-asserted.** The
blueprint splits the zones by *who* wrote them (CI vs agent). Locally there is no CI,
so that split would be decorative in the only place the Stop hook can read. The split
that is enforceable here is by **provenance**: `zones/verified/` is written by
`scripts/verify.sh` and by nothing else, because writing it requires having run the
checks; `zones/claimed/` is where a model records what it believes. CI remains the
third tier and is unchanged — it runs the same script on a clean checkout, and
`STATUS.md` continues to report its verdict against `HEAD`.

**7. Hooks fail open on internal error, and closed only on a real verdict.** The
blueprint does not say what happens when a hook throws. A Stop hook that raises on
malformed JSON would wedge every session in the repo with no obvious cause. Every
hook here wraps its logic and exits 0 on any unexpected exception — a broken enforcer
must degrade to the status quo, not to a brick. The block cap and `stop_hook_active`
guard are both honoured.

**8. `.claude/` enters the gate, and the lint ratchet is widened to reach it.**
`tests/test_source_parity.py::test_every_python_directory_is_linted_by_the_gate`
skips any directory whose name starts with `.`, so `.claude/hooks/*.py` would have
been unlinted and unnoticed — a directory sitting outside "the only definition of does
this pass" while appearing to be inside it, which is the exact pattern that test
exists to catch, and which has now bitten this repo three times. Enforcement code is
the last thing that should be exempt. `verify.sh` lints `.claude`, and the ratchet now
walks dotted directories with `.agents` exempted in writing.

**9. Pillar 4 is deferred, not forgotten.** The four CI workflows need an
`ANTHROPIC_API_KEY` secret, a GitHub App install, and branch protection — none of
which I can create or verify from here, and `autofix.yml` grants an agent
`contents: write` on the strength of a label. The architecture doc's own caveat says
this is premature for a solo project with no inbound issue volume, and its
Recommendation 1 says to ship the trust anchor first. Deferring is following the
spec, not trimming it.

**10. The worktree scripts are deferred.** `wt-new.sh`/`wt-clean.sh` serve *parallel
human streams*. The trust anchor needs worktrees only for the verifier, which Claude
Code's native `isolation: worktree` provides. The blueprint's versions also assume
`npm ci` + `uv sync` per worktree, which is not this repo's setup.

## Done looks like

- [ ] `.claude/settings.json` exists, is valid JSON, sets `defaultMode: "plan"`, and
      its `deny` array covers `zones/verified/**`, `.env*`, `secrets/**`, `*.pem`.
- [ ] `.claude/rules/verification.md`, `security.md`, `scheduler.md`, `node.md`,
      `website.md` exist; the three package rules carry a `paths:` frontmatter glob
      matching the package they govern.
- [ ] `.claude/agents/{explorer,planner,implementer,independent-verifier}.md` exist.
      `independent-verifier` declares `isolation: worktree` and denies `Write`/`Edit`;
      `implementer` does not.
- [ ] `.claude/hooks/block-protected-paths.sh` exits 2 for a write to
      `zones/verified/x.json`, `.env`, `secrets/k`, `a.pem`, and exits 0 for
      `packages/node/src/node/runtime.py`.
- [ ] The same hook exits 2 for a **Bash** command that redirects into
      `zones/verified/` — a path guard bypassed by `echo >` is theatre.
- [ ] `.claude/hooks/require-proof-stop.py` blocks when no bundle exists, blocks on a
      `FAIL` bundle, blocks on a bundle whose `state_fingerprint` no longer matches
      the tree, and allows on a matching `pass` bundle.
- [ ] The same hook allows immediately when the session changed no code, so a
      question-answering session is not wedged.
- [ ] The same hook blocks when the tree is clean but `HEAD` moved past the
      SessionStart baseline — committing the work does not launder it.
- [ ] `.claude/hooks/sessionstart-context.sh` records the session's baseline `HEAD`
      and prints repo state to stdout for injection.
- [ ] The same hook exits 0 on malformed stdin, on missing git, and when
      `stop_hook_active` is set.
- [ ] `scripts/verify.sh` writes `zones/verified/latest.verified.json` carrying
      `verdict`, `commit`, `state_fingerprint`, `skipped`, and per-step results.
- [ ] `.verify-receipt.json` is **gone**, with its references in `CLAUDE.md` and
      `.github/workflows/ci.yml` updated — one artifact, not two.
- [ ] `verify.sh` lints `.claude`, and
      `test_every_python_directory_is_linted_by_the_gate` covers dotted directories.
- [ ] `tests/test_agent_governance.py` covers all of the above, and **every assertion
      was observed failing before the implementation and passing after**.
- [ ] `./scripts/verify.sh` passes.

## Out of scope

- **The Pillar 4 workflows** (`triage.yml`, `autofix.yml`, `dep-sweep.yml`,
  `doc-drift.yml`). Deferred per decision 9 — a known gap, not a rejection.
- **`wt-new.sh` / `wt-clean.sh`.** Deferred per decision 10.
- **CI writing `zones/verified/` back into the repository.** CI already uploads the
  bundle as a workflow artifact and `generate_status.py` already reports CI's verdict
  against `HEAD`. Committing from CI needs `contents: write` and can loop.
- **Tracking `zones/` contents in git.** The bundles are per-commit machine output and
  are gitignored, exactly as `.verify-receipt.json` was. Tracking claims so a reviewer
  can diff claimed against verified on a PR is the natural next step and is *not* done
  here.
- **Fixing the two stale statements in `CLAUDE.md`** (it says there are auth bypasses
  "listed with file:line in `VERIFY.md` step 3" — that table is now empty; and "No
  persistence anywhere", which ROADMAP 2.1/C3 contradict). Both are real and are
  reported rather than fixed, because fixing them means re-verifying the current truth
  and that is its own change.
- **Proving `.claude/rules/` is loaded by the installed Claude Code build.** The
  architecture doc's own caveat says these names shift within 2.1.x. See notes.

## Verification

```
.venv/bin/python -m pytest tests/test_agent_governance.py -q
.venv/bin/python -m pytest tests/test_source_parity.py -q
./scripts/verify.sh
```

Hook behaviour is checked by feeding real JSON on stdin, the way the runtime does:

```
echo '{"tool_input":{"file_path":"zones/verified/x.json"}}' | .claude/hooks/block-protected-paths.sh; echo "exit=$?"
echo '{"stop_hook_active":false}' | .venv/bin/python .claude/hooks/require-proof-stop.py
```

## Notes / open questions

- **`.claude/rules/` support is asserted by the architecture doc and unverified here.**
  If the installed build does not auto-load `rules/*.md`, those five files are inert
  markdown. The load-bearing one (verification independence) is therefore *also*
  pointed at from `CLAUDE.md`, which certainly loads. Confirm with `/context` or
  `/memory` in a real session — I cannot from this container.
- **`defaultMode: "plan"` changes every future interactive session in this repo** to
  start read-only. That is the blueprint's intent and it is one line to revert.
- **"Did this session change code" is answered by a SessionStart baseline, with a
  fallback.** A pure dirty-tree proxy has a hole: an agent that commits its work and
  stops leaves a clean tree and would be waved through. So the SessionStart hook
  records `HEAD` for the session id, and Stop treats the session as having changed
  code if the tree is dirty **or** `HEAD` moved since that baseline. When no baseline
  exists — the hook was added mid-session, as it is right now — it falls back to the
  dirty-tree proxy rather than blocking, because a missing baseline is an enforcement
  gap, not evidence of wrongdoing.
- **This spec cannot close D7.** Everything here is still one party building the
  machine that checks that party's work. It raises the cost of a false claim; it does
  not supply the second pair of eyes `docs/decisions/D7-second-pair-of-eyes.md` asks
  for.
