# Spec: The gate sees the website, the tests' types, and its own scripts (ROADMAP C6 + C7, part of C8)

## What this does

`scripts/verify.sh` is "the only definition of does this pass". Three directories
sat outside it while appearing to be inside: the website was checked by nothing,
`tests/` was linted but never type-checked, and **`scripts/` — which contains the
gate itself — was outside all of it.** This puts all three inside, and adds a ratchet
so the fourth one fails loudly when it appears.

C6 and C7 are done together because they need the same thing — Node dependencies
installed — and doing them separately would pay that cost twice.

## What actually breaks today

**The website is 4,270 lines checked by nothing.** `package.json` has a `lint`
script the gate never invokes and no `test` script at all. Zero test files. Every
proxy route — including the credential forwarding added in ROADMAP 2.6 — is verified
only by reading it. Its own eslint finds **3 errors and 2 warnings** that have never
failed a build.

**`tests/` is not type-checked**, and pointing mypy at it reveals a second, larger
problem: **26 of the 27 errors are `module is installed, but missing library stubs or
py.typed marker`.** Neither package ships a PEP 561 marker, so their `strict = true`
type information is invisible to every consumer. Adding a `mypy tests` step without
fixing that would have produced *a check that reports success for doing nothing* —
verifying the test files' own local variables and nothing about the contract they
assert. The 27th is a real error in a file added last session:
`test_declared_dependencies.py:76`, `"AST" has no attribute "lineno"`.

**`scripts/` is linted by nothing**, and running ruff over it finds 3 errors and 4
unformatted files. One of the errors is `Path.read_text()` with no encoding **in
`generate_status.py`** — the exact platform-default bug ROADMAP 2.9 enabled
`PLW1514` to catch, surviving in the script that generates `STATUS.md`, because the
rule was only ever aimed at `packages/` and `tests/`.

## The pattern this is the fourth instance of

Every time a directory has been added to this gate, **the defect found was the
check's absence, not a check's failure**: `tests/` unlinted (2.9), `tests/` untyped
(C7), the website unchecked (C6), `scripts/` outside everything (found here). A gate
trusted as total and silently partial is more dangerous than no gate, because a green
run is read as coverage.

So the durable half of this change is not the four new steps. It is
`test_every_python_directory_is_linted_by_the_gate`, which fails when a top-level
directory containing Python is not passed to ruff by `verify.sh`. **It found a fifth
instance on its first run**: a top-level `src/` at the repo root.

## What `src/` turned out to be, and why ROADMAP C8 was wrong about it

C8 says "`src/shared/` is an orphan third copy of the artifact store, imported by
nothing". Both halves needed correcting:

- **`packages/node/src/shared/` is not orphaned.** `node/runtime.py:80` imports it
  and writes **every generated completion to disk** on the task-queue path. It is
  live code. It was also installed into site-packages as a top-level package named
  `shared`, so any other distribution shipping that name collided with it, and it was
  reached through a `try/except ModuleNotFoundError` ladder falling back to
  `src.shared...` — which only ever resolved when pytest ran from the package
  directory. Moved to `node/storage/`, one import path that always works.
- **The genuine orphan is `src/` at the repo root**, a fourth copy, differing from the
  others only in comment wording and formatting, reachable solely through that
  fallback. Deleted.

## Design decisions, and why

**Website checks skip, loudly, when `node_modules` is absent.** Same pattern as the
shellcheck step. A Python contributor should not need a Node toolchain to run the
gate; CI installs it and therefore always runs them. The cost is stated rather than
hidden: skipped steps are now tracked in a `SKIPPED` array, printed in the summary as
`N check(s) DID NOT RUN`, recorded in the receipt, and followed by the
sentence *"this PASS is weaker than a CI PASS"*. Previously shellcheck's skip was
printed once and then invisible in the verdict.

> **Corrected 2026-08-10.** This paragraph named `.verify-receipt.json`, which no
> longer exists: `specs/the-agent-cannot-certify-itself.md` replaced it with
> `zones/verified/latest.verified.json`, one artifact rather than two. The `skipped`
> list still travels with the verdict, which is the part this decision was about.

**CI installs Node dependencies in its existing install step, not as a check.**
`tests/test_source_parity.py` forbids `ruff|mypy|bandit|pytest` in `ci.yml` — CI must
not grow a second list of checks. `npm ci` is installation, in the same step that
already runs `pip install`, so the rule is respected in substance and not just letter.
A separate test asserts `npm ci` is present, because without it CI would skip the
website steps and still print PASS.

**`passWithNoTests: false`.** A suite that silently matches zero files is this whole
change's failure mode in a new costume.

**Vitest, not Jest.** Next 16 with React 19; vitest needs no Babel configuration and
runs TypeScript directly. Config is `.mts` so Vite's native loader does not warn.

**`--max-warnings=0` for eslint.** Warnings that never fail anything accumulate
invisibly — the same silent-partial shape. The two existing warnings were a duplicated
layout constant (`nodeHeight`, redeclared from `diagramTokens.node` and never read);
fixed by sourcing from the token, not by deleting the line.

**The 3 eslint errors are fixed, not silenced.** All were `no-explicit-any` on error
handling that reads FastAPI's three different error-body shapes. Replaced with
narrowing helpers, so a shape change surfaces as a type error instead of
`[object Object]` in the UI.

**The first website test covers a proxy route's credential handling**, not a component
snapshot. `api/telemetry/all` must send `X-Network-Auth-Token` upstream, must not send
it to the browser, must not send an empty one when unconfigured, and must not mask an
upstream 401 as success.

## Done looks like

- [x] `./scripts/verify.sh` type-checks `tests/` and fails on a type error there.
      **Observed** — introduced one, `mypy (tests)` failed.
- [x] Both packages ship `py.typed`, taking `mypy tests` from 27 errors to 1.
- [x] The `test_declared_dependencies.py:76` error is fixed by narrowing, not `# type: ignore`.
- [x] `./scripts/verify.sh` lints `scripts/`. **Observed failing** with an introduced error.
- [x] `./scripts/verify.sh` runs the website's eslint and its tests, and fails on each.
      **Observed** — separate sabotages, separate single-step failures.
- [x] Website steps **skip with a visible message** when `node_modules` is absent, the
      gate still passes, and the summary + receipt both name the skip. **Observed.**
- [x] `packages/website` has a `test` script and 4 tests asserting real behaviour.
      **Observed failing** under three separate mutations of the route.
- [x] The 3 eslint errors and 2 warnings are fixed; `--max-warnings=0`.
- [x] CI installs Node dependencies, and `tests/test_source_parity.py` still passes.
- [x] A ratchet fails when a Python directory sits outside the gate.
- [x] The root `src/` orphan is deleted and `shared/` is folded into `node.storage`.
- [x] `./scripts/verify.sh` passes — **17 checks**, up from 15.

## Out of scope

- **Broad website test coverage.** This establishes a harness and covers one route.
  The playground, SSE parsing and the components are ROADMAP 4.1.
- ~~**Type-checking the website.**~~ **This exclusion was WRONG and was reversed on
  2026-08-09.** The argument was that "eslint with the TypeScript plugin catches the
  errors that were actually present" — true of the errors present *that day*, and not
  a property of the tools. The first `tsc` run over this tree found **4 errors eslint
  passed clean**, in a test file the gate was already running. eslint checks lint
  rules; it does not type-check. `npm run typecheck` is now a gate step.
- **mypy on `packages/*/tests`.** Only the root `tests/` is added; the package suites
  are a larger error budget and a separate decision.
- **The rest of C8.** The six duplicated module pairs and the missing
  `packages/shared/` are untouched here. Only the artifact-store copies are resolved,
  because they were blocking `mypy tests`.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m mypy tests
npm --prefix packages/website run lint && npm --prefix packages/website test
```

## Notes / open questions

- **The skip-if-absent design means a local PASS is weaker than a CI PASS.** That
  asymmetry is real. The alternative — requiring Node for every gate run — trades it
  for a worse one, where contributors skip the gate entirely. The summary line naming
  the skip is what keeps it honest.
- The artifact store writes **generated completion text to disk on the node**, with no
  retention policy and no configuration. That is not a bug in this change, but it is
  directly relevant to D3's data-protection position and is not currently mentioned
  anywhere a host would see it.
