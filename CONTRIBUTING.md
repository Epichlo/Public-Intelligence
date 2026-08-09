# Contributing

Contributions are welcome. This project has unusual process rules and they are not
decoration — they exist because each one was added after something specific went
wrong. Read this before opening a pull request; it is short, and it will save you a
review cycle.

By contributing you agree your contribution is licensed under
[Apache-2.0](LICENSE), the licence this project ships under.

## Setup

One venv, one interpreter, everything:

```bash
git clone https://github.com/Epichlo/Public-Intelligence.git
cd Public-Intelligence
python3 -m venv .venv
.venv/bin/python -m pip install -e packages/shared \
  -e "packages/node[dev]" -e "packages/scheduler[dev]"
./scripts/install-hooks.sh          # pre-push hook that runs the gate
cd packages/website && npm ci       # only if you are touching the website
```

Python 3.11 is the floor. CI runs 3.11, 3.12 and 3.14 on Linux, macOS and Windows.

## The gate

```bash
./scripts/verify.sh            # everything CI runs, in one command
./scripts/verify.sh --quick    # skips cross-package tests and the installer
```

**Do not run ruff, mypy, bandit or pytest individually and conclude anything from
it.** `.github/workflows/ci.yml` invokes `scripts/verify.sh` and nothing else, so
there is exactly one definition of "does this pass". This is enforced:
`tests/test_source_parity.py` fails if CI grows its own list of checks.

Adding a check means editing `scripts/verify.sh`. Never add a step to the workflow.

## The three rules that get PRs sent back

### 1. Spec first

Anything bigger than a typo gets a spec. Copy `specs/TEMPLATE.md` to
`specs/<feature>.md` and fill it in **before** writing code. The section that matters
most is **Out of scope** — it is what stops a later reader assuming more was built
than was.

### 2. Write the test with the code, and watch it fail

A test that has never failed proves nothing. Write it, run it, **see it red**, then
write the implementation and see it green. If you cannot make it fail, you have not
found the behaviour you meant to pin.

### 3. Verify as a separate pass

Work through [`VERIFY.md`](VERIFY.md) top to bottom, after the code is written, as
its own step. Paste real output. End with an explicit PASS or FAIL.

**A check you could not run is `UNVERIFIED`, never `PASS`.** "I couldn't check X" is
a perfectly good thing to write in a PR. "X passes" without having run X is not, and
is the single fastest way to get a change rejected here.

## Claims and language

This project has a specific history with documentation that described intentions as
achievements — see `docs/historical/`, which is kept precisely so that history is
visible. So:

- **Claims about tests, CI or behaviour need output from the run you are describing.**
  Not from last week, not from a similar change.
- **Do not write phase-completion or "fully realized" language into docs.**
  `STATUS.md` is generated from real signals by `scripts/generate_status.py`; that is
  the status. Never hand-edit it.
- If something does not work, the docs should say so. A known gap written down is
  fine. A known gap left implied is not.

## Things about this codebase you would otherwise rediscover

- **Several core modules are duplicated** between `packages/node` and
  `packages/scheduler` — `quantization.py`, `local_boundary.py`, `kv_cache.py`,
  `transport.py`, `mesh_protocol.py`, and the `GPUInfo` pair. They exist because the
  two services used to be separate repositories. **Before adding a module, check
  whether its twin exists. If you change one of a pair, change both.**
  `tests/test_source_parity.py` records a drift budget per pair and fails if one
  drifts further. When you converge a pair, lower its budget.
- **Code for cut features is still in `packages/`.** Split inference, Raft consensus
  and KV-cache checkpointing are not part of v1 and are not mounted by anything, but
  they have not been moved out yet (ROADMAP C2). Do not build on them.
- **The distributed inference path is not implemented.** The working path proxies to
  Ollama. Do not describe split inference as working.
- **There is no persistence unless it is configured on.** See `ROADMAP.md` C3.

## Scope of what is wanted

`ROADMAP.md` is the plan, in dependency order. "Next feature" means the next
not-started item. `docs/decisions/` holds the product decisions that constrain what
is worth building — read D2 and D8 before proposing anything in Stage 3, because
several obvious-looking features were deliberately cut.

Bug fixes, tests, documentation corrections and platform fixes are always welcome and
do not need to be on the roadmap.

## Reporting security issues

Not here. See [`SECURITY.md`](SECURITY.md).
