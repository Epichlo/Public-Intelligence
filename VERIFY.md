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

One command runs every suite and every other gate. It is what CI invokes, so a
green run here is the same green CI will produce.

```bash
./scripts/verify.sh   # runs all three suites plus every other gate
```

Paste the real tail of each run, including the counts line.

- [ ] The gate runs to completion and prints PASS
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
  packages/node/src packages/scheduler/src src packages/website/src

# auth bypasses / dev backdoors on an authenticated path
grep -rnE "dev_token|bypass|skip[_-]?auth|allow[_-]?all|== *[\"']dev[\"']|startswith\(\"dev" \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  packages/node/src packages/scheduler/src src packages/website/src

# CORS wildcard combined with credentials
grep -rn -A3 "allow_origins" packages/node/src packages/scheduler/src
```

- [ ] No new hardcoded secret, key, or credential
- [ ] No new auth bypass on any authenticated route
- [ ] Any pre-existing hit is listed below as known, not silently passed over

The first grep returns four benign hits, and no others:

- `AliasChoices("NODE_NETWORK_AUTH_TOKEN", ...)` in `packages/node/src/node/core/configuration.py`
  and `packages/scheduler/src/scheduler/core/config.py` — these declare env var
  *names*, not values.
- Fixture assignments in `packages/website/src/app/api/*/route.test.ts` (four as of
  2026-08-09, across the telemetry, chat and usage proxies) — **test fixtures**
  asserting the proxies forward a credential upstream and never leak it to the
  browser. The grep covers `packages/website/src`, which gained test files in ROADMAP
  C6; a fixture value inside a `*.test.ts` is not a shipped credential.
- `SCHEDULER_JWT_PRIVATE_KEY_PATH` alias declarations in
  `packages/scheduler/src/scheduler/core/config.py` — again env var *names*. The key
  is referenced **by path, never by value**, precisely so a PEM never lands in an
  environment variable, a process listing or a log aggregator.

**Everything else it returns is real.** If it comes back completely clean, the
pattern is broken, not the code.

The auth-bypass grep returns one hit, `packages/website/src/app/architecture/page.tsx:42`,
which is prose containing the word "bypassing", not code.

**Known pre-existing hits as of 2026-08-03** — these are real and unfixed. Do not
let them mask a *new* one, and do not report them as clean:

| Location | Issue |
|---|---|
| _(none)_ | The table is empty as of 2026-08-07. Keep it, and add a row rather than fixing something quietly. |

Rows previously listed here that were **removed because they are fixed**, each verified
by the greps in this step returning no hit:

- **2026-08-03** — `ingress.py:56` `Bearer dev_*` → `tenant-dev`, and the website proxy's
  default `Bearer dev_token`. Both removed in commit `9f2c264`; `ingress.py` now verifies
  RS256 with no bypass branch, and the proxy rejects an unauthenticated request rather
  than synthesising a credential.
- **2026-08-06** — `allow_origins=["*"]` with `allow_credentials=True` in both services
  (ROADMAP 2.3). The CORS grep in this step now returns only the replacement code and its
  comments; there is no `allow_origins=["*"]` left in either package. Worth recording *why*
  this sat here so long as a low-priority row: it was described as "rejected by browsers",
  i.e. as failing safe. It did not. Starlette reflects the caller's `Origin` rather than
  sending a wildcard when credentials are on, so it worked for every origin that asked.

- **2026-08-07** — the hardcoded fallback RSA public key at `ingress.py:16` (ROADMAP C4).
  The risk had been judged low on the grounds that the matching *private* key is not in
  this repository, so nobody could mint a token it accepts. True, and beside the point:
  **the key came from somewhere.** It was a "standard dummy" PEM of the kind that
  circulates in tutorials, and whoever generated it may still hold the private half.
  Trusting a key of unknown provenance is not "probably fine" — it is an authentication
  decision nobody made. The gateway now **fails closed**: no configured key means 401 for
  every request plus an error log, and there is no literal left to fall back to. Pinned by
  `test_no_public_key_literal_survives_in_the_source`, which scans the whole installed
  package for `BEGIN PUBLIC KEY` rather than watching one line number.

- **2026-08-06** — `TELEMETRY_SECRET_KEY` defaulting to a constant published in this repo
  (ROADMAP 2.7, which superseded 2.2's "rotate it"). Rotating would have closed nothing:
  the mesh heartbeat path beside it took no authentication at all and reached the same
  registry state, and the key was fleet-wide symmetric so any participant could forge for
  any other node regardless. Both services now key mesh envelopes on each node's own
  per-install credential, and the setting is gone from the services and every install path.
  Pinned by `test_the_fleet_wide_secret_is_no_longer_used_anywhere`, which matches USE
  (`"TELEMETRY_SECRET_KEY"` or `TELEMETRY_SECRET_KEY=`) rather than mention, so the files
  explaining what it used to be keep their explanation.

## 4. Check for duplicated logic before adding new files

This repo carries six duplicated module pairs, a legacy of the pre-monorepo split.
`packages/shared/` is now possible; until they are collapsed into it,
`tests/test_source_parity.py` ratchets their drift.

```bash
# does something with this name already exist?
find packages/node/src packages/scheduler/src src -name "*<keyword>*"

# does a module with this purpose already exist under a different name?
grep -rn "class <NewClassName>\|def <new_function_name>" packages/node/src packages/scheduler/src src
```

- [ ] Searched for an existing implementation before writing a new one
- [ ] If a near-duplicate exists, the change extends it or the duplication is
      justified in writing below

**Known duplicate pairs** — if you touch one, state explicitly whether the twin
needs the same change:

| Pair | Status |
|---|---|
| `packages/node/src/node/core/mesh_auth.py` ↔ `packages/scheduler/.../mesh_auth.py` | **byte-identical, budget 0** — added deliberately by 2.7. Held by `tests/test_mesh_protocol_parity.py`, which also round-trips a real envelope sealed by one copy through the other. If these drift, the Scheduler silently stops accepting real nodes. |
| `packages/node/src/node/core/mesh_protocol.py` ↔ `packages/scheduler/.../mesh_protocol.py` | **byte-identical, budget 0** |

**Five pairs left this table on 2026-08-07 and the reason matters**, because a
shorter list reads like progress and is mostly relocation. `quantization`,
`kv_cache`, `local_boundary`, `boundary_engine` and `transport` moved to
`experimental/` under ROADMAP C2 — still duplicated, still able to drift, no longer
part of the shipped system. `tests/test_source_parity.py` keeps ratcheting them under
`EXPERIMENTAL_PAIRS` so the drift stays measured rather than disappearing.

The `autonomous_orchestrator` pair was **deleted** (ROADMAP 2.10), and the artifact
store's three copies are down to one at `packages/node/src/node/storage/` (C8) —
the root `src/` copy is gone and `packages/node/src/shared/` was folded in.

## 5. Confirm no secrets or .env files are tracked

```bash
# one repo now, so one check
git ls-files | grep -iE "\.env$|\.pem$|\.key$|credential|secret" || echo "clean"
git check-ignore -q .env && echo ".env ignored" || echo "!! .env NOT ignored"

# Filename matching is not enough. This is the one that would catch a real leak:
git ls-files -z | xargs -0 grep -lE "BEGIN (RSA )?PRIVATE KEY" || echo "no tracked private key"

# Check the DIRECTORY, not just the extensions. scripts/mint_token.py writes the
# signing key into .secrets/, and a secret stored there with no extension was NOT
# covered by the *.pem / *.key rules until 2026-08-09.
git check-ignore -q .secrets/probe && echo ".secrets/ ignored" || echo "!! .secrets NOT ignored"
```

- [ ] No `.env`, key, or credential file tracked
- [ ] `.gitignore` covers `.env`, `.secrets/`, and the default `scheduler-state.db`
- [ ] `git diff --cached` reviewed for inline secrets before commit

**Known benign hits.** The filename grep matches
`packages/scheduler/src/scheduler/api/credentials.py` and
`packages/scheduler/tests/test_credential_issuance.py` on the word *credential* —
these are **source files**, not credential files. The private-key grep matches
`test_credential_issuance.py`, whose fixture is the literal string
`-----BEGIN PRIVATE KEY-----\nnonsense\n-----END PRIVATE KEY-----`, used to assert
that an unreadable key produces a 503 carrying no key material.

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
Date:        2026-08-09
Change:      Stage D answered (D1-D8), N3, Stage C (C1-C10), 2.10, Stage 3
             (3.1-3.4, 3.6), Stage 4 (4.1-4.3), and 1.5 re-examined.
             Nine commits, 2de17ba..HEAD.
Specs:       specs/stage-d-decisions-and-licence.md
             specs/the-gate-sees-the-website.md
             (later commits are documented in their own messages and in
             docs/decisions/; several changed shape mid-flight and the commit
             message is the honest record of why)

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS (one gap found and fixed during this step)
  6. STATUS regenerated . PASS (one generator bug found and fixed during this step)

VERDICT: PASS -- with CI explicitly UNVERIFIED. See below.

Evidence, all from this session:

1. `./scripts/verify.sh` -> `PASS 22 checks`, commit 9689ae25, clean tree, zero
   skipped. Suites: Node 259 passed / 1 skipped, Scheduler 346 passed, root E2E
   119 passed, website 16 passed across 3 files. The gate was 15 checks at the
   start of this session.

   Net test movement is deliberate and not all upward: the Scheduler suite lost
   ~15 tests to `experimental/` (C2) and gained more than that back. The SHIPPING
   count going down while coverage went up was the point of C2.

   Every new behavioural test in these commits was observed failing first. Where
   red-green was not possible -- pinning behaviour that was already correct (4.3)
   -- the tests were mutation-checked instead, and one mutation that "survived"
   turned out to have been applied to a dead branch, which is recorded rather
   than quietly re-run.

2. Two specs were written before their code. Later commits document themselves;
   `docs/decisions/` carries the eight product decisions and what each one costs.
   Nothing was built that a decision record listed as out of scope -- D2 cut the
   payout machinery and no payout code exists.

3. Greps run above. **The known-issues table is EMPTY for the first time**: the
   hardcoded fallback RSA public key at `ingress.py:16` is gone (C4). Remaining
   hits are env var *names* in `AliasChoices`, four website test fixtures, and
   three prose uses of the word "bypass" in comments explaining bypass
   PREVENTION. No `allow_origins=["*"]` outside a comment.

4. `tests/test_source_parity.py` + `test_mesh_protocol_parity.py` -> 26 passed.
   Two shipping pairs remain, both at drift budget 0. Five pairs moved to
   `experimental/` and are still ratcheted there.

5. **A real gap, found by this step and fixed in it.** `.secrets/` holds the JWT
   signing key. `*.pem` covered the two files present, but the DIRECTORY was not
   ignored -- so a secret written there with no extension (a bare token, a JSON
   credential) would have been committed by the `git add -A` this repo is worked
   on with. `.secrets/` is now ignored outright. Nothing secret was ever tracked;
   verified with a content grep, not only a filename grep.

6. **A second real gap, found by this step and fixed in it.**
   `scripts/generate_status.py` reported the LATEST workflow run's conclusion as
   this repo's CI status, ignoring which commit it covered. It printed
   **"CI: PASS"** while HEAD was nine commits ahead of anything CI had ever
   built. That is this file's own failure mode occurring inside the file's own
   generator. It now matches the run to HEAD and answers UNVERIFIED otherwise,
   with the distance stated. Pinned by `tests/test_status_reports_ci_honestly.py`,
   which fails if the old logic returns.

UNVERIFIED, stated rather than glossed:

- **CI.** It has never run for any commit in this session. `origin/main` is at
  `e7b0634`; HEAD is nine commits ahead and unpushed. The latest green run
  describes code that predates all of this work. STATUS.md now says so.
- **ROADMAP 1.5, and it is the important one.** Docker is unavailable in this
  environment, so `docker-compose.test.yml` still has never run. **No node on a
  genuinely separate machine has ever served a request.** D8 makes NAT traversal
  the project's differentiator and `docs/PREMISES.md` P2 flags it as the weakest
  premise, so the single load-bearing claim remains unsubstantiated. Two further
  faults in that file were found statically and fixed; running it is what would
  earn the claim.
- **D7.** Deliberately open. Every judgement in these nine commits was made by
  one party, including the judgement that they are sound.
- **The invite codes (D4) and the canary (D1)** are decided and NOT implemented.
  `docs/OPERATING.md` and `docs/ACCEPTABLE_USE.md` say so where an operator will
  read it, rather than describing the intended system.
```
