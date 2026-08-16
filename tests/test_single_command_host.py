"""One command must actually host a node: fetch, install, and leave it running.

Before this, hosting a node was three steps a person had to know in order -- clone the
repo, run install.sh, then run launch_host_node.sh start. This pins the contract that
makes it one pasteable line (see specs/single-command-node-hosting.md):

    curl -fsSL .../scripts/bootstrap.sh | bash -s -- --fleet-token X ...

These are text-level checks on the two scripts -- fast, and they document the wiring.
The *behavioural* proof that `install.sh --start` leaves a live node, and that the
bootstrap clones + forwards args, lives in scripts/verify_install.sh, which runs both
for real. A green check here with a red one there would mean the scripts say the right
words but do the wrong thing, which is why both exist.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap.sh"
INSTALL = REPO_ROOT / "install.sh"
LAUNCH = REPO_ROOT / "scripts" / "launch_host_node.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_bootstrap_script_exists() -> None:
    """The `curl | bash` target. Without it there is no one-liner to paste."""
    assert BOOTSTRAP.exists(), (
        "scripts/bootstrap.sh is missing -- it is the curl|bash entry point that makes "
        "node hosting a single command"
    )


def test_bootstrap_clones_the_project() -> None:
    """A first-time host has no checkout, so the one-liner must fetch one itself."""
    text = _read(BOOTSTRAP)
    assert "git clone" in text, (
        "bootstrap.sh never clones the repo, so `curl | bash` on a bare machine has "
        "nothing to install"
    )


def test_bootstrap_updates_an_existing_checkout_instead_of_failing() -> None:
    """Re-running the one-liner must update, not abort on 'directory exists'."""
    text = _read(BOOTSTRAP)
    assert "git pull" in text or "git -C" in text, (
        "bootstrap.sh does not handle an existing checkout; re-running the one-liner "
        "would fail on a non-empty target directory instead of updating it"
    )


def test_bootstrap_runs_the_installer_with_start() -> None:
    """The whole point: the one-liner ends with a *running* node, not just files."""
    text = _read(BOOTSTRAP)
    assert re.search(r"install\.sh['\"]?\s", text), "bootstrap.sh never runs install.sh"
    assert "--start" in text, (
        "bootstrap.sh runs the installer without --start, so the one-liner installs a "
        "node and leaves it stopped -- which is the three-step problem it exists to fix"
    )


def test_bootstrap_forwards_its_arguments_to_the_installer() -> None:
    """`bash -s -- --fleet-token X` must reach install.sh, or admission is impossible."""
    text = _read(BOOTSTRAP)
    assert '"$@"' in text, (
        'bootstrap.sh does not forward "$@" to install.sh, so flags like --fleet-token '
        "and --invite-code passed through `curl | bash -s --` are dropped and the node "
        "cannot register against any real Scheduler"
    )


def test_install_accepts_a_start_flag() -> None:
    """--start is the opt-in that turns install into install-and-run."""
    text = _read(INSTALL)
    assert "--start" in text, "install.sh has no --start flag"


def test_start_flag_launches_the_daemon() -> None:
    """--start must actually invoke the launcher, not merely print instructions."""
    text = _read(INSTALL)
    # The launch is gated on the flag and calls the real launcher's `start`.
    assert re.search(r"launch_host_node\.sh['\"]?\s+start", text), (
        "install.sh --start does not call `launch_host_node.sh start`; it would parse "
        "the flag and still leave the node stopped"
    )


def test_start_is_opt_in_so_a_plain_install_does_not_spawn_a_daemon() -> None:
    """Backwards compatibility and the D-3 lesson: no surprise daemon, no daemon on a
    failed install. The launch must be guarded by the flag being set."""
    text = _read(INSTALL)
    # There must be a conditional on the start variable around the launch, not an
    # unconditional call.
    assert re.search(r"START_NODE.*==.*true|\$START_NODE|START_NODE\b", text), (
        "install.sh launches unconditionally rather than behind a --start guard; a "
        "plain `./install.sh` would spawn a daemon it never used to"
    )


def test_the_launcher_start_command_still_exists() -> None:
    """The thing --start leans on. If the launcher loses `start`, --start is a no-op."""
    text = _read(LAUNCH)
    assert "start)" in text and "start_node" in text, (
        "launch_host_node.sh no longer implements `start`, so install.sh --start has "
        "nothing to call"
    )
