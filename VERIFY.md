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

The first grep returns two benign hits — `AliasChoices("NODE_NETWORK_AUTH_TOKEN", ...)`
in `packages/node/src/node/core/configuration.py:105` and `packages/scheduler/src/scheduler/core/config.py:54`
— which declare env var *names*, not values. Everything else it returns is real.

The auth-bypass grep returns one hit, `packages/website/src/app/architecture/page.tsx:42`,
which is prose containing the word "bypassing", not code.

**Known pre-existing hits as of 2026-08-03** — these are real and unfixed. Do not
let them mask a *new* one, and do not report them as clean:

| Location | Issue |
|---|---|
| `packages/scheduler/src/scheduler/api/ingress.py:16` | hardcoded fallback RSA public key |

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
| `packages/node/src/node/core/quantization.py` ↔ `packages/scheduler/src/scheduler/core/quantization.py` | byte-identical |
| `packages/node/src/node/core/local_boundary.py` ↔ `packages/scheduler/.../local_boundary.py` | 378 lines, differs only in imports |
| `packages/node/src/node/core/kv_cache.py` ↔ `packages/scheduler/.../kv_cache.py` | near-identical |
| `packages/node/src/node/core/transport.py` ↔ `packages/scheduler/.../transport.py` | ~508 lines, formatting drift |
| `packages/node/src/node/core/autonomous_orchestrator.py` ↔ `packages/scheduler/.../autonomous_orchestrator.py` | **already diverged** (`Enum` vs `StrEnum`) |
| `src/shared/storage/` ↔ `packages/node/src/shared/storage/` | third copy of the artifact store |
| `packages/node/src/node/core/mesh_auth.py` ↔ `packages/scheduler/.../mesh_auth.py` | **byte-identical, budget 0** — added deliberately by 2.7. Held by `tests/test_mesh_protocol_parity.py`, which also round-trips a real envelope sealed by one copy through the other. If these drift, the Scheduler silently stops accepting real nodes. |

## 5. Confirm no secrets or .env files are tracked

```bash
# one repo now, so one check
git ls-files | grep -iE "\.env$|\.pem$|\.key$|credential|secret" || echo "clean"
git check-ignore -q .env && echo ".env ignored" || echo "!! .env NOT ignored"
```

- [ ] No `.env`, key, or credential file tracked
- [ ] `.gitignore` covers `.env`
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
Date:        2026-08-07
Change:      ROADMAP N1 — the gateway stops returning fabricated text as a
             successful completion.
Spec:        specs/stop-returning-fabricated-completions.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS

Reasons:
- 1. `./scripts/verify.sh` -> `PASS 15 checks`, this session. Scheduler 311 passed,
  Node 280 / 1 skipped, root E2E 73. Net -5 on Scheduler: +6 new in
  `test_split_inference_refused.py`, -5 from deleting
  `test_openai_split_inference.py`, and one existing test renamed.
- 1a. Red observed first, and the STARTING evidence was a live probe rather than a
  test: a valid RS256 JWT plus `x-split-inference: true` asking "What is the capital
  of France?" returned `HTTP 200` with `content: 'token_556'`. 5 of the 6 new tests
  then failed against unfixed code.
- 1b. TWO OF MY OWN TESTS WERE WRONG AGAIN, same shape as earlier in this session:
  * `test_the_gateway_no_longer_reaches_the_simulation` failed because the only
    remaining mention of `LocalBoundaryEngine` is the COMMENT explaining the
    history. Rewritten to match use, not mention -- it now strips comment lines
    first. Same reasoning as the archived-repo check in `test_installer_paths.py`.
  * `test_the_settings_flag_refuses_every_request` failed with
    `"Settings" object has no field "enable_split_inference"`, which is a FINDING,
    not a test bug -- see 2a.
- 1c. DELETED `packages/scheduler/tests/test_openai_split_inference.py` in full. All
  5 of its tests asserted that the simulated split path returned well-formed
  completions. They passed for years and were evidence for nothing: the suite
  asserted the path returned *something*, never that what it returned was real.
  That is the lesson worth keeping from this item.
- 2. Every box under "Done looks like" is ticked, one of them CORRECTED -- see 2a.
  Nothing under "Out of scope" was built: `local_boundary`, `transport`, `kv_cache`
  and `quantization` are untouched (ROADMAP C2), split inference is not
  implemented, and the three module-level test files that never call the endpoint
  are left alone.
- 2a. SPEC CORRECTION. The spec claimed the `enable_split_inference` setting "keeps
  working, as a way to get 501s". Writing the test disproved it: `Settings` has no
  such field and never did, so `getattr(get_settings(), "enable_split_inference",
  False)` was permanently False. A third trigger that could never fire, and an
  operator setting `SCHEDULER_ENABLE_SPLIT_INFERENCE` got nothing, silently. The
  `getattr` is kept so that adding the field later refuses rather than fabricates,
  and a test now pins the field's absence.
- 3. Unchanged: the fallback RSA public key at `ingress.py:16` and the two benign
  `AliasChoices` env-var-name hits. No new secret or bypass. This change only
  removes a capability.
- 4. No new module. 250 lines removed from `openai.py` (613 -> 395). It no longer
  imports `LocalBoundaryEngine`, and the `transport` import it dropped does not
  change either copy of that duplicated pair. `tests/test_source_parity.py` passes
  with budgets unchanged.
- 5. `git ls-files | grep -iE "\.env$|..."` -> clean; `.env` ignored.
- 6. Regenerated; counts (311/280/73) match step 1.

Not claimed: this does not make split inference work, and does not remove the
~2,850 lines of simulation still shipped and tested (C2). What it establishes is
that no request can reach that code and no response can carry its output. The
`token_` guard test covers the two known triggers; it cannot prove a path nobody
thought of does not exist, which is why the source-level assertion exists alongside
it.

---

## Previous verdict — ROADMAP 2.5

```
Date:        2026-08-07
Change:      ROADMAP 2.5 — eviction reports what it did, instead of announcing
             that it was asked.
Spec:        specs/eviction-reports-what-it-did.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS

Reasons:
- 1. `./scripts/verify.sh` -> `PASS 15 checks`, this session. Scheduler 310 passed
  (+7, all new in `test_eviction_reporting.py`), Node 280 / 1 skipped, root E2E 73.
- 1a. Red observed first: 6 of the 7 failed against pre-change code. The seventh
  ("a fresh node is neither evicted nor reported") passed, and passed VACUOUSLY —
  see 1b.
- 1b. TWO OF MY OWN TESTS WERE WRONG, both found by reading failures rather than
  trusting the count:
  * The router logs through **structlog**, which by default renders to stdout and
    does not route into stdlib logging, so pytest's `caplog` captured NOTHING from
    it. Two tests failed outright; a third PASSED, because it asserted a string was
    *absent* and every string is absent from an empty capture. Rewritten with
    `structlog.testing.capture_logs`, and the "absence" test now also asserts the
    capture is non-empty, so its negatives mean something.
  * The consensus test set a fake engine before constructing `ZenohRouter`.
    `ZenohRouter.__init__` builds a `RaftConsensusEngine`, which assigns itself to
    `registry.consensus_engine` (`consensus.py:64`) and replaced the fake — so the
    test silently exercised the LOCAL path and observed a successful eviction.
    Reordered; it then failed correctly.
- 1c. Mutation-tested, 3 mutations, 3 reds: logging the eviction unconditionally
  again; making the consensus path return True; and making removal unable to tell a
  present node from an absent one.
- 2. Every box under "Done looks like" is ticked. Nothing under "Out of scope" was
  built: no departures endpoint, no eviction history, no alerting, and the consensus
  engine itself is untouched.
- 2a. This is the SECOND correction to 2.5's roadmap text. The first version claimed
  stale-eviction already applied correctly when nothing aged nodes out at all (fixed
  in 2.7). This pass narrowed what remained to the single surviving defect. A line
  left open across several roadmap items accumulated two false claims — worth noting
  as a pattern, not just a fact about this line.
- 3. Unchanged: the fallback RSA public key and the two benign `AliasChoices`
  env-var-name hits. No new secret or bypass; nothing about credentials changed.
- 4. No new module. `NodeRegistry` exists only in packages/scheduler, no twin.
  `tests/test_source_parity.py` passes with budgets unchanged.
- 5. `git ls-files | grep -iE "\.env$|..."` -> clean; `.env` ignored.
- 6. Regenerated; counts (310/280/73) match step 1.

Not claimed: the consensus path is exercised only against a fake engine that drops
proposals. Raft is explicitly not in v1 (single instance is the deployment), so no
test here drives a real multi-Scheduler election. What is proven is that the caller
stops asserting an outcome it cannot know — not that the consensus engine works.

---

## Previous verdict — ROADMAP 2.9

```
Date:        2026-08-06
Change:      ROADMAP 2.9 — close the two gate holes that let 2.7 reach main green
             locally and fail CI on Windows.
Spec:        specs/lint-the-tests-and-the-encodings.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS

Reasons:
- 1. `./scripts/verify.sh` -> `PASS 15 checks` (was 13; +2 for linting and
  format-checking `./tests`), this session. Scheduler 303, Node 280 / 1 skipped,
  root E2E 73. No new tests: this change is gate configuration plus the violations
  it found, so the evidence is the gate itself failing on reintroduced faults, not
  new assertions.
- 1a. Both new checks were verified by BREAKING them, not by watching them pass:
  * added `Path("README.md").read_text()` to a test file -> `ruff check ./packages`
    reports `PLW1514 ... without explicit encoding argument`, 1 error. Reverted.
  * added `import os, sys` to `tests/test_installer_paths.py` -> the new
    `ruff check (tests)` step reports 5 errors. Reverted.
  Before this change, neither of those produced any failure anywhere.
- 1b. `PLW1514` found 2 real violations, and ONE IS PRODUCTION CODE:
  `node/core/telemetry.py` opened `/proc/meminfo` with the platform default
  encoding on the Linux memory path. Fixed rather than suppressed. The other was a
  test reading a file it had just written.
- 2. Every box under "Done looks like" is ticked. Nothing under "Out of scope" was
  built: `packages/website` is still unlinted, mypy still does not see `tests/`, and
  no other preview rule was enabled.
- 2a. A NUMBER I PREVIOUSLY REPORTED WAS WRONG AND IS CORRECTED. When filing 2.9 I
  said `tests/` had 22 lint errors. It has 7. The 22 came from running ruff at its
  default line length (88) instead of this repo's (100), so most were spurious
  `E501` — the same mistake that made a stray `ruff format ./tests` reflow files
  earlier in this session. The roadmap line and the spec now say 7.
- 3. Unchanged: the fallback RSA public key and the two benign `AliasChoices`
  env-var-name hits. No new secret or bypass; nothing about credentials changed.
- 4. No new module, and no third copy of the `[tool.ruff]` block — `tests/` borrows
  the scheduler package's config via `--config` precisely to avoid one.
  `tests/test_source_parity.py` still passes (14 tests), so the two packages'
  `[tool.ruff]` blocks remain byte-identical after being edited identically.
- 5. `git ls-files | grep -iE "\.env$|..."` -> clean; `.env` ignored.
- 6. Regenerated; counts (303/280/73) match step 1.

Not claimed: this does NOT prove the Windows leg is fixed. The encoding fix in
`39f4a1d` is still unverified — its CI run has been QUEUED for 37 minutes behind a
GitHub Actions incident, and the run before it failed partly for that same reason
("Failed to resolve action download info. Service Unavailable"). What is
established is that the fault class now fails the local gate, which it did not
before. Windows itself remains verifiable only by CI.

---

## Previous verdict — ROADMAP 2.6

```
Date:        2026-08-06
Change:      ROADMAP 2.6 — the fleet-describing endpoints stop answering strangers.
Spec:        specs/authenticate-the-read-surface.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS

Reasons:
- 1. `./scripts/verify.sh` -> `PASS 13 checks`, this session. Scheduler 303 passed
  (+17, all new in `test_read_surface_auth.py`), Node 280 / 1 skipped, root E2E 73.
- 1a. Red observed first: 7 of the 17 failed against pre-change code — the five
  guarded reads, the fleet-telemetry test, and the webhook test. The five
  "works with a credential" cases passed before and after (the routes answered
  everyone, so they answered a credentialed caller too); they are the other half of
  each pair and are not red-green evidence on their own.
- 1b. Mutation: removing the guard from `GET /nodes` turns the route-inventory
  ratchet red with a message naming the reopened route. That ratchet is the part of
  this change with lasting value.
- 1c. TWO OF MY OWN TESTS WERE WRONG, both found by reading results rather than
  trusting a green count:
  * `test_no_route_is_unauthenticated_by_accident` PASSED against the unfixed code.
    FastAPI 0.141 keeps included routers as `_IncludedRouter` wrappers instead of
    flattening them into `app.routes`, so my walk found only the four docs routes
    and reported nothing unguarded. An inventory test that inventories nothing is
    worse than no test — it reads like coverage. Rewritten to traverse
    `original_router`, and given a companion,
    `test_the_route_inventory_actually_finds_routes`, which fails loudly if the walk
    ever stops finding known routes again.
  * the webhook test asserted 401 and got 404, which is how I learned
    `create_app` never mounts the webhooks router at all.
- 2. Every box under "Done looks like" is ticked. One box was CORRECTED rather than
  ticked as written — see 2a. Nothing under "Out of scope" was built: no GitHub
  HMAC verification, no per-tenant scoping, no rate limiting, and the orchestrator's
  false verification claim is untouched.
- 2a. SPEC CORRECTION, recorded rather than quietly dropped: the spec first claimed
  `POST /v1/webhooks/github` was a live unauthenticated write path. It is not — the
  router is never mounted, so it 404s. A spec that overstates a vulnerability is the
  same defect as one that understates it. The router is guarded anyway so mounting
  it later is not also a hole, and the test asserts that on the router object.
- 2b. Scope grew past the roadmap line, deliberately: it named five routes and
  missed `/nodes/telemetry` and `/nodes/{id}/telemetry`, which return live decrypted
  metrics for the whole fleet. Guarding the mesh in 2.7 while serving the same data
  to anyone over HTTP would have been half a fix.
- 3. Same two pre-existing hits as the previous pass — the fallback RSA public key
  and the two benign `AliasChoices` env-var-name hits. No new secret or bypass; this
  change only removes access. The CORS grep is unchanged.
- 4. No new module and no new duplicate. This adds a dependency to existing routes
  and one header to one TypeScript file. `tests/test_source_parity.py` unchanged.
- 5. `git ls-files | grep -iE "\.env$|..."` -> clean; `.env` ignored.
- 6. Regenerated; counts (303/280/73) match step 1.

Not claimed: THE WEBSITE CHANGE IS UNTESTED. `packages/website` has no test
harness — no runner, no test files — so the telemetry proxy now sending
`X-Network-Auth-Token` is verified only by reading it. If that env var is unset in a
deployment, the dashboard's telemetry panel will now 401 where it previously
worked, and nothing here would catch that. It is the same gap ROADMAP 4.1 records.

---

## Previous verdict — ROADMAP 2.7

```
Date:        2026-08-06
Change:      ROADMAP 2.7 (absorbing 2.5) — nothing unauthenticated may change
             registry state from the Zenoh mesh.
Spec:        specs/authenticated-mesh-ingress.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS -- then FAILED CI, fixed in a follow-up commit. See the note at the
end of this verdict.

Reasons:
- 1. `./scripts/verify.sh` -> `PASS 13 checks`, this session. Scheduler 286 passed
  (+14, all in `test_mesh_ingress_auth.py`), Node 280 passed / 1 skipped, root E2E
  73 passed (+5 in `test_mesh_protocol_parity.py`). Seven pre-existing tests were
  rewritten because the behaviour they asserted changed, not because they broke:
  three in `test_zenoh_mesh_reachability.py`, two in `test_zenoh_integration.py`,
  and one each in `test_runtime.py` and `test_zenoh_client.py`.
- 1a. Red observed first: 9 of the 14 new tests failed against pre-change code.
  The 5 that passed did so VACUOUSLY -- the old handlers did not understand the new
  envelope shape, so they rejected it for the wrong reason -- and are named here
  rather than counted as evidence. Everything below is mutation evidence instead.
- 1b. THE MUTATION RUN CHANGED THE DESIGN, which is the main thing to know about
  this pass. Three mutations of the crypto stayed green. Investigating each:
    * removing the HMAC verification changed nothing, because AES-GCM is an AEAD
      and its own tag already rejected the same envelopes. The separate SHA-256
      HMAC I had ported from the old envelope was doing NO WORK.
    * dropping `node_id` from the signature changed nothing, because an explicit
      field check caught it first.
    * dropping `purpose` from key derivation changed nothing, for a while, because
      of a *different* bug in my mutation harness (below).
  Rather than ship redundant crypto that no test could distinguish, the module was
  rewritten: the HMAC is gone, and `node_id` and `purpose` are now AES-GCM
  ASSOCIATED DATA, so the binding is enforced by the cipher. Re-mutated after:
  removing purpose from BOTH the key and the associated data -> RED; replacing the
  per-node key with a constant -> RED; and the three behavioural mutations
  (liveliness marks reachable again, deathrattle unregisters directly, sweep does
  nothing) -> RED.
- 1c. HONEST NOTE, and it matters more than the rest. Cross-topic replay is stopped
  by the KEY LOOKUP -- the Scheduler derives the key from the node owning the topic
  -- not by anything this change added. Removing BOTH the associated-data binding
  and the explicit field check still leaves that test green. The binding is defence
  in depth against a future change that reintroduced shared keys. The test's
  docstring originally claimed otherwise and was corrected rather than left
  overstating what protects what.
- 1d. HARNESS BUG, recorded because it briefly produced a false result: my first
  mutation script rewrote a source file and ran pytest within the same second, so
  `__pycache__` served bytecode compiled from the PRE-mutation source and three
  mutations reported "still green" when they were never applied. Re-run with
  `-B`, `PYTHONDONTWRITEBYTECODE=1`, a cleared `__pycache__` and a 1.1s pause, the
  purpose mutation went red. Any mutation result in this session that came back
  green was re-checked this way.
- 2. Every box under "Done looks like" is ticked. Nothing under "Out of scope" was
  built: the Zenoh transport itself is still plaintext, there is still no online
  rekey, replay inside the 30s freshness window is still possible, `packages/shared/`
  still does not exist, and the observability half of 2.5 is untouched.
- 2a. Scope grew, deliberately and recorded in the spec BEFORE the code:
    * **liveliness**, not in 2.2's framing at all, was the worst of the three holes
      -- a DELETE took the node id from a key expression the publisher chose and
      called `unregister_node`, so anyone on the mesh could evict any host;
    * **the core of 2.5**, because removing that write with no time-based
      replacement would have traded an eviction hole for dead hosts advertised
      forever. Verified that stale-eviction did NOT exist before claiming it: no
      sweep, no `last_seen` on nodes anywhere in the Scheduler. ROADMAP 2.5's own
      text asserted otherwise and is corrected.
- 2b. Design reversal, stated because I recommended the opposite when scoping this:
  I argued the shared crypto should force `packages/shared/` into existence. ROADMAP
  2.8 changed the facts -- `verify_install.sh` now really runs
  `pip install -e packages/node`, so a `pi-shared` dependency pip cannot resolve
  from a path would break a property that is now tested. Two byte-identical copies
  instead, at drift budget 0 in `tests/test_mesh_protocol_parity.py`, which also
  round-trips a real envelope sealed by one copy through the other.
- 3. Two hits, both pre-existing, and **the `TELEMETRY_SECRET_KEY` row is now GONE
  from the table in step 3** -- the published constant is removed from both
  services, `install.sh`, `install.ps1` and `docker-compose.test.yml`, pinned by a
  test that matches USE rather than mention. What remains is the fallback RSA public
  key and the two benign `AliasChoices` hits. No new secret or bypass; this change
  only removes trust.
- 4. Adds `mesh_auth.py` as a SIXTH duplicated pair, deliberately, at budget 0 --
  stricter than any existing pair. It also removes the old `derive_keys` /
  `encrypt_payload` from `telemetry.py` rather than leaving them beside it.
  `tests/test_source_parity.py` passes with budgets unchanged.
- 5. `git ls-files | grep -iE "\.env$|..."` -> clean; `.env` ignored.
- 6. Regenerated; counts (286/280/73) match step 1.

Not claimed: no test runs two machines, and none of this was exercised against a
hostile publisher on a real Zenoh network -- forgery is simulated by sealing with
the wrong key and by publishing on the wrong topic, in-process. What is proven is
that the Scheduler's handlers reject those inputs and that the node's real
serialiser round-trips through the Scheduler's real verifier. Replay of a captured
VALID envelope inside the 30s freshness window is still accepted, by design, and is
recorded as out of scope rather than tested.

CI FAILED ON THIS COMMIT (run 31119806560) DESPITE A GREEN LOCAL GATE. Recorded
here rather than quietly fixed, because "local passes, CI does not" is a failure
this repo has already been bitten by once (the 1.2 ruff-scope incident).

Two unrelated causes in that run:

1. REAL, MINE. `test_the_fleet_wide_secret_is_no_longer_used_anywhere` called
   `Path.read_text()` with no encoding. On Windows the default is cp1252, and
   `packages/node/examples/demo.py` contains a byte cp1252 cannot decode, so the
   test raised `UnicodeDecodeError` on all three Windows legs. It passed locally
   and on Linux/macOS because their default is UTF-8. The 2.8 dependency test
   survived only by accident -- it globs `packages/*/src`, and `examples/` is
   outside it.
   Fixed by passing `encoding="utf-8"` at all 11 `read_text()` sites in the tests
   this session added, plus the four pre-existing ones in `test_source_parity.py`
   that had the same latent fault.
   NOT VERIFIED ON WINDOWS. There is no Windows machine here, and an attempt to
   reproduce with `LC_ALL=C` proved nothing -- macOS keeps a UTF-8 default
   regardless. What is established: CI's traceback names `cp1252.py:23`, and that
   file genuinely fails a `cp1252` decode locally. The fix removes the dependency
   on the platform default rather than accommodating it, so it is correct by
   construction; CI is the verification.

2. NOT MINE. Several legs failed at "Set up job" with `Failed to resolve action
   download info. Error: Service Unavailable`, and two were cancelled. That is a
   GitHub Actions outage, not this change. It is named so a later reader does not
   attribute all five failures to the encoding bug.

GAPS THIS EXPOSED, filed rather than fixed in the hotfix:
- `verify.sh` lints `./packages` but NOT the root `tests/` directory, so nothing
  checks the cross-package tests at all. Enabling the full ruleset there surfaces
  22 pre-existing errors.
- Ruff's `PLW1514` (unspecified-encoding) would catch this whole class, but it
  requires preview mode. Turning preview on pulls in other unstable rules and is
  not a hotfix-sized change.
Both are ROADMAP 2.9.
```

---

## Previous verdict — ROADMAP 2.8

```
Date:        2026-08-06
Change:      ROADMAP 2.8 — the installer actually installs, and the gate can now
             tell when it stops.
Spec:        specs/installer-actually-installs.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS

Reasons:
- 1. `./scripts/verify.sh` → `PASS 13 checks` (was 12; the new real-install step is
  the thirteenth), this session. Scheduler 272 passed, Node 280 passed / 1 skipped,
  root E2E 68 passed — +11, all new: 9 in `tests/test_installer_paths.py`, 2 in
  `tests/test_declared_dependencies.py`. Also confirmed `--quick` does NOT run the
  real installer (`grep -c "install.sh (real"` → 0), which is the point of putting
  it behind the full path.
- 1a. Red observed first and from a real failure, not a constructed one. The
  starting evidence was running the actual installer against a throwaway copy of
  the tree: `./install.sh: line 274: .../Node/.env: No such file or directory`,
  `REAL EXIT CODE: 1`. Then 6 of the 9 new path tests failed against the unfixed
  scripts.
- 1b. HONEST NOTE — two of the three that passed initially passed **vacuously**,
  and I only found that by reading which assertions fired rather than trusting the
  red count:
    * the `install.ps1` case of `test_every_path_an_installer_references_exists`
      matched nothing, because that file builds paths with `Join-Path` and never
      writes `${PROJECT_ROOT}/...`. Fixed by adding a quoted-`packages/...` pattern.
    * `test_no_installer_still_points_at_the_pre_monorepo_layout` for
      `launch_host_node.sh` passed because it searched for the substring `"Node/"`
      and that file contains `"${PROJECT_ROOT}/Node"` — no trailing slash. Fixed by
      matching a path *segment*. It then failed, correctly.
- 1c. Mutation-tested, 3 mutations, 3 reds: reverting `install.sh`'s env path to
  `Node/`; reverting the launch script's `NODE_DIR`; and removing the `structlog`
  dependency again. Each failed the intended test and no others.
- 2. Every box under "Done looks like" is ticked. Nothing under "Out of scope" was
  built: `install.ps1` is still not executed for real anywhere, `docker-compose.test.yml`
  is untouched, the clone branch was repointed rather than redesigned, no installed
  node is started or registered, and the archived repo is left alone.
- 2a. Scope grew twice, both recorded in the spec rather than folded in silently:
    * `scripts/launch_host_node.sh` had the same stale path AND is what `install.sh`
      symlinks to as its fallback — so the fallback was broken in the same way as
      the thing it falls back from;
    * **three undeclared dependencies**, found by the new check on its FIRST real
      run. `node/api/auth.py:25` imports `structlog` and `clients/scheduler.py:7`
      imports `httpx`, neither declared; `scheduler/core/autonomous_orchestrator.py:7`
      imports `pydantic`, not declared. All resolve in the shared dev venv and none
      resolve for a host installing one package. 280 node tests passed while
      `import node.main` raised `ModuleNotFoundError: structlog` in a clean install.
      Declared all three, and added `tests/test_declared_dependencies.py` as the
      cheap ratchet so the next one does not need a full install to find.
- 2b. Also fixed, found by pointing shellcheck at `launch_host_node.sh` for the
  first time: `nohup $EXEC_CMD` relied on word splitting, so any path containing a
  space — an ordinary home directory like `/Users/Jane Smith` — split in the wrong
  places and the daemon never started. Now a bash array. Quoting the string, which
  is what the lint literally suggests, would have been worse.
- 3. Three hits, all pre-existing and all tabled in step 3: the two
  `TELEMETRY_SECRET_KEY` defaults and the fallback RSA public key, plus the two
  benign `AliasChoices` hits. The auth-bypass grep returns one hit, prose in a
  website page. No new secret or bypass. NOT FIXED HERE, deliberately: `install.sh`
  still writes `TELEMETRY_SECRET_KEY=<the published constant>` into every `.env` it
  generates. That is ROADMAP 2.7, and burying a protocol decision inside a path fix
  is how the original problem got made.
- 4. This change REMOVES a duplicate: `packages/node/install.ps1`, which had drifted
  into never generating `NODE_NETWORK_AUTH_TOKEN` — the credential the control API
  fails closed without (0.1) — so that copy produced a node serving nothing. One
  Windows installer now, pinned by a test. None of the six known Python pairs was
  touched; `tests/test_source_parity.py` passes with budgets unchanged.
- 5. `git ls-files | grep -iE "\.env$|..."` → clean; `.env` ignored. The installer
  writes `packages/node/.env`, which `.gitignore` already covers.
- 6. Regenerated by `scripts/generate_status.py`; its counts (272/280/68) match
  step 1 exactly.

Not claimed: `install.ps1` has NOT been executed. There is no Windows machine here,
and `verify.sh` skips the POSIX installer on Windows runners, so the Windows path is
covered only by reading its paths and its clone URL out of the file. That is
strictly weaker than what `install.sh` now gets, and the asymmetry is deliberate and
recorded in the spec rather than smoothed over. Nor does anything here prove an
installed node registers or serves — the check ends at "importable and configured".
```

---

## Previous verdict — ROADMAP 2.3 + 2.4

```
Date:        2026-08-06
Change:      ROADMAP 2.3 + 2.4 — close the open HTTP surface. CORS stops handing
             responses to every origin that asks; /v1/batch stops being anonymous.
Spec:        specs/close-the-open-http-surface.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS

Reasons:
- 1. `./scripts/verify.sh` → `PASS 12 checks`, this session. Scheduler 272 passed,
  Node 280 passed / 1 skipped, root E2E 57 passed. +18 Scheduler (9 CORS, 9 batch
  auth), +7 Node (CORS). Two existing tests were edited because the behaviour they
  asserted changed: `test_phase4_9_batch_credit.py::test_batch_processing_api_endpoints`
  now carries a JWT (it passed anonymously, which was the bug), and one of my own
  new tests was corrected — see 1b.
- 1a. Red observed first and for the right reasons: 15 of the 18 new Scheduler
  tests failed against pre-change code. The 3 that passed are guards, not evidence,
  and are named rather than counted as reds:
    * `test_the_starlette_behaviour_this_fix_assumes_is_still_true` deliberately
      pins the *old* middleware's behaviour, so it must pass before and after. It
      exists so a Starlette upgrade that changed the reflection behaviour fails the
      suite instead of quietly invalidating this spec's reasoning.
    * `test_a_valid_token_can_submit` and
      `test_the_submitting_tenant_can_read_its_own_batch` passed because there was
      no auth at all, so every request succeeded. Regression protection.
  The Node's 7 could not go red as a suite: `node.main` had no `create_app` to call.
  Covered by mutation instead, below.
- 1b. Mutation-tested, 9 mutations. 7 went red first time; the two that did not are
  recorded because one was a real weakness and one was my own bad mutation:
    * `allow_headers` back to `["*"]` → **STILL GREEN**. Genuinely weak test. It
      asserted on the `access-control-allow-headers` response header, which cannot
      distinguish the two: with an explicit list Starlette returns the list, with
      `*` it echoes whatever was requested, so both look reasonable. Rewritten to
      preflight a header that is NOT on the list and require a 400. Then red.
    * `verify_jwt` back to 422 → **STILL GREEN**, and that was the mutation's
      fault: it set `authorization = ''` inside the function, which still fails the
      Bearer check and 401s. The original behaviour was FastAPI rejecting the
      request *before* the function ran, which needs the `Header(...)` signature
      back. Re-run correctly, 3 tests failed.
  The other seven, all red: wildcard CORS restored; `*` accepted by the settings
  validator; batch ownership check removed; 403 instead of 404; batch store back to
  module scope; and the two above once corrected.
- 2. Every box under "Done looks like" is ticked. Nothing under "Out of scope" was
  built: the other unauthenticated reads are untouched, batch jobs are still not
  persisted, `/v1/batch` still fabricates its results and dispatches nothing, batch
  is still not rate-limited, and the fallback RSA key is still there.
- 2a. Scope grew past the two roadmap lines in three places, each recorded in the
  spec BEFORE the code was written, not retrofitted:
    * batch **ownership**, because authentication alone gives "any valid token
      reads every batch", which is not what 2.4 is for;
    * `_BATCH_TASKS` → `app.state`, required for that ownership check to be
      per-app, and the specific blocker 2.1 recorded against batch persistence;
    * `verify_jwt`'s 422, because 2.4's own rejection test would otherwise have had
      to assert the wrong status code.
- 2b. The roadmap's premise for 2.3 was WRONG and is corrected in the roadmap
  itself. It said the config was "rejected by browsers" — failing safe. Measured
  against the real middleware this session, Starlette reflects the caller's Origin
  instead of sending a wildcard, so it worked for every origin that asked. A
  config that fails open was sitting behind a line describing one that fails shut.
- 3. Three hits, all pre-existing and all tabled in step 3: the two
  `TELEMETRY_SECRET_KEY` defaults and the fallback RSA public key, plus the two
  benign `AliasChoices` env-var-name hits. **The CORS row is gone from that table**
  — the grep returns no `allow_origins=["*"]` in either package, only the
  replacement and its comments. The auth-bypass grep returns one hit, prose in a
  website page. No new secret, credential, or bypass; this change only removes
  access.
- 3a. Recorded, not fixed, and filed as ROADMAP 2.6: `GET /nodes`,
  `GET /nodes/{id}`, `GET /v1/models`, `GET /v1/models/{id}` and `GET /status` take
  no auth dependency. Closing CORS cut the blast radius from "any page an operator
  visits" to "anyone who can reach the host". It did not close it.
- 4. No new duplicate module. The CORS config is necessarily near-identical in
  `node/main.py` and `scheduler/main.py`, and the two settings fields and validators
  likewise — these are two FastAPI apps with separate settings classes, not one of
  the six known pairs, and there is no shared module to change. Each of the four
  sites carries a comment naming its twin. `tests/test_source_parity.py` → 14
  passed, budgets unchanged.
- 5. `git ls-files | grep -iE "\.env$|..."` → clean; `.env` ignored. Both
  `.env.example` files gained documentation, no values.
- 6. Regenerated by `scripts/generate_status.py`; its counts (272/280/57) match
  step 1 exactly.

Not claimed: nothing here was exercised against a real browser. CORS behaviour is
asserted against Starlette's middleware through the ASGI test client, which is
where the policy is decided — but "Chrome actually refuses to read this" is
inferred from the spec, not observed. The JWT path uses a locally generated RSA key
pair, not a real issued credential, because there is no way to issue one yet (3.1).
```

---

## Previous verdict — ROADMAP 2.1

```
Date:        2026-08-06
Change:      ROADMAP 2.1 — Scheduler state survives a restart. NodeRegistry and
             CreditLedger write through to a durable store and reload at startup.
Spec:        specs/scheduler-persistence.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS

Reasons:
- 1. `./scripts/verify.sh` → `PASS 12 checks`, this session. Scheduler 254 passed,
  Node 273 passed / 1 skipped, root E2E 57 passed. +27 on Scheduler, all in the new
  `packages/scheduler/tests/test_persistence.py`. Node and E2E are unchanged, which
  is expected: nothing in packages/node was touched.
- 1a. RED WAS WEAK AND IS SAID SO PLAINLY. The new tests import
  `scheduler.persistence`, a package that did not exist, so the first run failed as
  `ModuleNotFoundError` — that proves the module is new and nothing else. Every
  claim was therefore checked by mutation instead, one behaviour at a time. Ten
  mutations, ten reds:
    * register does not persist → `test_a_registered_node_is_reconstructed_after_a_restart`
    * `set_node_token` does not persist → the two token tests
    * `set_available_models` does not persist → `test_a_catalogue_refresh_survives_a_restart`
    * `delete_node` stops deleting the token row → `test_unregister_removes_the_node_and_its_token`
    * `local_unregister_node` skips the store → `test_stale_eviction_removes_the_node_durably`
    * `except ValidationError` → `except ZeroDivisionError` → `test_a_row_that_no_longer_validates_...`
    * balances stored via `f'{x:.2f}'` → `test_a_balance_round_trips_without_being_rounded`
    * `get_or_create_account` writes a zero row → `test_an_account_that_never_earned_is_not_written`
      (`assert {'never-earned-anything': 0.0} == {}`)
    * lifespan does not call `load()` → the lifespan test and the HTTP restart test
    * `create_app` builds a store of its own → `test_an_app_built_with_no_store_persists_nothing`
  The first attempt at the zero-account mutation STAYED GREEN, and that was the
  mutation's fault, not the test's: it wrote via an un-awaited `create_task`, so
  nothing ever reached the database. Re-run as a real synchronous write, it went red.
- 1b. HONEST NOTE — a coarser mutation, neutralising all three `save_*` methods at
  once, leaves 12 of the 27 passing. Each is explained, none is evidence for the
  write path: 2 exercise the storeless path deliberately; 3 assert persistence is
  off unless configured; 2 concern the constructor and the schema-version check;
  and 5 assert *absence* (the deletion and zero-account tests), which a store that
  never writes satisfies trivially. Those 5 got their real evidence from the
  targeted mutations above, which is why both mutation runs are recorded rather
  than only the flattering one.
- 2. Every box under "Done looks like" is ticked. Nothing under "Out of scope" was
  built: `_BATCH_TASKS` is still an in-memory module global, nothing credits the
  ledger, there is no Postgres backend, there are no migrations, tokens are
  plaintext at rest, and heartbeats/telemetry are still not restored.
- 2a. Scope was DELIBERATELY NARROWED against the roadmap line, which named batch
  jobs, and the reason is recorded in the spec and in ROADMAP 2.4 rather than left
  as a silent omission: `POST /v1/batch` has no auth dependency at all, so giving it
  a database converts an unauthenticated unbounded-memory growth path into an
  unauthenticated unbounded-DISK growth path. It is ordering behind 2.4, not a drop.
- 2b. The roadmap's framing was also corrected rather than inherited. 2.1 was
  written before 1.6 and treats registry loss as the headline; since 1.6 a node
  re-registers itself on a 404 heartbeat, so the registry is reconstructible and the
  LEDGER is the unrecoverable half. Both are persisted; the spec says which is which.
- 3. Five hits, all pre-existing and all tabled in step 3: the two
  `TELEMETRY_SECRET_KEY` defaults (telemetry.py:189, zenoh_router.py:278), the
  fallback RSA public key (ingress.py:16), and the two
  `allow_origins=["*"]`/`allow_credentials=True` pairs — `scheduler/main.py` moved
  from :76 to :114 because this change adds lines above it, and the table is
  corrected. Plus the two benign `AliasChoices` env-var-name hits. The auth-bypass
  grep returns one hit, prose in a website page. No new secret, credential, or
  bypass. `SCHEDULER_DATABASE_PATH` is a path, not a credential, and defaults to
  None. The new `PUT`/`POST` paths are unchanged — this change adds no route.
  NEW AND STATED, NOT HIDDEN: the database stores per-node auth tokens in
  plaintext, the same as process memory does today. It is in the spec's "Out of
  scope" and in `.env.example`, and file permissions are the only control.
- 4. No new duplicate. Searched first: no file named `*persist*`/`*sqlite*`/`*store*`
  existed under either package, and `NodeRegistry`/`CreditLedger` exist only in
  packages/scheduler — `grep -rln "CreditLedger\|NodeRegistry" packages/node/src src`
  returns nothing, so neither has a twin to keep in step. The package is named
  `scheduler/persistence/` specifically so it is NOT confused with the artifact
  store at `src/shared/storage/` (which is the sixth known duplicate pair); their
  class names do not collide either — `ArtifactStore`/`LocalDiskArtifactStore` vs
  `SchedulerStore`/`SQLiteStore`. `tests/test_source_parity.py` → 14 passed, budgets
  unchanged.
- 5. `git ls-files | grep -iE "\.env$|..."` → clean; `.env` ignored. Only
  `.env.example` is tracked and this change adds documentation to it, not a value.
- 6. Regenerated by `scripts/generate_status.py`; its counts (254/273/57) match
  step 1 exactly.

Not claimed: no test restarts a real Scheduler process. "Survives a restart" is
proven by building a second, independent NodeRegistry/CreditLedger/FastAPI app over
the same file — which is the right unit-level proof of the reload path, and is NOT
the same as a `kill -9` mid-write. Nothing here was run against a real Render
deployment, so the ephemeral-filesystem caveat in `.env.example` is read from
Render's documented behaviour, not observed. No concurrency or load testing was
done: the claim that synchronous SQLite on the event loop is cheap enough is a
judgement about expected volume, stated as such in the spec, not a measurement.
```

---

## Previous verdict — ROADMAP 1.6

```
Date:        2026-08-05
Change:      ROADMAP 1.6 — a node survives the Scheduler being unreachable, at
             boot and afterwards, instead of dying or heartbeating into a 404.
Spec:        specs/scheduler-outage-resilience.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS

Reasons:
- 1. `./scripts/verify.sh` → `PASS 12 checks`, this session. Node 273 passed /
  1 skipped, Scheduler 227 passed, root E2E 57 passed. +17 on Node: 14 new in
  `test_scheduler_outage.py`, 3 new in `test_scheduler_client.py`, and one
  existing test's docstring rewritten because its meaning changed.
- 1a. Red observed first, by stashing only the three changed source files
  (`clients/scheduler.py`, `core/configuration.py`, `runtime.py`) and running the
  new tests against pre-change code: 13 failed, including all 11 runtime-level
  outage tests. Restored with `git stash pop`; all green after.
- 1b. HONEST NOTE — three of the new tests did NOT go red on the first attempt:
  * `test_readiness_reports_degraded_while_unregistered` and
    `test_readiness_recovers_once_registration_lands` pass against old code
    because they mock the Runtime entirely and only exercise the endpoint's own
    logic. `/health/ready` already described a degraded node correctly; the defect
    was that no process could ever be in that state to ask. They are endpoint
    contract tests, not evidence for this change.
  * `test_conflict_is_detected_by_status_not_by_message` passed against old code
    as first written, because the node id never reaches the error message. That
    was a flaw in the test, not a pass. Rewritten to put "409" in the response
    BODY, which the old code interpolated into the message — and it then went red
    with the old code logging "Node already registered with Scheduler." for an
    HTTP 500. So the string match was not merely fragile, it was already wrong:
    any Scheduler 500 whose body mentioned 409 made the node believe it had
    registered when it had not.
- 2. Every box under "Done looks like" is ticked. One box was CORRECTED rather
  than ticked as written: it claimed `/infer` still works during a degraded start,
  which no test covered. Rather than tick it, a test was added for `/health` and
  `/models` and the box reworded to name what is actually exercised. Nothing under
  "Out of scope" was built — the Scheduler is still not durable, `unregister` is
  still not retried, there is still no process supervision, and heartbeats still
  use a fixed interval.
- 2a. Scope was widened past the roadmap's wording ("at boot") to cover the
  post-boot 404 case, deliberately and recorded in the spec before the code was
  written. Reason: both are the same broken assumption, the post-boot one fires
  on every Scheduler restart, and fixing only boot would ship a node that survives
  an outage in its first second and dies permanently to one at minute five.
- 3. Five hits, all pre-existing and all tabled in step 3: the two
  `TELEMETRY_SECRET_KEY` defaults, the fallback RSA public key, and the two
  `allow_origins=["*"]`/`allow_credentials=True` pairs — plus the two benign
  `AliasChoices` env-var-name hits (configuration.py drifted to :113 with this
  change). The auth-bypass grep returns one hit, prose in a website page. No new
  secret, credential, or bypass. `random.uniform` was added for backoff jitter and
  carries a `# noqa: S311` with the reason stated in the docstring; it selects a
  sleep duration and nothing that must be unpredictable.
- 4. No new duplicate, and none of the six known pairs was touched. `Runtime` and
  `SchedulerClient` exist only in packages/node with no Scheduler twin, checked
  before writing. `tests/test_source_parity.py` passes with budgets unchanged.
  `_send_request` got *less* duplicated: its two branches carried byte-identical
  error handling and were collapsed into one, which is what made attaching the
  status code a single edit rather than two.
- 5. `git ls-files | grep -iE "\.env$|..."` → clean; `.env` ignored.
- 6. Regenerated by `scripts/generate_status.py`; its counts (227/273/57) match
  step 1 exactly.

Not claimed: no test drives a real Scheduler being stopped and restarted. The
outage is simulated by raising `SchedulerError` from a mocked client, and the
retry loop is driven with `async_sleep` and `random.uniform` patched, so what is
proven is the node's decision logic — not its behaviour against a real socket
timing out. The 404-recovery path in particular assumes the Scheduler answers 404
for an unknown node, which is read from `heartbeat.py` rather than observed.
```

---

## Previous verdict — ROADMAP 1.4

```
Date:        2026-08-05
Change:      ROADMAP 1.4 — the advertised model catalogue tracks what Ollama
             actually has, instead of freezing at node startup.
Spec:        specs/truthful-model-catalogue.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS

Reasons:
- 1. `./scripts/verify.sh` → `PASS 12 checks`, this session. Node 256 passed /
  1 skipped, Scheduler 227 passed, root E2E 57 passed. That is +13 / +9 / +4 over
  the 1.3 pass; 26 tests are new (11 catalogue refresh, 9 endpoint, 4 wire
  contract, 3 Ollama cache) and 3 existing config tests were rewritten.
- 1a. Red observed first, by stashing ONLY the seven changed source files and
  running the new tests against pre-change code: 11/11 refresh tests failed,
  9/9 endpoint tests failed, and 4/4 config assertions failed. Restored with
  `git stash pop`, all green.
- 1b. The wire-contract tests went red as a *collection* error (ImportError on
  `build_model_catalogue_payload`), which proves only that the symbol is new. They
  were checked properly by mutation instead: making the builder emit full
  `ModelInfo` dicts rather than names failed 2 of the 4 on the real assertion
  (`'llama3-8b' != {'name': 'llama3-8b', 'size_gb': 4.7, ...}`). The other two
  survive that mutation by construction — one passes an empty list, one inspects
  field names — and are guards, not red-green evidence.
  A second mutation, dropping `sorted()` from `Runtime._model_names`, failed
  `test_reordering_is_not_a_change` and nothing else, which is what it should do.
- 1c. HONEST NOTE: 2 of the 3 new Ollama tests passed against pre-change code.
  `test_a_repulled_model_resolves_its_context_length_again` and
  `test_a_failed_show_is_not_cached` describe correct behaviour of a cache that
  did not exist, so the uncached code satisfied them trivially. They are
  regression protection for the cache, not evidence it was needed. Only
  `test_context_length_is_resolved_once_per_digest` was genuinely red.
- 2. Every box under "Done looks like" is ticked. Nothing under "Out of scope"
  was built: the Scheduler still trusts the pushed list without verification,
  refresh is still polling rather than event-driven, the catalogue is still not
  persisted, and `context_length` still falls back to 2048.
- 2a. Scope DID grow during the pass, and the spec was corrected before the code
  was written, not after: the spec first claimed `hosted_models` was "read by no
  production code anywhere". That came from a grep truncated by `| head`. It has
  one production read (`runtime.py:372`, a `PipelineStage` label on the split
  path). The spec now says so and states what removing it costs.
- 3. Five hits, all pre-existing and all already tabled in step 3: the two
  `TELEMETRY_SECRET_KEY` defaults, the fallback RSA public key, and
  `allow_origins=["*"]` with `allow_credentials=True` in both services. Plus the
  two benign `AliasChoices` env-var-name hits, whose line numbers had drifted to
  configuration.py:105 and config.py:54 and are corrected above; telemetry.py and
  zenoh_router.py likewise moved to :189 and :278. The auth-bypass grep returns
  one hit, prose in a website page. No new secret, credential, or bypass.
  `PUT /nodes/{id}/models` carries `Depends(verify_auth_token)`, the same
  dependency as register and unregister, and
  `test_update_requires_authentication` pins that it fails closed.
- 4. No new duplicate, and none of the six known pairs was touched — the diff is
  confined to the registry, the node/scheduler models and API, the two node
  clients, the runtime, and docs. Searched first (`grep -rn "available_models"`,
  `list_models`, `discover`) before adding anything. `ModelInfo` exists only in
  packages/node; there is no Scheduler twin to keep in step.
  `tests/test_source_parity.py` passes with its budgets unchanged.
- 5. `git ls-files | grep -iE "\.env$|..."` → clean; `.env` ignored. Only
  `.env.example` is tracked, and this change removed a line from it rather than
  adding one.
- 6. Regenerated by `scripts/generate_status.py`; its counts (227/256/57) match
  step 1 exactly.

Not claimed: nothing here was exercised against a real Ollama daemon or a real
running Scheduler. Every test drives mocks or the ASGI app in-process, so what is
proven is that the node decides correctly and that the two sides agree on the
wire — not that `ollama pull` on a live host propagates end to end. That would
need the same two-machine setup roadmap 1.5 is still waiting on.
```

---

## Previous verdict — ROADMAP 1.3

```
Date:        2026-08-04
Change:      ROADMAP 1.3 — nodes measure the metrics they heartbeat, instead of
             sending five constants. Includes corrections to the 1.2 pass.
Spec:        specs/real-heartbeat-metrics.md

  1. Test suite ......... PASS
  2. Spec match ......... PASS-WITH-GAPS
  3. Secrets & bypasses . PASS
  4. Duplication ........ PASS
  5. Nothing tracked .... PASS
  6. STATUS regenerated . PASS

VERDICT: PASS-WITH-GAPS

Reasons:
- 1. Node 243 passed 1 skipped / Scheduler 218 passed / root E2E 29 passed, this
  session. Plus CI's own gates run locally: ruff check and format --check clean over
  ./Node ./Scheduler, bandit -ll at 0 medium and 0 high, install.sh --dry-run OK,
  mypy clean on the three touched files. 18 new tests.
  Red observed first: the Node hardware tests ran against a stub reproducing the old
  constants and failed 5/7 on the intended assertions, including
  `'dict' object can't be awaited`. The ioreg parse tests were additionally checked by
  mutating the regex to a wrong key and watching two of them fail, then restoring it.
- 1a. HONEST NOTE: the five Scheduler tests in test_heartbeat_driven_scheduling.py
  passed on first run. The Scheduler was never broken -- it was being fed constants.
  Those tests are regression protection, not red-green evidence.
- 2. GAP: the NVIDIA branch remains unverified on real hardware, same as 1.2 -- no
  NVIDIA GPU on this machine, so nvidia-smi results are synthetic in tests. The Apple
  Silicon branch was checked live (10.87 GB reported vs psutil's 10.88; ioreg readable
  without sudo). Everything else in "Done looks like" is ticked with its test.
- 3. Same five pre-existing hits as the 1.2 pass, all listed in step 3. No new secret,
  credential, or bypass. `_apple_gpu_utilization` shells out to ioreg via an absolute
  path from shutil.which with a 5s timeout; bandit rates it low, below the CI gate.
- 4. No new duplicate. `detect_host_metrics` and `detect_gpu` deliberately share
  `_probe_gpu` rather than each implementing the detection ordering.
- 5. Unchanged from the 1.2 pass; only `.env.example` tracked, non-secret.
- 6. Regenerated; counts match step 1.

Also fixed here, found while verifying and outside 1.3's scope: `runtime.start()`
called `logger.warning(msg, error=...)` on a stdlib logger inside the handler for a
failed Ollama discovery. stdlib Logger raises TypeError on unknown kwargs, so a node
whose Ollama was down died on the exact path meant to keep it alive. Reproduced with
a failing test first. Swept every other `logging.getLogger` module; this was the only
instance -- the 36 similar calls elsewhere use structlog, where kwargs are valid.
```

---

## Previous verdict — ROADMAP 1.2

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

Not claimed: any behaviour on a second physical machine. This change does not
affect roadmap 1.5 either way.

CORRECTION, added 2026-08-04 after the fact: this verdict originally read "Not
claimed: CI (no remote, never run)". That was wrong, repeated from a stale line in
this file rather than checked. CI existed, had run, and this very change FAILED it
on `ruff check ./Node ./Scheduler` -- a scope wider than the `ruff check <pkg>/src`
that CLAUDE.md documented and that was run instead. Fixed in a follow-up commit; the
repo-level section below and CLAUDE.md's lint commands were corrected at the same
time. The lesson is in the file's own rules: an unverified claim is UNVERIFIED, and
one `gh run list` would have caught it.
```

**A verdict of PASS with any line marked UNVERIFIED is not a PASS.** Report it as
FAIL, or as PASS-WITH-GAPS naming every gap. The point of this file is that the
next person can trust the verdict without re-deriving it.

---

## Repo-level facts

Re-check these rather than trusting the text; all three statements that stood here
before 2026-08-04 were false by then.

- **All four repos have GitHub remotes and are pushed**, all on `main` with upstreams.
  `.gitmodules` exists and maps `Node`, `Scheduler`, and `website`.
- **CI runs on push to `main` and has passed.** Query it: `gh run list --limit 5`.
- **The `gh` CLI is installed.** CI status is queryable, so "CI unverifiable" is not
  an acceptable answer — run the command.

A green CI run proves only what the workflow actually executes. Read
`.github/workflows/ci.yml` before citing a run as evidence for anything beyond it.
