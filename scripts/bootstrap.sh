#!/usr/bin/env bash
# ==============================================================================
# Public Intelligence - one-command host bootstrap
# ==============================================================================
# Fetch the project and start a host node in a single line:
#
#   curl -fsSL https://raw.githubusercontent.com/Epichlo/Public-Intelligence/main/scripts/bootstrap.sh \
#     | bash -s -- --scheduler-url https://scheduler.example --fleet-token TOKEN --invite-code CODE
#
# Everything after `bash -s --` is forwarded verbatim to install.sh (see
# `install.sh --help`). This clones (or updates) the repo and runs `install.sh --start`,
# so the one line ends with a RUNNING node rather than just files.
#
# curl|bash runs remote code. This script embeds no secrets and writes none -- it runs
# the repository's own install.sh. Read it at the URL first if you prefer, or clone the
# repo and run `./install.sh --start` yourself; the two paths are equivalent.
# ==============================================================================
set -euo pipefail

# Overridable so the same script serves a real install and a hermetic test (the gate
# points PI_REPO at a local git origin and PI_BRANCH at the branch under test).
PI_REPO="${PI_REPO:-https://github.com/Epichlo/Public-Intelligence.git}"
PI_BRANCH="${PI_BRANCH:-main}"
PI_DIR="${PI_DIR:-${HOME}/public-intelligence}"

log() { printf '\033[0;34m[bootstrap]\033[0m %s\n' "$1"; }
die() {
    printf '\033[0;31m[bootstrap] %s\033[0m\n' "$1" >&2
    exit 1
}

command -v git >/dev/null 2>&1 || die "git is required but was not found on PATH."

if [[ -d "${PI_DIR}/.git" ]]; then
    # Re-running the one-liner updates in place rather than failing on a full directory.
    log "Updating existing checkout at ${PI_DIR}..."
    git -C "${PI_DIR}" pull --ff-only origin "${PI_BRANCH}"
elif [[ -e "${PI_DIR}" ]]; then
    die "${PI_DIR} exists but is not a git checkout. Move it, or set PI_DIR to another path."
else
    log "Cloning ${PI_REPO} (${PI_BRANCH}) into ${PI_DIR}..."
    git clone --depth 1 --branch "${PI_BRANCH}" "${PI_REPO}" "${PI_DIR}"
fi

INSTALL="${PI_DIR}/install.sh"
[[ -f "${INSTALL}" ]] || die "install.sh not found at ${INSTALL} after fetch."

log "Running the installer and starting the node..."
# --start makes the installer leave a running daemon; "$@" forwards the flags the caller
# passed after `bash -s --`, so --scheduler-url / --fleet-token / --invite-code reach it.
exec bash "${INSTALL}" --start "$@"
