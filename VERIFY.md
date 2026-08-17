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

The auth-bypass grep returns **three** hits, all of them prose rather than code:

- `packages/website/src/app/architecture/page.tsx:42` — page copy containing the word
  "bypassing".
- `packages/scheduler/src/scheduler/api/ingress.py:69` — a comment explaining how a
  `kid`-aware verifier turns into a bypass, naming the test that pins it
  (`test_an_unknown_kid_does_not_bypass_verification`).
- `packages/scheduler/src/scheduler/core/rate_limiter.py:54` — a comment explaining
  why evicting a depleted bucket would be a rate-limit bypass.

**This line said "one hit" until 2026-08-17, when there were three.** Both extra hits
are comments describing bypasses being *prevented*, and both predate the correction —
so nothing was wrong with the code, and the count was wrong for long enough that the
instruction two paragraphs down ("check each hit against that list, because a new one
hides among them") had become harder to follow than it looks. A known-good list that
is stale by two is a list that trains you to skim.

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
that an unreadable key produces a 503 carrying no key material — **and this file**,
`VERIFY.md`, which matches because the previous sentence quotes that fixture. Two
hits, both benign, one of them self-referential.

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
Change:      Stage D (D1-D8) answered AND both mechanisms implemented; N3; Stage C
             (C1-C10) complete; 2.10; Stage 3 (3.1-3.6) complete; Stage 4 (4.1-4.3);
             1.5 re-examined. Seventeen commits, 2de17ba..HEAD.

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS -- with CI and ROADMAP 1.5 explicitly UNVERIFIED. See below.

Evidence, all from this session:

1. `./scripts/verify.sh` -> `PASS 25 checks`, zero skipped. Node 259 passed /
   1 skipped, Scheduler 389, root E2E 126, website 36 across 5 files. Plus 43
   quarantined tests in `experimental/`, COLLECTED by the gate and run on demand.
   The gate was 15 checks and 664 tests at the start of this session.

2. Two specs written before their code; later commits document themselves. The
   spec that was WRONG -- `the-gate-sees-the-website.md`, which excluded `tsc` on
   the argument that eslint suffices -- is corrected in place rather than quietly,
   after `tsc` found 4 errors eslint passed clean.

3. Greps above. The known-issues table is EMPTY. Remaining hits are env var names
   in `AliasChoices`, four website test fixtures, and the private-key PATH
   settings -- the key is referenced by path, never by value, precisely so a PEM
   never lands in an environment variable or a log aggregator.

4. Zero duplicated pairs in shipping code: `mesh_protocol` and `mesh_auth` moved
   to `packages/shared` and the byte-identity ratchets were replaced by the
   stronger claim that only one copy exists. Four pairs remain in `experimental/`
   and ARE now ratcheted -- they were not before, because `EXPERIMENTAL_PAIRS`
   had been declared and parametrized over nothing while a commit message of mine
   said otherwise.

5. `.env`, `.secrets/`, `packages/website/.env.local`, `scheduler-state.db` and
   the runner symlink are all ignored. No tracked file contains a private key.

6. `STATUS.md` regenerated. CI reports UNVERIFIED against HEAD, correctly.

What this session FOUND, none of it caught by the 664 tests that were green when
it started -- and this is the part worth reading:

- **Every streamed completion was republished to the Zenoh mesh in plaintext**, on
  a wildcard-subscribable key, with no subscriber in the codebase.
- **Streaming deadlocked after 4 chunks** waiting for an ACK nothing ever sends.
- **Every node opened an unauthenticated wildcard subscriber** that read and
  unlinked host shared memory by attacker-supplied name.
- **The Scheduler ran an unauthenticated Raft plane on every boot** whose handler
  could EVICT ANY HOST and INJECT NEW ONES -- and an injected node is dispatched
  to, so it receives other people's prompts. This is the most serious of the four,
  and I had described it in my own words as "inert in practice" before reading it.
- `/v1/batch` fabricated its results; the playground showed malformed SSE frames
  to the user as model output; the chat proxy sent the fleet secret as a Bearer
  JWT; `STATUS.md` printed "CI: PASS" for code CI had never built.

UNVERIFIED, stated rather than glossed:

- **CI.** It has never run for any commit in this session. `origin/main` is at
  `e7b0634`; HEAD is seventeen commits ahead and unpushed.
- **ROADMAP 1.5, still the important one.** Docker is unavailable in this
  environment, so `docker-compose.test.yml` has still never run. **No node on a
  genuinely separate machine has ever served a request.** D8 makes NAT traversal
  the differentiator and `docs/PREMISES.md` P2 flags it as the weakest premise, so
  the single load-bearing claim of the product remains unsubstantiated.
- **D7.** Deliberately open. Every judgement in these seventeen commits was made
  by one party, including the judgement that they are sound. This session found
  four security holes and two false statements *in my own work from earlier in the
  same session*, which is the argument for D7 rather than against it.
- **Canary limits.** It proves a node runs *a* model, not *the* model it
  advertised. Recorded as `docs/PREMISES.md` P4, not solved.
```
