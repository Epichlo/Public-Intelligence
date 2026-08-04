Before marking any task done, run through VERIFY.md as a separate step. Do not self-certify completion in the same pass that wrote the code. If anything in VERIFY.md can't be checked, say so explicitly instead of assuming it passed.

Read ROADMAP.md for v1 scope and feature order. When told "next feature," take the next not-started item, spec it, then build it.

# Public Intelligence

Distributed compute control plane. Three components, pinned as git submodules from
the `Public-Intelligence-Revolution` GitHub org:

- `Scheduler/` — FastAPI control plane. Node registry, matchmaking, OpenAI-compatible
  gateway (`/v1/chat/completions`, `/v1/models`, `/v1/batch`), Zenoh P2P router.
- `Node/` — FastAPI host agent. Local control API, telemetry, Docker sandbox runtime,
  Ollama-backed inference.
- `website/` — Next.js 16 / React 19 dashboard and playground. Proxies to Scheduler.

## Workflow

1. **Spec first.** Copy `specs/TEMPLATE.md` to `specs/<feature>.md` and fill it in
   before writing code. Anything bigger than a typo gets a spec.
2. **Write the test with the code**, not after. See the `test-first` skill.
3. **Verify as a separate pass.** Work through `VERIFY.md` top to bottom, paste real
   output, end with an explicit PASS or FAIL.
4. **Regenerate status:** `python3 scripts/generate_status.py`. Never hand-edit
   `STATUS.md`.

## Running things

```bash
# tests -- three suites, three interpreters
Scheduler/.venv/bin/python -m pytest Scheduler/tests -q
Node/.venv/bin/python      -m pytest Node/tests      -q
Node/.venv/bin/python      -m pytest tests           -q   # root E2E: needs BOTH packages

# lint -- these are the commands CI runs, over the WHOLE submodule, tests included.
# Linting only `src` will pass locally and still fail CI; that has happened.
Node/.venv/bin/python -m ruff check        ./Node ./Scheduler
Node/.venv/bin/python -m ruff format --check ./Node ./Scheduler

# security gate -- CI fails on MEDIUM and above only
Node/.venv/bin/python -m bandit -r ./Node/src ./Scheduler/src -x tests -ll

# installer smoke test, also run by CI
./install.sh --dry-run
```

Before pushing, run all of the above plus the three suites. CI runs on
windows-latest and macos-latest; `gh run list` and `gh run view <id>` show results.

The root suite only runs under `Node/.venv` — it is the only environment where both
`node` and `scheduler` are importable. There is no root `pyproject.toml` or
`conftest.py`.

## Things that are true about this repo, so you don't rediscover them

**All four repos have GitHub remotes and are pushed.** Root is
`Epichlo/Public-Intelligence`; the submodules are `Node-PublicIntelligence`,
`Scheduler-PublicIntelligence`, and `website-PublicIntelligence`, all on `main` with
upstreams set. `.gitmodules` exists and maps all three. Verify with `git remote -v`
rather than trusting this line.

**CI runs and has passed.** `.github/workflows/ci.yml` executes on push to `main`;
`gh run list` shows successful runs. The `gh` CLI **is** installed. Three claims
that stood here until 2026-08-04 — no remote, CI never run, no `.gitmodules` — were
all false by then and caused at least one session to report "CI unverifiable" without
checking. **Check with `gh run list`, do not repeat this paragraph as evidence.** A
green CI run still only proves what the workflow actually executes; read it before
citing it.

**Four core modules are duplicated across Node and Scheduler** — `quantization.py`
(byte-identical), `local_boundary.py`, `kv_cache.py`, `transport.py` — plus a third
copy of the artifact store at `src/shared/storage/`. A fifth pair was added on
2026-08-04: `Node/src/node/models/gpu_info.py::GPUInfo` ↔
`Scheduler/src/scheduler/models/node.py::GPUInfo`. `autonomous_orchestrator.py`
has already drifted (`Enum` vs `StrEnum`) because a fix landed on one copy only.
**Before adding a module, check whether its twin exists.** If you change one of a
pair, say explicitly whether the twin needs the same change.

**The distributed inference path is not implemented.** `Node/src/node/runtime.py`
never assigns `self.inference_backend` anything but `EchoBackend`. `LocalBoundaryEngine`
uses a 155-word vocabulary and seeded random matrices. The working inference path is
the non-split one that proxies to Ollama. Don't describe split inference as working.

**There are known auth bypasses and hardcoded credentials in the live code** —
listed with file:line in `VERIFY.md` step 3. They are pre-existing and unfixed. Do
not report them as clean, and do not let them mask a new one.

**No persistence anywhere.** `NodeRegistry` and `CreditLedger` are in-memory dicts.
Restart loses all state.

## Reporting rules

- Claims about tests, CI, or behaviour require output from **this session**. Prior
  results don't carry over.
- "I couldn't check X" is a fine thing to say. "X passes" without having run X is not.
- Don't write phase-completion or "fully realized" claims into docs. `STATUS.md` is
  generated from real signals; that is the status.
