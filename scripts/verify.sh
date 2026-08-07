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
# On success it writes .verify-receipt.json recording the commit that was
# verified. A "this is done" claim is checkable against that file: if the receipt's
# SHA is not HEAD, the claim is about code that no longer exists.

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

# --- receipt ---------------------------------------------------------------
SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
DIRTY="false"
[ -n "$(git status --porcelain 2>/dev/null)" ] && DIRTY="true"
VERDICT="pass"
[ ${#FAILED[@]} -gt 0 ] && VERDICT="FAIL"

{
    printf '{\n'
    printf '  "verdict": "%s",\n' "$VERDICT"
    printf '  "commit": "%s",\n' "$SHA"
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
} > "$REPO_ROOT/.verify-receipt.json"

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
