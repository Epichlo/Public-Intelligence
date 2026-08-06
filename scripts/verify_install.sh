#!/usr/bin/env bash
#
# Run install.sh FOR REAL against a throwaway copy of the working tree, and check
# it produced a node that actually works.
#
# This exists because `verify.sh` ran only `install.sh --dry-run`, and every step
# of that script returns early in dry-run mode *after printing what it would do*:
#
#     if [[ "$DRY_RUN" == "true" ]]; then
#         log_dry_run "Would run: ${VENV_DIR}/bin/pip install -e ..."
#         return 0
#     fi
#
# So the gate exercised the printing and never the doing. CI stayed green for two
# days over an installer that exited 1 on its first write, because the monorepo
# migration renamed `Node/` to `packages/node/` and four scripts were left behind.
# See specs/installer-actually-installs.md.
#
# Deliberately a real `pip install`, not `--no-deps` or a mock: the failure mode
# being guarded against is "the installer produces something that does not work",
# and every cheaper version of this check would have passed against the broken
# installer too.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

WORK="$(mktemp -d 2>/dev/null || mktemp -d -t pi-install)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

fail() { printf '\033[31mFAIL\033[0m  %s\n' "$1"; exit 1; }

printf 'copying the working tree to %s\n' "$WORK"

# The WORKING TREE, not `git archive HEAD`: a pre-push gate must fail on the code
# in front of it, not on what happens to be committed. Excluding .venv/.git/caches
# so the installer builds its environment from nothing, the way a host's would.
if command -v rsync >/dev/null 2>&1; then
    rsync -a \
        --exclude '.venv' --exclude '.git' --exclude 'node_modules' \
        --exclude '__pycache__' --exclude '*.pyc' \
        "$REPO_ROOT"/ "$WORK"/ || fail "could not copy the tree"
else
    tar -C "$REPO_ROOT" \
        --exclude '.venv' --exclude '.git' --exclude 'node_modules' \
        --exclude '__pycache__' --exclude '*.pyc' \
        -cf - . | tar -C "$WORK" -xf - || fail "could not copy the tree"
fi

# A stale .env or .venv copied in would let a broken installer look successful.
rm -rf "$WORK/packages/node/.env" "$WORK/packages/node/.venv" "$WORK/public-intelligence-node"

printf 'running install.sh for real\n'
if ! (cd "$WORK" && bash ./install.sh > "$WORK/install.log" 2>&1); then
    printf '\n--- installer output ---\n'
    tail -30 "$WORK/install.log"
    fail "install.sh exited non-zero"
fi

# --- what a working install looks like -------------------------------------

ENV_FILE="$WORK/packages/node/.env"
[ -f "$ENV_FILE" ] || fail "installer did not create packages/node/.env"

grep -q '^NODE_ID=' "$ENV_FILE" || fail ".env has no NODE_ID"
# The node's control API fails closed without this (ROADMAP 0.1), so an install
# that omits it produces a node that serves nothing. The deleted duplicate Windows
# installer did exactly that.
grep -qE '^NODE_NETWORK_AUTH_TOKEN=.{16,}' "$ENV_FILE" \
    || fail ".env has no generated NODE_NETWORK_AUTH_TOKEN"

VENV_PY="$WORK/packages/node/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$WORK/packages/node/.venv/Scripts/python.exe"
[ -x "$VENV_PY" ] || fail "installer did not create a usable venv at packages/node/.venv"

# The weakest claim worth making: `pip install -e` can succeed and still leave a
# package that cannot be imported.
"$VENV_PY" -c 'import node; import node.main' >/dev/null 2>&1 \
    || fail "the installed interpreter cannot import the node package"

[ -e "$WORK/public-intelligence-node" ] || fail "installer did not create the runner link"

printf '\033[32mOK\033[0m    install.sh produced a working node (env, venv, importable package, runner link)\n'
