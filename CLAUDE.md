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

**Do not run linters, mypy, or bandit individually. Run the gate:**

```bash
./scripts/verify.sh           # everything CI runs, in one command
./scripts/verify.sh --quick   # skips root E2E + installer, for a tight loop
```

`.github/workflows/ci.yml` invokes that same script and nothing else, so there is
exactly one definition of "does this pass". Adding a check means editing
`scripts/verify.sh` — never adding a step to the workflow.
`tests/test_source_parity.py` fails if CI grows its own check list again.

Run `./scripts/install-hooks.sh` once per clone to get a pre-push hook that runs
the gate before any push. It writes `.verify-receipt.json`; if that file's commit
is not `HEAD`, whatever it says is about code that no longer exists.

The root suite only runs under `Node/.venv` — it is the only environment where both
`node` and `scheduler` are importable. There is no root `pyproject.toml` or
`conftest.py`.

## Things that are true about this repo, so you don't rediscover them

**Facts about remotes, CI, submodules, interpreter/tool versions, and how far the
duplicated modules have drifted are GENERATED — read the "Repo facts" section of
`STATUS.md`, and regenerate it rather than trusting any prose about them.**

This section used to assert those facts in prose. It said the root repo had no
remote, that `.gitmodules` did not exist, and that CI had never run. All were false,
and a session repeated them in a completion report instead of spending one command
checking — reporting "CI unverifiable" for a change whose CI run had already failed.
Prose cannot notice when it goes stale. Only judgment lives here now; measurements
live in `STATUS.md`.

**Several core modules are duplicated across Node and Scheduler** — `quantization.py`,
`local_boundary.py`, `kv_cache.py`, `transport.py`, `mesh_protocol.py`, and the
`GPUInfo` pair — plus a third copy of the artifact store at `src/shared/storage/`.
They exist because the two services are separate git repositories with no shared
installable package. **Before adding a module, check whether its twin exists.** If
you change one of a pair, change both.

This is now enforced, not just requested: `tests/test_source_parity.py` records a
drift budget per pair and fails if one drifts further, and
`tests/test_wire_contract.py` feeds the Node's real serialiser output to the
Scheduler's real models. Current drift is in `STATUS.md`. When you converge a pair,
lower its budget so the ratchet holds.

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
