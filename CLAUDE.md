Before marking any task done, run through VERIFY.md as a separate step. Do not self-certify completion in the same pass that wrote the code. If anything in VERIFY.md can't be checked, say so explicitly instead of assuming it passed.

Read ROADMAP.md for v1 scope and feature order. When told "next feature," take the next not-started item, spec it, then build it.

# Public Intelligence

Distributed compute control plane. **One repository** — the three components used
to be git submodules and were merged into `packages/` on 2026-08-04. The old repos
still exist on GitHub, each tagged `pre-monorepo-2026-08-04`.

- `packages/scheduler/` — FastAPI control plane. Node registry, matchmaking, OpenAI-compatible
  gateway (`/v1/chat/completions`, `/v1/models`, `/v1/batch`), Zenoh P2P router.
- `packages/node/` — FastAPI host agent. Local control API, telemetry, Docker sandbox runtime,
  Ollama-backed inference.
- `packages/website/` — Next.js 16 / React 19 dashboard and playground. Proxies to Scheduler.

## Workflow

1. **Spec first.** Copy `specs/TEMPLATE.md` to `specs/<feature>.md` and fill it in
   before writing code. Anything bigger than a typo gets a spec.
2. **Write the test with the code**, not after. See the `test-first` skill.
3. **Verify as a separate pass.** Work through `VERIFY.md` top to bottom, paste real
   output, end with an explicit PASS or FAIL.
4. **Regenerate status:** `python3 scripts/generate_status.py`. Never hand-edit
   `STATUS.md`.

## Running things

One venv, one interpreter, everything. Set it up once per clone:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e packages/shared \
  -e "packages/node[dev]" -e "packages/scheduler[dev]"
./scripts/install-hooks.sh
```

**Do not run linters, mypy, pytest, or bandit individually. Run the gate:**

```bash
./scripts/verify.sh           # everything CI runs, in one command
./scripts/verify.sh --quick   # skips cross-package tests + installer, tight loop
```

`.github/workflows/ci.yml` invokes that same script and nothing else, so there is
exactly one definition of "does this pass". Adding a check means editing
`scripts/verify.sh` — never adding a step to the workflow.
`tests/test_source_parity.py` fails if CI grows its own check list again.

Run `./scripts/install-hooks.sh` once per clone to get a pre-push hook that runs
the gate before any push. The gate writes `zones/verified/latest.verified.json`
recording what ran and against which tree; if its `commit` or `state_fingerprint`
is not the tree in front of you, whatever it says is about code that no longer
exists.

## The governance layer enforces the rules above

`.claude/` turns the three rules in Workflow from requests into OS-level facts:

- `.claude/rules/` — path-scoped rules loaded as project memory.
  **`.claude/rules/verification.md` is the load-bearing one:** the agent that wrote
  code may not decide it is verified.
- `.claude/hooks/require-proof-stop.py` — a Stop hook that refuses to end a session
  that changed code without a matching passing bundle. It recomputes the fingerprint
  rather than believing the file.
- `.claude/hooks/block-protected-paths.py` — denies writes to secrets and to
  `zones/verified/`, including via shell redirection.
- `.claude/agents/` — `implementer` writes code and may not declare it verified;
  `independent-verifier` runs in its own worktree with `Write`/`Edit` denied.

`zones/claimed/` is what an agent believes. `zones/verified/` is what the gate
measured. See `zones/README.md` and `docs/CLAUDE_CODE_ARCHITECTURE.md`.

`tests/` at the repo root holds the cross-package tests — the node/scheduler wire
contract and the duplicate-module ratchets. They assert relationships *between* the
packages, which is why they are not inside either one. Before the monorepo migration
they could only run under `Node/.venv`; now one root `.venv` runs everything.

## Things that are true about this repo, so you don't rediscover them

**Facts about remotes, CI, interpreter/tool versions, and how far the
duplicated modules have drifted are GENERATED — read the "Repo facts" section of
`STATUS.md`, and regenerate it rather than trusting any prose about them.**

This section used to assert those facts in prose. It said the root repo had no
remote, that `.gitmodules` did not exist, and that CI had never run. All were false,
and a session repeated them in a completion report instead of spending one command
checking — reporting "CI unverifiable" for a change whose CI run had already failed.
Prose cannot notice when it goes stale. Only judgment lives here now; measurements
live in `STATUS.md`.

**`packages/shared/` now exists** (ROADMAP C8), and `mesh_protocol.py` / `mesh_auth.py`
live there as `pi_shared`, with thin re-export shims at the old import paths. There is
one copy; there is nothing to keep in step. Put a module there when the two services
disagreeing about it would fail **silently** — mesh divergence is the case that
matters, because the Scheduler just stops accepting real nodes and nothing raises.

**Four pairs are still duplicated, in `experimental/`** — `quantization.py`,
`local_boundary.py`, `kv_cache.py`, `transport.py`. They are cut from v1 and are not
shipped, so converging them buys nothing; `tests/test_source_parity.py` ratchets them
where they sit. The artifact store's three copies are down to one at
`packages/node/src/node/storage/`.

**Before adding a module, check whether its twin exists.** If you change one of a
remaining pair, change both.

This is now enforced, not just requested: `tests/test_source_parity.py` records a
drift budget per pair and fails if one drifts further, and
`tests/test_wire_contract.py` feeds the Node's real serialiser output to the
Scheduler's real models. Current drift is in `STATUS.md`. When you converge a pair,
lower its budget so the ratchet holds.

**The distributed inference path is not implemented.** `packages/node/src/node/runtime.py`
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
