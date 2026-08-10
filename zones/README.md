# zones/ — what was claimed, and what was actually checked

Two directories, split by **provenance**. This is the on-disk expression of the
threat model in `docs/CLAUDE_CODE_ARCHITECTURE.md`.

| Directory | Written by | Trust |
|---|---|---|
| `claimed/` | agents, and the SessionStart hook | untrusted — a belief |
| `verified/` | `./scripts/verify.sh` and nothing else | trusted — a measurement |

The distinction is not who is more honest. It is that **writing `verified/` requires
having run the checks**: the bundle is a by-product of the gate executing, not a
statement anyone can compose. A model can write "the tests pass" into `claimed/` and
nothing about the world changes. It cannot write that into `verified/` —
`.claude/hooks/block-protected-paths.py` denies the write, including via shell
redirection, and `.claude/settings.json` carries a `deny` rule that no later scope or
permission mode can override.

## The bundle

`verified/latest.verified.json` records `verdict`, `commit`, `state_fingerprint`, the
per-step results, and which checks were **skipped** — a PASS that quietly omitted
half the gate is the failure this repo has hit three times, so the skip list travels
with the verdict.

`state_fingerprint` is what makes the evidence expire. It hashes `git diff HEAD` plus
every untracked, non-ignored file (`scripts/state_fingerprint.py`). The Stop hook
recomputes it instead of trusting the file: run the gate, edit one line, and the
bundle no longer describes the tree it claims to.

## Not tracked in git

Both directories are gitignored, exactly as `.verify-receipt.json` was before them —
these are per-commit machine output, and committing them would churn every branch.

CI remains the third tier and is unaffected: it runs the same script on a clean
checkout, uploads the bundle as a workflow artifact, and `STATUS.md` reports its
verdict against `HEAD`.

Tracking `claimed/` so a reviewer could diff *claimed against verified* on a pull
request is the natural next step, and is deliberately not done yet — see
`specs/the-agent-cannot-certify-itself.md`.
