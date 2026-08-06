# Spec: Lint the cross-package tests, and catch implicit encodings (ROADMAP 2.9)

## What this does

Closes the two gate holes that let a Windows-only bug reach `main` with a green
local run: the root `tests/` directory is never linted, and nothing flags a file
read with no explicit encoding.

## What actually breaks today

**This is not hypothetical — it already happened, in this session.** ROADMAP 2.7
passed `./scripts/verify.sh` locally (`PASS 13 checks`) and passed the pre-push
hook, then failed CI on all three Windows legs:

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 2848
FAILED packages/scheduler/tests/test_mesh_ingress_auth.py::test_the_fleet_wide_secret_is_no_longer_used_anywhere
```

`Path.read_text()` with no encoding resolves to the *platform default* — UTF-8 on
macOS and Linux, cp1252 on Windows. One non-ASCII byte in any scanned file
(`packages/node/examples/demo.py`) made it fail on Windows and nowhere else.

Two gate holes let it through:

1. **`verify.sh` never lints `tests/`.** It runs `ruff check ./packages` and
   `ruff format --check ./packages`. The root `tests/` directory — the wire
   contract, the parity ratchets, the installer checks, every cross-package test —
   is not linted at all. There is also no ruff config at the repo root, which is
   why a stray `ruff format ./tests` reformats at ruff's default 88 columns instead
   of this repo's 100.
2. **Nothing flags an implicit encoding.** Ruff has a rule for exactly this,
   `PLW1514` (unspecified-encoding), and it was not enabled.

Measured, not estimated: with the repo's real config, `tests/` has **7** lint
errors (4 unsorted-imports, 2 deprecated-import, 1 suppressible-exception), and
`PLW1514` finds **2** violations across `packages/` — both `open()` calls in tests.
An earlier note of mine said 22 errors in `tests/`; that count came from running
ruff with its *default* line length rather than this repo's, so most of it was
spurious `E501`. Corrected here.

## Design decisions, and why

**`tests/` is linted with the scheduler package's config, not a new one.**
`ruff check ./tests --config packages/scheduler/pyproject.toml`. A third copy of
the `[tool.ruff]` block at the repo root would be one more thing to keep in sync,
and `tests/test_source_parity.py` already exists to stop exactly that kind of
duplication drifting. Pointing at an existing config costs one flag.

**`PLW1514` is enabled with `explicit-preview-rules`, not by turning preview on
wholesale.** The rule is preview-gated. `preview = true` alone would activate every
other preview rule in the selected categories — an unknown amount of churn, and
rules that can change between ruff releases. `explicit-preview-rules = true` opts in
to *only* the preview rules named in `select`, so the blast radius is one rule.

**Both packages get the identical config block.** `tests/test_source_parity.py`
asserts the two `[tool.ruff]` blocks are byte-identical, and that assertion is worth
more than the convenience of changing one. Both are edited the same way.

**The two `open()` violations are fixed, not suppressed.** They read a file written
by the same test, so the encoding is genuinely ours to state.

## Done looks like

- [x] `./scripts/verify.sh` lints `./tests` and fails if it has a lint error.
      Verified by introducing one and watching the gate fail.
- [x] `./scripts/verify.sh` format-checks `./tests` at this repo's line length.
- [x] `PLW1514` is enabled in both packages, and only that preview rule is.
- [x] A `read_text()` or `open()` with no encoding anywhere in `packages/` fails
      the gate. Verified by introducing one.
- [x] The 7 existing `tests/` lint errors and 2 encoding violations are fixed.
- [x] Both packages' `[tool.ruff]` blocks remain byte-identical
      (`tests/test_source_parity.py` still passes).
- [x] `./scripts/verify.sh` passes.

## Out of scope

- **Linting `packages/website`.** TypeScript, different toolchain, no harness
  (ROADMAP 4.1).
- **Type-checking `tests/`.** mypy runs on `packages/*/src` only. Extending it is a
  larger job with its own error budget.
- **The non-ASCII byte in `packages/node/examples/demo.py`.** It is valid UTF-8 and
  there is nothing wrong with it. The bug was reading it without saying so.
- **Other preview rules.** Deliberately excluded by `explicit-preview-rules`.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m ruff check ./tests --config packages/scheduler/pyproject.toml
.venv/bin/python -m ruff check ./packages --select PLW1514
```

## Notes / open questions

- The deeper lesson is not the rule. It is that `verify.sh` is "the only definition
  of does this pass", and a directory it never looked at was outside that
  definition while appearing to be inside it. Worth asking, next time a check is
  added, what it does *not* cover.
- Open: mypy still does not see `tests/`, so the same class of gap exists for types.
  Not fixed here, and named so it is a known gap rather than an assumed cover.
