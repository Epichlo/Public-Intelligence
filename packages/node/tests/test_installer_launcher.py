"""Unit and integration tests for install.sh script and launch_host_node.sh launcher."""

import subprocess
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    """Walk up until the directory holding install.sh is found.

    Counting `.parent` levels broke when the package moved from `Node/` to
    `packages/node/` during the monorepo migration -- the depth from a test file to
    the repo root changed. Searching for a landmark does not care about depth.
    """
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "install.sh").is_file():
            return candidate
    raise RuntimeError("repo root (the directory containing install.sh) not found")


# These tests execute install.sh and launch_host_node.sh directly. Windows cannot
# exec a shell script -- subprocess raises OSError [WinError 193] "%1 is not a
# valid Win32 application" -- and it is not meant to: Windows hosts are installed
# via install.ps1, which is exercised separately by the CI installer step.
#
# This is a genuinely POSIX-only surface, not an unimplemented feature. If these
# ever need Windows coverage, the target is install.ps1, not these scripts.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX installer scripts; Windows hosts use install.ps1",
)


def test_install_script_help() -> None:
    """Verify install.sh --help displays usage and exits with 0."""
    project_root = _repo_root()
    install_script = project_root / "install.sh"

    assert install_script.exists(), "install.sh script must exist at project root"

    result = subprocess.run(
        [str(install_script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Public Intelligence One-Click Host Node Installer" in result.stdout
    assert "--dry-run" in result.stdout


def test_install_script_dry_run() -> None:
    """Verify install.sh --dry-run performs hardware discovery."""
    project_root = _repo_root()
    install_script = project_root / "install.sh"

    result = subprocess.run(
        [str(install_script), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "[DRY-RUN]" in result.stdout
    assert "Hardware Auto-Discovery Results:" in result.stdout
    assert "CPU Logical Cores" in result.stdout
    assert "Host System RAM" in result.stdout
    assert "GPU Vendor / Model:" in result.stdout
    assert "Installation Simulation Complete" in result.stdout


def test_launcher_script_help() -> None:
    """Verify launch_host_node.sh --help displays usage."""
    project_root = _repo_root()
    launcher_script = project_root / "scripts" / "launch_host_node.sh"

    assert launcher_script.exists(), "scripts/launch_host_node.sh script must exist"

    result = subprocess.run(
        [str(launcher_script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert "Usage: " in result.stdout or "Usage: " in result.stderr
    assert "start|stop|restart|status|logs" in result.stdout


def test_launcher_script_status_stopped() -> None:
    """Verify launch_host_node.sh status indicates STOPPED when no daemon is running."""
    project_root = _repo_root()
    launcher_script = project_root / "scripts" / "launch_host_node.sh"

    pid_file = project_root / "Node" / "node.pid"
    if pid_file.exists():
        pid_file.unlink()

    result = subprocess.run(
        [str(launcher_script), "status"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "STOPPED" in result.stdout
