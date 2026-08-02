Before marking any task done, run through VERIFY.md as a separate step. Do not self-certify completion in the same pass that wrote the code. If anything in VERIFY.md can't be checked, say so explicitly instead of assuming it passed.

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

# lint / types
Scheduler/.venv/bin/python -m ruff check Scheduler/src
Node/.venv/bin/python      -m ruff check Node/src
```

The root suite only runs under `Node/.venv` — it is the only environment where both
`node` and `scheduler` are importable. There is no root `pyproject.toml` or
`conftest.py`.

## Things that are true about this repo, so you don't rediscover them

**No git remote is configured on the root repo.** `git remote -v` is empty. Nothing
is pushed or backed up. The submodules have GitHub remotes; the workspace pinning
them does not.

**CI has never run.** `.github/workflows/ci.yml` needs a remote, and it checks out
with `submodules: recursive` while no `.gitmodules` file exists — so the three
submodule directories would come up empty and `pip install -e ./Node` would fail
immediately. Do not cite CI as evidence of anything.

**Four core modules are duplicated across Node and Scheduler** — `quantization.py`
(byte-identical), `local_boundary.py`, `kv_cache.py`, `transport.py` — plus a third
copy of the artifact store at `src/shared/storage/`. `autonomous_orchestrator.py`
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
