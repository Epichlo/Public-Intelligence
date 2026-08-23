# Independent model review — 2026-08-23

> **Provenance.** Run by Claude Sonnet (Anthropic), executed headless via the Claude
> Code CLI from inside this repository — so, unlike the 2026-08-14 Gemini run, it was
> NOT blind to earlier reviews' existence; it could read this repo, ROADMAP.md and
> PREMISES.md. It is a different model family from the one that wrote the code,
> which is the independence it has; it is not an external human judge and does not
> close D7. Prompt: attack the load-bearing premises against code, cite file:line.

## Verdict
HOLDS, with one live finding not in `docs/PREMISES.md`: independent code inspection confirms the two premises the project cites as cause of closure (P2 — NAT traversal unproven, P3 — economics don't close) are accurately self-reported, not overstated. But P8 ("the gate is the definition of done") is failing **right now, in this session** — the last verified bundle covers `d6b4564` and was generated dirty even then, while HEAD has since moved to `1780e4e`. Nothing on this branch currently has valid gate evidence, including the two most recent security commits.

## Findings

### P2: NAT traversal for GPU hosts is the differentiator (D8's whole bet)
- Verdict: CONFIRMED (as unproven — the docs accurately self-report failure)
- Evidence: `tests/test_mesh_inference_e2e.py:14,18` states in its own docstring: "This is still one process on loopback. Two machines behind two NATs is ROADMAP 1.5." `:39` binds `ENDPOINT = "tcp/127.0.0.1:7453"`. `docker-compose.test.yml` exists on disk but nothing shows it has ever run — `ROADMAP.md:60` and `VERIFY.md:301` both say so, and `tests/test_compose_env_matches_settings.py` found two defects in it *without* running it, corroborating that it's inert. No fix needed — this is an unearned claim correctly labeled unearned.

### P3: The economics do not close for a marketplace
- Verdict: CONFIRMED
- Evidence: reproduced `fully_loaded_cost()` (`scripts/economics.py:105-129`) by hand against the file's own defaults (`:40-63`): $600/yr amortisation + $100.52/yr idle + $81.91/yr load = $782.4/yr ÷ 346.9M tokens/yr = **$2.256/1M tokens** vs. $0.15/1M commodity — a ~15x loss, matching `ROADMAP.md`'s closure claim exactly. Found one doc drift: `docs/PREMISES.md:58` still says "~12×" — stale relative to the ~15x figure the roadmap actually uses. Doesn't change the verdict (the conclusion is insensitive to 2x input error per the file's own footer), but it's a one-line fix worth making.

### P8: The gate is the definition of "does this pass" (verification integrity)
- Verdict: REFUTED — actively, in this session, not just historically
- Evidence: `zones/verified/latest.verified.json` has `"commit": "d6b4564..."` and `"working_tree_dirty": true`. Current `HEAD` is `1780e4e...` — one commit past what the bundle covers, and the bundle admits it ran dirty even at its own commit. Per `CLAUDE.md`'s own rule, that makes it evidence "about code that no longer exists." Concretely: the two security commits spot-checked below have no matching passing bundle — I confirmed them by reading code, not by gate output.
- Minimal fix: re-run `./scripts/verify.sh` against a clean `1780e4e` tree before any completion claim on this branch; treat everything since `d6b4564` as `UNVERIFIED` until then, per `.claude/rules/verification.md`.

## Security commit spot-check
- `6698f36` ("the scheduler control plane failed open in six reviewed places"): **confirmed in current code**, not just the commit message. `packages/scheduler/src/scheduler/api/auth.py:50-59` — `verify_auth_token` fails closed (401) when `network_auth_token is None`. `packages/scheduler/src/scheduler/api/nodes.py:79-136` — credential is written only after admission, and re-registration requires `hmac.compare_digest` proof of the stored credential before refresh. Both match the commit's claims.
- `5f817e2` (perf_counter merge resolution) and `41a3fb5` (website loopback middleware): checked at `git show --stat` + commit-message depth only, not full diff. Consistent with `ROADMAP.md`'s independently-documented V2 entry for the clock fix, but this is a shallower check than `6698f36` got.

## Blind spots
`docs/PREMISES.md` registers host-side motivation (P1) but never a **requester-side** demand premise — nothing asks whether anyone actually wants inference from a 7B–70B open model on a stranger's residential connection over frontier-hosted APIs at comparable latency. A two-sided exchange with only one side's motivation examined is a real gap.

Second: D3 (terms/liability) is explicitly "NOT reviewed by counsel" (`ROADMAP.md:285`), and hosts run strangers' arbitrary prompts egressing from a residential IP — but this has no P-number, no falsifier, no confidence rating. P6 covers only what the code *persists*, not what a host is exposed to by carrying the traffic at all. An unregistered, unrated legal-exposure premise sitting next to nine carefully falsified ones is inconsistent with the register's own stated purpose.
