# VERIFY

The fixed checklist every change passes before anyone calls it done.

**This runs as a separate pass from the one that wrote the code.** Do not write an
implementation and certify it in the same breath — that is the failure mode this
file exists to prevent.

Rules that override everything else below:

- **Paste real output.** Every check that runs a command shows the command and its
  actual terminal output. Summarising output as "tests pass" is not a check.
- **A check you could not run is `UNVERIFIED`, never `PASS`.** Say which check,
  and why it could not run. Guessing is worse than admitting the gap.
- **`PASS` requires having run something in this session.** Output from an earlier
  session, or from the last time someone looked, does not count.

---

## 1. Run the test suite

Run all three. They need different interpreters — the root suite is the only one
that imports both `node` and `scheduler`, so it only works under `Node/.venv`.

```bash
Scheduler/.venv/bin/python -m pytest Scheduler/tests -q   # Scheduler suite
Node/.venv/bin/python      -m pytest Node/tests      -q   # Node suite
Node/.venv/bin/python      -m pytest tests           -q   # root E2E suite
```

Paste the real tail of each run, including the counts line.

- [ ] All three suites run to completion
- [ ] Pass/fail counts recorded below, copied from actual output
- [ ] Any new test added by this change is named here, and was **observed failing
      before the fix and passing after** — an assertion that never failed proves nothing

```
<paste output here>
```

## 2. Check the change against its spec

- [ ] The spec file exists: `specs/<feature>.md`
- [ ] Every box under "Done looks like" is ticked, each with the command or file
      that proves it
- [ ] Nothing was built that the spec lists under "Out of scope" — if scope grew,
      the spec was updated first, deliberately, not retroactively to match the code

If there is no spec for this change, that is a **FAIL** for anything larger than a
typo fix. Write the spec, then come back.

## 3. Grep for secrets, default credentials, and auth bypasses

```bash
# hardcoded credential material -- catches inline literals, embedded keys, AND
# literal fallbacks passed to os.environ.get(). Verified against the known-bad
# cases below: if this grep comes back clean, the pattern is broken, not the code.
grep -rniE "(secret|token|password|passwd|api[_-]?key|private[_-]?key)[a-z0-9_]*[\"']?\s*[,:=]\s*[\"'][^\"'{}\$]{8,}[\"']|BEGIN (RSA )?(PUBLIC|PRIVATE) KEY" \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  Node/src Scheduler/src src website/src

# auth bypasses / dev backdoors on an authenticated path
grep -rnE "dev_token|bypass|skip[_-]?auth|allow[_-]?all|== *[\"']dev[\"']|startswith\(\"dev" \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  Node/src Scheduler/src src website/src

# CORS wildcard combined with credentials
grep -rn -A3 "allow_origins" Node/src Scheduler/src
```

- [ ] No new hardcoded secret, key, or credential
- [ ] No new auth bypass on any authenticated route
- [ ] Any pre-existing hit is listed below as known, not silently passed over

The first grep returns two benign hits — `AliasChoices("NODE_NETWORK_AUTH_TOKEN", ...)`
in `Node/src/node/core/configuration.py:88` and `Scheduler/src/scheduler/core/config.py:46`
— which declare env var *names*, not values. Everything else it returns is real.

**Known pre-existing hits as of 2026-08-03** — these are real and unfixed. Do not
let them mask a *new* one, and do not report them as clean:

| Location | Issue |
|---|---|
| `Node/src/node/core/telemetry.py:175`, `Scheduler/src/scheduler/core/zenoh_router.py:280` | `TELEMETRY_SECRET_KEY` defaults to a constant published in this repo (ROADMAP 2.2) |
| `Scheduler/src/scheduler/api/ingress.py:16` | hardcoded fallback RSA public key |
| `Scheduler/src/scheduler/main.py:76`, `Node/src/node/main.py:43` | `allow_origins=["*"]` with `allow_credentials=True` (ROADMAP 2.3) |

Two rows previously listed here were **removed on 2026-08-03 because they are fixed**,
verified by the greps in this step returning no hit for either:

- `ingress.py:56` `Bearer dev_*` → `tenant-dev`, and the website proxy's default
  `Bearer dev_token`. Both were removed in commit `9f2c264`; `ingress.py` now verifies
  RS256 with no bypass branch, and the proxy rejects an unauthenticated request rather
  than synthesising a credential.

The `zenoh_router.py` line number moved from 255 to 280 as that file grew; the issue is
unchanged.

## 4. Check for duplicated logic before adding new files

This repo already carries four cross-repo copy-paste duplicates. Adding a fifth is
the single easiest way to make it worse.

```bash
# does something with this name already exist?
find Node/src Scheduler/src src -name "*<keyword>*"

# does a module with this purpose already exist under a different name?
grep -rn "class <NewClassName>\|def <new_function_name>" Node/src Scheduler/src src
```

- [ ] Searched for an existing implementation before writing a new one
- [ ] If a near-duplicate exists, the change extends it or the duplication is
      justified in writing below

**Known duplicate pairs** — if you touch one, state explicitly whether the twin
needs the same change:

| Pair | Status |
|---|---|
| `Node/src/node/core/quantization.py` ↔ `Scheduler/src/scheduler/core/quantization.py` | byte-identical |
| `Node/src/node/core/local_boundary.py` ↔ `Scheduler/.../local_boundary.py` | 378 lines, differs only in imports |
| `Node/src/node/core/kv_cache.py` ↔ `Scheduler/.../kv_cache.py` | near-identical |
| `Node/src/node/core/transport.py` ↔ `Scheduler/.../transport.py` | ~508 lines, formatting drift |
| `Node/src/node/core/autonomous_orchestrator.py` ↔ `Scheduler/.../autonomous_orchestrator.py` | **already diverged** (`Enum` vs `StrEnum`) |
| `src/shared/storage/` ↔ `Node/src/shared/storage/` | third copy of the artifact store |

## 5. Confirm no secrets or .env files are tracked

```bash
# is anything sensitive tracked, in the root repo or any submodule?
git ls-files | grep -iE "\.env|\.pem$|\.key$|credential|secret" || echo "root: clean"
for d in Node Scheduler website; do
  echo "-- $d --"
  git -C "$d" ls-files | grep -iE "\.env|\.pem$|\.key$|credential|secret" || echo "clean"
done

# does .gitignore actually cover them?
for d in . Node Scheduler website; do
  printf "%-12s " "$d"; git -C "$d" check-ignore -q .env && echo ".env ignored" || echo "!! .env NOT ignored"
done
```

- [ ] No `.env`, key, or credential file tracked in root or any submodule
- [ ] `.gitignore` covers `.env` in every repo that has one
- [ ] `git diff --cached` reviewed for inline secrets before commit

## 6. Regenerate STATUS.md

```bash
python3 scripts/generate_status.py
```

- [ ] `STATUS.md` regenerated from this session's real runs
- [ ] Its counts match the output pasted in step 1

Never hand-edit `STATUS.md`. If a number in it looks wrong, fix the script or fix
the code — not the file.

---

## Verdict

Fill this in. It is the whole point of the file.

```
Date:        2026-08-04
Change:      ROADMAP 1.2 — nodes advertise measured hardware instead of a hardcoded
             16 GB "unknown" GPU; GET /nodes gains a derived `reachability` field.
Spec:        specs/real-hardware-advertisement.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS-WITH-GAPS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS (new duplicate, justified in writing)
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS-WITH-GAPS

Reasons:
- 1. Scheduler 213 passed / Node 231 passed, 1 skipped / root E2E 29 passed, all run
  in this session. 22 tests are new across 4 files. Each was observed failing first:
  the Node hardware tests were run against a stub reproducing the old hardcoded values
  and failed 8/9 on the intended assertions (including `assert 16.0 == 24.0` for RAM);
  the Scheduler tests failed with a real 422 `"Input should be greater than 0"` before
  `gt=0` was relaxed, and `KeyError: 'reachability'` before the view model existed.
- 2. GAP: the NVIDIA branch is unverified on real hardware. This machine has no
  NVIDIA GPU (`command -v nvidia-smi` → not found), so that path is exercised only
  against a synthetic collector result. The Apple Silicon branch WAS checked live
  against `sysctl` (`Apple M5`, 25769803776 bytes → advertised 24.0 GB). The
  underlying `nvidia-smi` invocation is pre-existing code in `telemetry/collector.py`
  and was not modified. Everything else in "Done looks like" is ticked with the test
  or command that proves it.
- 3. Five hits, all pre-existing and all already listed in step 3 of this file:
  `TELEMETRY_SECRET_KEY` defaults (telemetry.py:175, zenoh_router.py:280), the
  fallback RSA public key (ingress.py:16), and `allow_origins=["*"]` with
  `allow_credentials=True` in both services. Two benign `AliasChoices` hits declare
  env var names, not values — their line numbers have drifted to
  configuration.py:92 and config.py:50 (this file still says 88 and 46). The auth-bypass
  grep returned one hit, prose in `website/src/app/architecture/page.tsx:42`, not code.
  No new secret, credential, or bypass was introduced.
- 4. This change adds a FIFTH duplicated pair: `node/models/gpu_info.py::GPUInfo` now
  mirrors `scheduler/models/node.py::GPUInfo`. Searched first — no existing shared
  location holds it, and the two are separate services with separate wire contracts.
  Both files carry a comment saying a change to one requires the same change to the
  other. `nvidia-smi` parsing was NOT duplicated: `hardware.py` reuses the existing
  `telemetry/collector.py` parser rather than writing a second one.
- 5. Only `.env.example` is tracked in Node and Scheduler; both contain non-secret
  defaults only (ports, URLs, log levels). `.env` is ignored in all four repos.
- 6. Regenerated by `scripts/generate_status.py`; its counts (213/231/29) match step 1.

Not claimed: CI (no remote, never run — see below), and any behaviour on a second
physical machine. This change does not affect roadmap 1.5 either way.
```

**A verdict of PASS with any line marked UNVERIFIED is not a PASS.** Report it as
FAIL, or as PASS-WITH-GAPS naming every gap. The point of this file is that the
next person can trust the verdict without re-deriving it.

---

## Repo-level checks that currently cannot pass

These are environment facts, not per-change failures. They are listed so no one
mistakes them for verified. Re-check when they change.

- **No git remote is configured on the root repo** (`git remote -v` is empty).
  Nothing is backed up or pushed. Submodules have GitHub remotes; the workspace
  that pins them does not.
- **`.github/workflows/ci.yml` has never executed.** It needs a remote to run on,
  and it checks out with `submodules: recursive` while no `.gitmodules` file
  exists — so `Node/`, `Scheduler/`, and `website/` would come up empty and
  `pip install -e ./Node` would fail on step one.
- **CI status cannot be queried** — the `gh` CLI is not installed on this machine.

Until those are fixed, any "CI passed" claim is unverifiable. `generate_status.py`
reports CI as `UNVERIFIABLE` for exactly this reason.
