#!/usr/bin/env bash
#
# THE gate. This script is the only definition of "does this change pass".
#
# `.github/workflows/ci.yml` invokes this file and nothing else, so CI and local
# cannot drift apart -- there is only one list of checks left in the repo. That
# matters because they *did* drift: CLAUDE.md documented `ruff check <pkg>/src`
# while CI ran the wider `ruff check ./Node ./Scheduler` (pre-monorepo paths),
# the narrower command was run locally, and a lint failure reached main.
#
# Usage:
#   ./scripts/verify.sh              # everything
#   ./scripts/verify.sh --quick      # skip the root E2E suite and the installer
#
# It writes zones/verified/latest.verified.json recording what ran and against which
# tree. A "this is done" claim is checkable against that file, and
# .claude/hooks/require-proof-stop.py checks it automatically: if the bundle's commit
# or fingerprint is not the tree in front of you, the claim is about code that no
# longer exists. This replaces the old .verify-receipt.json -- one artifact, not two,
# because a stale second copy is precisely what a later session reads as current.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

# --- interpreter selection -------------------------------------------------
# ONE interpreter for everything. Before the monorepo migration this needed three
# venvs and the root E2E suite only ran under Node/.venv, because that was the sole
# environment where both packages imported. Now both are installed editable into
# one root .venv, and CI installs them into its system interpreter the same way.
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PY="$REPO_ROOT/.venv/bin/python"
    MODE="root .venv"
elif [ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]; then
    PY="$REPO_ROOT/.venv/Scripts/python.exe"
    MODE="root .venv (windows)"
else
    PY="$(command -v python3 || command -v python)"
    MODE="system interpreter"
fi

# --- result tracking -------------------------------------------------------
# Every step runs even after one fails, mirroring CI's `fail-fast: false`. One
# run should show you everything that is wrong, not just the first thing.
FAILED=()
PASSED=()
# Skipped steps are tracked and REPORTED, not merely printed and forgotten. A gate
# that quietly omits checks while printing PASS is the exact failure this file has
# now hit three times (tests/ unlinted, tests/ untyped, the website unchecked). The
# summary names what did not run, and the receipt records it, so "it passed" and
# "it passed everything" stay distinguishable.
SKIPPED=()
declare -a RECEIPT_STEPS

run_step() {
    local name="$1"; shift
    printf '\n\033[1m── %s\033[0m\n' "$name"
    if "$@"; then
        PASSED+=("$name")
        RECEIPT_STEPS+=("{\"step\":\"$name\",\"result\":\"pass\"}")
        return 0
    fi
    FAILED+=("$name")
    RECEIPT_STEPS+=("{\"step\":\"$name\",\"result\":\"FAIL\"}")
    return 0
}

printf '\033[1mverify\033[0m  mode=%s  python=%s\n' "$MODE" "$("$PY" -V 2>&1)"

# --- lint ------------------------------------------------------------------
# Both packages including their tests. Each carries a byte-identical
# [tool.ruff] block; tests/test_source_parity.py fails if they diverge.
run_step "ruff check"        "$PY" -m ruff check ./packages
run_step "ruff format"       "$PY" -m ruff format --check ./packages

# The root tests/ directory was linted by NOTHING until ROADMAP 2.9. This file is
# "the only definition of does this pass", and a whole directory of cross-package
# tests -- the wire contract, the parity ratchets, the installer checks -- sat
# outside that definition while appearing to be inside it.
#
# It borrows the scheduler package's config rather than adding a third copy of the
# [tool.ruff] block at the repo root; tests/test_source_parity.py exists to stop
# exactly that kind of duplication drifting. It is also why a bare
# `ruff format ./tests` reformats at ruff's default 88 columns instead of this
# repo's 100 -- always pass --config.
RUFF_CFG="packages/scheduler/pyproject.toml"
run_step "ruff check (tests)"  "$PY" -m ruff check ./tests --config "$RUFF_CFG"
run_step "ruff format (tests)" "$PY" -m ruff format --check ./tests --config "$RUFF_CFG"

# scripts/ was the THIRD directory sitting outside the gate while appearing to be
# inside it -- after packages/tests (2.9) and the website (C6). It contains this
# file. Pointing ruff at it found 3 errors and 4 unformatted files, and one of the
# errors was `Path.read_text()` with no encoding *in generate_status.py*: the same
# platform-default bug 2.9 added PLW1514 to catch, surviving in the script that
# produces STATUS.md, because the rule was only ever aimed at packages/ and tests/.
#
# The pattern is now three for three: every time a directory has been added to this
# file, the defect found was the check's ABSENCE, not a check's failure.
run_step "ruff check (scripts)"  "$PY" -m ruff check ./scripts --config "$RUFF_CFG"
run_step "ruff format (scripts)" "$PY" -m ruff format --check ./scripts --config "$RUFF_CFG"

# .claude/hooks/ decides whether a task is allowed to COMPLETE. It is the last code
# in this repo that should be exempt from the gate, and it was very nearly exempt by
# accident: the ratchet in tests/test_source_parity.py skipped any directory whose
# name starts with a dot, so these files would have sat outside "the only definition
# of does this pass" while appearing to be inside it. That is the same silent-partial
# failure as tests/ (2.9), the website (C6) and scripts/ (C7) -- four for four now.
# The ratchet was widened to walk dotted directories in the same change.
run_step "ruff check (hooks)"  "$PY" -m ruff check ./.claude --config "$RUFF_CFG"
run_step "ruff format (hooks)" "$PY" -m ruff format --check ./.claude --config "$RUFF_CFG"

# experimental/ is LINTED but its tests are NOT RUN. ROADMAP C2 asked to exclude it
# from the gate; excluding it entirely would let ~2,000 lines rot, and linting is
# free. What C2 actually wanted was for the reported test count to mean something --
# so the tests stay out and the shipping number stops being inflated by suites for
# features this product has decided not to have.
run_step "ruff check (experimental)"  "$PY" -m ruff check ./experimental --config "$RUFF_CFG"
run_step "ruff format (experimental)" "$PY" -m ruff format --check ./experimental --config "$RUFF_CFG"

# COLLECT the quarantined tests without RUNNING them. This is the difference
# between "not in the gate" and "dead".
#
# When C2 first moved these, their imports still pointed at `node.core.transport`
# and friends -- modules that had just been moved out from under them. All 41 tests
# were unrunnable, and linting could not tell, because a stale import is valid
# syntax. "Kept for v2" had quietly become "deleted with extra steps".
#
# --collect-only imports every module and reports nothing as passed, so the
# shipping test count stays honest (C2's actual goal) while an unimportable
# quarantined test still fails the gate.
run_step "pytest --collect-only (experimental)" \
    "$PY" -m pytest ./experimental --collect-only -q

# The gate lints its own scripts. CI already installs shellcheck on Linux but
# never ran it; a `[ "$x" != "PATTERN"* ]` comparison that silently never matched
# sat in this very file until shellcheck was pointed at it.
if command -v shellcheck >/dev/null 2>&1; then
    run_step "shellcheck" shellcheck scripts/verify.sh scripts/install-hooks.sh \
        scripts/verify_install.sh scripts/launch_host_node.sh install.sh
else
    printf '\n\033[33m── shellcheck (skipped: not installed)\033[0m\n'
    SKIPPED+=("shellcheck")
fi

# --- types -----------------------------------------------------------------
# Both packages set strict = true. This was configured and never run, which is
# how a `logger.warning(msg, error=...)` TypeError shipped on a startup path.
run_step "mypy (shared)"     "$PY" -m mypy packages/shared/src
run_step "mypy (node)"       "$PY"  -m mypy packages/node/src
run_step "mypy (scheduler)"  "$PY" -m mypy packages/scheduler/src

# mypy is platform-aware, so a POSIX-only call is only an error when it checks as
# Windows. Running this locally rather than discovering it on a Windows runner:
# the first Windows type-check found `os.getloadavg()` behind a bare `except`
# whose fallback published a RANDOM cpu figure into the telemetry mesh, and an
# `os.getgid()` call. There is a Windows installer, so these were reachable.
run_step "mypy (node, win32)"      "$PY"  -m mypy packages/node/src --platform win32
run_step "mypy (scheduler, win32)" "$PY" -m mypy packages/scheduler/src --platform win32

# The root tests/ directory. 2.9 closed the lint half of this gap and named the type
# half as a known gap; ROADMAP C7 closes it.
#
# This only checks anything because both packages now ship a PEP 561 `py.typed`
# marker. Without it mypy answered `module is installed, but missing library stubs`
# for all 26 imports tests/ makes into node and scheduler -- so a type-check step
# here would have verified the test files' own local variables and NOTHING about
# the contract they assert. Adding the step without the marker would have been a
# check that reports success for doing nothing, which is worse than no check.
run_step "mypy (tests)" "$PY" -m mypy tests

# --- tests -----------------------------------------------------------------
# Branch coverage, reported not gated: the point is seeing which branches a
# change left unexecuted, which is how an untested regex and an untested except
# branch both slipped through.
#
# --cov takes a PATH, not the module name. `--cov=node` silently measures nothing
# (0%) when pytest is invoked from the repo root rather than the package dir, because
# the module resolves before the source filter is applied.
run_step "pytest (node)" "$PY" -m pytest packages/node/tests -q \
    --cov=packages/node/src/node --cov-branch --cov-report=term-missing:skip-covered --cov-fail-under=0
run_step "pytest (scheduler)" "$PY" -m pytest packages/scheduler/tests -q \
    --cov=packages/scheduler/src/scheduler --cov-branch --cov-report=term-missing:skip-covered \
    --cov-fail-under=0

if [ "$QUICK" -eq 0 ]; then
    # Cross-package tests: the node/scheduler wire contract and the duplicate-module
    # ratchets. Kept as a separate suite because they assert relationships BETWEEN
    # the packages rather than the behaviour of either one.
    run_step "pytest (root e2e)" "$PY" -m pytest tests -q
fi

# --- website ---------------------------------------------------------------
# 4,270 lines that were checked by NOTHING: package.json had a `lint` script this
# file never invoked, and no `test` script at all. Every proxy route -- including
# the credential forwarding added in 2.6 -- was verified only by reading it.
#
# Skipped loudly when node_modules is absent, same as shellcheck above. A Python
# contributor should not need a Node toolchain to run the gate; CI installs it and
# therefore always runs these. The cost is stated rather than hidden: on a machine
# without the dependencies, a local PASS is weaker than a CI PASS, and the line
# below says which checks did not run.
WEBSITE_DIR="$REPO_ROOT/packages/website"
if [ -d "$WEBSITE_DIR/node_modules" ]; then
    run_step "website lint" npm --prefix "$WEBSITE_DIR" run --silent lint
    # `tsc` was ruled OUT of the gate by specs/the-gate-sees-the-website.md, on the
    # argument that "eslint with the TypeScript plugin catches the errors that were
    # actually present". That argument was true when it was written and is FALSE:
    # the first time tsc was pointed at this tree it found 4 errors eslint had
    # passed clean, in a test file the gate was already running.
    #
    # eslint checks lint rules; it does not type-check. Those are different jobs and
    # the spec conflated them. The cost is one more toolchain step, which is already
    # paid for by the two above it.
    run_step "website types" npm --prefix "$WEBSITE_DIR" run --silent typecheck
    run_step "website tests" npm --prefix "$WEBSITE_DIR" run --silent test
else
    printf '\n\033[33m── website lint + tests (skipped: packages/website/node_modules absent)\033[0m\n'
    printf '   run: npm ci --prefix packages/website\n'
    SKIPPED+=("website lint + tests")
fi

# --- security --------------------------------------------------------------
# -ll gates on MEDIUM and above only. This codebase legitimately shells out
# (nvidia-smi, ioreg, docker, git) and wraps optional hardware probes in broad
# try/except, which bandit flags at LOW as B404/B603/B607/B110.
run_step "bandit" "$PY" -m bandit -r ./packages/node/src ./packages/scheduler/src -x tests -ll -q

# --- installer -------------------------------------------------------------
# `case` rather than `[ "$x" != "MINGW64_NT"* ]`: test(1) compares literally and
# never globs, so that form silently ran the POSIX installer on Windows runners.
IS_WINDOWS=0
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;; esac

if [ "$QUICK" -eq 0 ] && [ "$IS_WINDOWS" -eq 0 ] && [ -f ./install.sh ]; then
    run_step "install.sh --dry-run" bash ./install.sh --dry-run

    # The dry-run above proves almost nothing on its own, and for two days it
    # proved nothing at all: EVERY step of install.sh returns early in dry-run
    # mode after printing what it *would* do, so the paths it prints were never
    # exercised. They still said `Node/`, which the monorepo migration renamed to
    # `packages/node/` -- the installer exited 1 on its first write, and CI was
    # green over it the whole time.
    #
    # This step runs the installer for real against a throwaway copy of the tree
    # and checks the result imports. Its first real run found a second bug the
    # dry-run could never have caught: the node package did not declare structlog.
    # See specs/installer-actually-installs.md.
    run_step "install.sh (real, throwaway copy)" bash ./scripts/verify_install.sh
fi

# --- evidence bundle -------------------------------------------------------
# Written here and NOWHERE ELSE, which is the whole basis of the split described in
# zones/README.md: producing this file requires having run the checks above, so it is
# a by-product of measuring rather than a statement anyone can compose. An agent
# cannot forge it -- .claude/hooks/block-protected-paths.py denies the write
# (including via shell redirection) and .claude/settings.json carries a `deny` rule,
# which no later scope or permission mode can override.
#
# `state_fingerprint` is what makes the evidence EXPIRE, and it is the fix for a real
# hole in the blueprint this came from: that Stop hook took the newest bundle by mtime
# and trusted it, so running the gate, editing one line, and stopping left a PASS
# standing about code that no longer existed. .claude/hooks/require-proof-stop.py
# recomputes the fingerprint instead of believing this file.
#
# zones/ is gitignored, so writing this does not perturb the fingerprint it records.
SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
DIRTY="false"
[ -n "$(git status --porcelain 2>/dev/null)" ] && DIRTY="true"
FINGERPRINT="$("$PY" "$REPO_ROOT/scripts/state_fingerprint.py" 2>/dev/null || echo unknown)"
VERDICT="pass"
[ ${#FAILED[@]} -gt 0 ] && VERDICT="FAIL"

mkdir -p "$REPO_ROOT/zones/verified"
{
    printf '{\n'
    printf '  "verdict": "%s",\n' "$VERDICT"
    printf '  "commit": "%s",\n' "$SHA"
    printf '  "state_fingerprint": "%s",\n' "$FINGERPRINT"
    printf '  "working_tree_dirty": %s,\n' "$DIRTY"
    printf '  "generated_at": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '  "quick_mode": %s,\n' "$([ "$QUICK" -eq 1 ] && echo true || echo false)"
    printf '  "skipped": ['
    skip_first=1
    for s in ${SKIPPED[@]+"${SKIPPED[@]}"}; do
        [ $skip_first -eq 0 ] && printf ', '
        printf '"%s"' "$s"
        skip_first=0
    done
    printf '],\n'
    printf '  "steps": [\n'
    local_first=1
    for s in "${RECEIPT_STEPS[@]}"; do
        [ $local_first -eq 0 ] && printf ',\n'
        printf '    %s' "$s"
        local_first=0
    done
    printf '\n  ]\n}\n'
} > "$REPO_ROOT/zones/verified/latest.verified.json"

# --- summary ---------------------------------------------------------------
printf '\n\033[1m────────────────────────────────────────\033[0m\n'
if [ ${#FAILED[@]} -eq 0 ]; then
    printf '\033[32mPASS\033[0m  %d checks  commit %s%s\n' \
        "${#PASSED[@]}" "${SHA:0:8}" "$([ "$DIRTY" = "true" ] && echo ' (dirty tree)')"
    [ "$DIRTY" = "true" ] && printf '      receipt covers HEAD, but the tree has uncommitted changes\n'
    if [ ${#SKIPPED[@]} -gt 0 ]; then
        printf '\033[33m      %d check(s) DID NOT RUN:\033[0m %s\n' \
            "${#SKIPPED[@]}" "$(IFS=', '; echo "${SKIPPED[*]}")"
        printf '      this PASS is weaker than a CI PASS, which runs all of them\n'
    fi
    exit 0
fi
printf '\033[31mFAIL\033[0m  %d of %d checks failed:\n' "${#FAILED[@]}" "$(( ${#FAILED[@]} + ${#PASSED[@]} ))"
for f in "${FAILED[@]}"; do printf '        - %s\n' "$f"; done
exit 1
