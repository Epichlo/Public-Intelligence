#!/usr/bin/env bash
#
# THE gate. This script is the only definition of "does this change pass".
#
# `.github/workflows/ci.yml` invokes this file and nothing else, so CI and local
# cannot drift apart -- there is only one list of checks left in the repo. That
# matters because they *did* drift: CLAUDE.md documented `ruff check <pkg>/src`
# while CI ran `ruff check ./Node ./Scheduler`, the narrower command was run
# locally, and a lint failure reached main.
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
# Locally the three suites need their own venvs (the root E2E suite only imports
# both packages under Node/.venv). In CI both packages are pip-installed into the
# one system interpreter and no venv exists.
if [ -x "$REPO_ROOT/Node/.venv/bin/python" ]; then
    NODE_PY="$REPO_ROOT/Node/.venv/bin/python"
    SCHED_PY="$REPO_ROOT/Scheduler/.venv/bin/python"
    MODE="local venvs"
elif [ -x "$REPO_ROOT/Node/.venv/Scripts/python.exe" ]; then
    NODE_PY="$REPO_ROOT/Node/.venv/Scripts/python.exe"
    SCHED_PY="$REPO_ROOT/Scheduler/.venv/Scripts/python.exe"
    MODE="local venvs (windows)"
else
    NODE_PY="$(command -v python3 || command -v python)"
    SCHED_PY="$NODE_PY"
    MODE="system interpreter"
fi

# --- result tracking -------------------------------------------------------
# Every step runs even after one fails, mirroring CI's `fail-fast: false`. One
# run should show you everything that is wrong, not just the first thing.
FAILED=()
PASSED=()
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

printf '\033[1mverify\033[0m  mode=%s  python=%s\n' "$MODE" "$("$NODE_PY" -V 2>&1)"

# --- lint ------------------------------------------------------------------
# Whole submodules, tests included. Both packages carry a byte-identical
# [tool.ruff] block; tests/test_source_parity.py fails if they diverge.
run_step "ruff check"        "$NODE_PY" -m ruff check ./Node ./Scheduler
run_step "ruff format"       "$NODE_PY" -m ruff format --check ./Node ./Scheduler

# The gate lints its own scripts. CI already installs shellcheck on Linux but
# never ran it; a `[ "$x" != "PATTERN"* ]` comparison that silently never matched
# sat in this very file until shellcheck was pointed at it.
if command -v shellcheck >/dev/null 2>&1; then
    run_step "shellcheck" shellcheck scripts/verify.sh scripts/install-hooks.sh install.sh
else
    printf '\n\033[33m── shellcheck (skipped: not installed)\033[0m\n'
fi

# --- types -----------------------------------------------------------------
# Both packages set strict = true. This was configured and never run, which is
# how a `logger.warning(msg, error=...)` TypeError shipped on a startup path.
run_step "mypy (node)"       "$NODE_PY"  -m mypy Node/src
run_step "mypy (scheduler)"  "$SCHED_PY" -m mypy Scheduler/src

# mypy is platform-aware, so a POSIX-only call is only an error when it checks as
# Windows. Running this locally rather than discovering it on a Windows runner:
# the first Windows type-check found `os.getloadavg()` behind a bare `except`
# whose fallback published a RANDOM cpu figure into the telemetry mesh, and an
# `os.getgid()` call. There is a Windows installer, so these were reachable.
run_step "mypy (node, win32)"      "$NODE_PY"  -m mypy Node/src --platform win32
run_step "mypy (scheduler, win32)" "$SCHED_PY" -m mypy Scheduler/src --platform win32

# --- tests -----------------------------------------------------------------
# Branch coverage, reported not gated: the point is seeing which branches a
# change left unexecuted, which is how an untested regex and an untested except
# branch both slipped through.
#
# --cov takes a PATH, not the module name. `--cov=node` silently measures nothing
# (0%) when pytest is invoked from the repo root rather than from Node/, because
# the module resolves before the source filter is applied.
run_step "pytest (node)" "$NODE_PY" -m pytest Node/tests -q \
    --cov=Node/src/node --cov-branch --cov-report=term-missing:skip-covered --cov-fail-under=0
run_step "pytest (scheduler)" "$SCHED_PY" -m pytest Scheduler/tests -q \
    --cov=Scheduler/src/scheduler --cov-branch --cov-report=term-missing:skip-covered \
    --cov-fail-under=0

if [ "$QUICK" -eq 0 ]; then
    # Root E2E is the only place both packages import, so it is the only place the
    # Node/Scheduler wire contract and the duplicated-module pairs can be checked.
    run_step "pytest (root e2e)" "$NODE_PY" -m pytest tests -q
fi

# --- security --------------------------------------------------------------
# -ll gates on MEDIUM and above only. This codebase legitimately shells out
# (nvidia-smi, ioreg, docker, git) and wraps optional hardware probes in broad
# try/except, which bandit flags at LOW as B404/B603/B607/B110.
run_step "bandit" "$NODE_PY" -m bandit -r ./Node/src ./Scheduler/src -x tests -ll -q

# --- installer -------------------------------------------------------------
# `case` rather than `[ "$x" != "MINGW64_NT"* ]`: test(1) compares literally and
# never globs, so that form silently ran the POSIX installer on Windows runners.
IS_WINDOWS=0
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;; esac

if [ "$QUICK" -eq 0 ] && [ "$IS_WINDOWS" -eq 0 ] && [ -f ./install.sh ]; then
    run_step "install.sh --dry-run" bash ./install.sh --dry-run
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
    exit 0
fi
printf '\033[31mFAIL\033[0m  %d of %d checks failed:\n' "${#FAILED[@]}" "$(( ${#FAILED[@]} + ${#PASSED[@]} ))"
for f in "${FAILED[@]}"; do printf '        - %s\n' "$f"; done
exit 1
