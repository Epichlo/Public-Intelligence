# Spec: The installer actually installs (ROADMAP 2.8)

## What this does

Nobody can install a node. `install.sh` exits 1 on its first write, and the
Windows path installs the wrong repository. This makes both work, and — the part
that matters more — makes the gate able to *notice* when they stop working, which
it currently cannot.

## What actually breaks today

Measured this session by running the real installer against a throwaway copy of
the working tree, not by reading it:

```
[INFO] Configuring P2P WAN Node Environment...
./install.sh: line 274: .../installtest/Node/.env: No such file or directory
REAL EXIT CODE: 1
```

Four separate breakages, all descendants of the 2026-08-04 monorepo migration that
moved `Node/` to `packages/node/`:

1. **`install.sh` cannot write anything.** It targets `Node/.env` (:237),
   `Node/.venv` (:324), `pip install -e $PROJECT_ROOT/Node` (:341), and
   `Node/.venv/bin/public-intelligence-node` (:353). None of those paths exist. It
   dies at the first one. macOS and Linux hosts get nothing.

2. **`scripts/launch_host_node.sh` points at `Node/` too** (:9, :12, :13). So even
   a repaired install could not be started — and `install.sh` symlinks
   `public-intelligence-node` to this script as its fallback, meaning the fallback
   is broken in the same way as the thing it falls back from.

3. **The root `install.ps1` installs the wrong repository.** `$NodeDir = $ScriptDir`
   is the repo root, which has no `pyproject.toml`, so it takes the clone branch
   and fetches `Epichlo/Node-PublicIntelligence` — the **archived pre-monorepo
   repo**, last pushed 2026-08-04. It then installs that. Windows hosts do not get
   a failure; they get a node frozen before 1.4, 1.6, 2.1, 2.3 and 2.4. Silently
   installing stale software is worse than failing.

4. **`packages/node/install.ps1` is a stale duplicate** that never generates
   `NODE_NETWORK_AUTH_TOKEN`. The node's control API fails closed without it
   (ROADMAP 0.1), so that copy produces a node that serves nothing. Two Windows
   installers, and the one sitting next to the package is the broken one.

5. **Two packages import modules they do not declare.** Found by the new real-run
   check on its first execution, which is the whole argument for building it.
   `node/api/auth.py:25` imports `structlog` and `node/clients/scheduler.py:7`
   imports `httpx`, neither declared in `packages/node/pyproject.toml`;
   `scheduler/core/autonomous_orchestrator.py:7` imports `pydantic`, not declared
   in the scheduler's. All three resolve in development because the root `.venv`
   installs both packages together — `structlog` arrives via the scheduler,
   `httpx` via `ollama`, `pydantic` via `pydantic-settings`. **A host installing
   only the node got `ModuleNotFoundError: No module named 'structlog'` on
   `import node.main`**, with all 280 node tests passing. This was added to the
   scope after the fact and is recorded here rather than folded in silently.

### Why the gate could not see any of this

`scripts/verify.sh` runs `install.sh --dry-run`. Every step that touches the
filesystem returns early in dry-run mode *after printing what it would do*:

```bash
if [[ "$DRY_RUN" == "true" ]]; then
    log_dry_run "Would run: ${VENV_DIR}/bin/pip install -e ${PROJECT_ROOT}/Node"
    return 0
fi
```

So the check exercises the printing, never the doing. CI has been green over an
installer that cannot install on every commit since the migration — including all
four commits made in this session. **This is the same failure the repo has already
been bitten by twice** (CI running a different check list than CLAUDE.md; docs
asserting facts nobody re-measured): a green signal over an unexercised path.

## Design decisions, and why

**The real-run check is the deliverable, not the path fix.** Correcting four paths
takes minutes and will rot again at the next layout change. A gate step that
actually installs is what makes the *class* of bug visible. If only one of the two
halves could ship, it should be this one.

**It runs against a copy of the working tree, not `git archive HEAD`.** An archive
of committed files is closer to what a host clones, but it would test code that is
not the code being verified — a pre-push gate must fail on the tree in front of it.
The copy excludes `.venv`, `.git`, `node_modules` and `__pycache__` so the
installer builds its environment from nothing, the way a host's would.

**It asserts the node imports, not merely that files appeared.** `pip install -e`
can succeed and still leave a package that cannot be imported. The check runs the
installed interpreter and imports `node`, which is the weakest claim that is
actually worth making.

**It sits behind the non-`--quick` path.** It performs a real `pip install`, so it
costs wall-clock time on every CI leg. `--quick` is the tight local loop and
already skips the root E2E suite and the installer; this belongs with those.

**A separate static path check runs everywhere, including Windows.** `verify.sh`
skips `install.sh` on Windows runners, so a real-run check can never cover
`install.ps1`. A test that reads every repo-relative path out of all three scripts
and asserts it exists is cheap, platform-independent, and catches exactly the
defect that occurred here. It is weaker than running the thing — it would not catch
a functional break — and both exist for that reason.

**`packages/node/install.ps1` is deleted rather than repaired.** Keeping two
Windows installers is what let the more-discoverable one drift into missing the
0.1 credential. One installer per platform, at the repo root, next to `install.sh`.

**The Windows installer clones the monorepo when run outside a checkout.** Not the
archived Node repo. The archived repo is left alone — it is still referenced by
`pre-monorepo-2026-08-04` tags and deleting it is not this change's business.

**The venv stays per-package at `packages/node/.venv`.** Not the root `.venv`,
which CLAUDE.md defines as the *development* environment holding both packages plus
dev tooling. A host installing a node should not have their node's runtime
entangled with a developer setup, and a developer running `install.sh` should not
have their working venv rewritten.

## Done looks like

- [x] `bash install.sh` run against a clean copy of the tree exits **0**, and
      creates `packages/node/.env`, `packages/node/.venv`, and a
      `public-intelligence-node` link. Covered by the new gate step.
- [x] The interpreter that installer produced can `import node`. Same step.
- [x] `packages/node/.env` contains a generated `NODE_NETWORK_AUTH_TOKEN` — a node
      without one serves nothing (0.1). Same step.
- [x] `./scripts/verify.sh` runs that check; `./scripts/verify.sh --quick` skips it.
- [x] Every repo-relative path referenced by `install.sh`, `install.ps1` and
      `scripts/launch_host_node.sh` exists in the repo. Covered by a test in
      `tests/` that runs on all platforms, Windows included.
- [x] That test fails if a path is reverted to `Node/` — verified by mutation, not
      assumed.
- [x] `install.ps1` no longer *fetches* `Node-PublicIntelligence`. Covered by the
      same test. (This box originally said "no longer references". It was corrected
      rather than ticked as written: the file now explains this history in a
      comment that names the old repo, and a test forbidding the bare name would
      delete the explanation of why the code looks the way it does. The test matches
      a `github.com/Epichlo/...` URL instead — fetching it is the defect.)
- [x] `packages/node/install.ps1` is gone.
- [x] Every third-party module either package imports is declared in its own
      `dependencies`. Covered by a test in `tests/`, so the cheap ratchet catches
      the next one without paying for a full install.
- [x] `./scripts/verify.sh` passes.

## Out of scope

- **Running `install.ps1` for real.** No Windows machine here, and CI's Windows
  legs would need the installer not to clone, launch a daemon, or install Python
  via winget. The static path check is what covers it; that is explicitly weaker
  than what `install.sh` gets, and the asymmetry is stated rather than papered over.
- **`docker-compose.test.yml`**, which ROADMAP 1.5 records as never having run and
  as carrying a wrong `NODE_ID` env var. Same family of defect — an unexercised
  entry point — but it belongs to 1.5.
- **Whether the installer should clone at all.** The Windows script's
  clone-if-not-in-a-checkout branch is repointed, not redesigned.
- **Testing that an installed node actually registers and serves.** The check
  proves the install produces an importable, configured node. It does not start it
  or reach a Scheduler; that is 1.5's two-machine test.
- **The archived `Node-PublicIntelligence` repo.** Not deleted, not archived, not
  touched. It is still what the `pre-monorepo-2026-08-04` tag refers to.

## Verification

```
./scripts/verify.sh
./scripts/verify.sh --quick        # must NOT run the real installer step
.venv/bin/python -m pytest tests/test_installer_paths.py -q
bash scripts/verify_install.sh     # the real-run check, standalone
grep -rn "Node/" install.sh install.ps1 scripts/launch_host_node.sh   # expect no hits
```

## Notes / open questions

- Duplicate-module check: this touches shell and PowerShell, none of the six
  duplicated Python pairs. It *removes* a duplicate (`packages/node/install.ps1`).
- The real-run step's cost is a full `pip install -e packages/node` per CI leg,
  across a 3-OS × 3-Python matrix. Measured locally before committing; if it proves
  disproportionate the fallback is `--no-deps` plus a separate dependency-resolution
  check, which is weaker and would be recorded as such rather than done quietly.
- Open: `install.sh` writes `TELEMETRY_SECRET_KEY=<the published constant>` into
  every `.env` it generates. Left exactly as-is here, because changing it is
  ROADMAP 2.7 and doing it inside an installer fix would bury a protocol decision
  in a path change.
