"""Shipped defaults must point somewhere that exists (ROADMAP C1, decision D6).

`install.sh` wrote `NODE_BOOTSTRAP_ROUTERS=["tcp/bootstrap.public-intelligence.net:7447"]`
and `NODE_SCHEDULER_URL=https://scheduler-publicintelligence.onrender.com` into every
`.env` it generated. The hostname is NXDOMAIN and the Scheduler does not answer, so
the installer's happy path produced a node that connected to nothing -- and failed
slowly and quietly rather than immediately and clearly.

[D6](../docs/decisions/D6-is-there-a-network.md) decided not to operate a network, so
the fix is `localhost` defaults rather than registering the domain: making the shipped
configuration *reachable* would not have made it *correct*.

**The durable point is this file, not the defaults.** The bug was not that a hostname
was wrong; it was that nothing would have noticed. These tests fail if a
non-resolving name re-enters any shipped default.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Hostnames this project has claimed to operate and does not. Kept as an explicit
# denylist rather than "anything that does not resolve", because a DNS lookup in a
# test is flaky, network-dependent, and would start passing the moment somebody
# parked the domain -- which is not the same as operating a router on it.
DEAD_HOSTS = (
    "bootstrap.public-intelligence.net",
    "scheduler-publicintelligence.onrender.com",
    "public-intelligence.net",
)

# Files that configure a node someone installs. docker-compose.test.yml is excluded
# deliberately: its `scheduler` hostname is a compose service name, which resolves
# inside that network and is meant to.
SHIPPED_CONFIG_FILES = (
    "install.sh",
    "install.ps1",
    "packages/node/src/node/core/configuration.py",
    "scripts/launch_host_node.sh",
)


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _code_only(rel: str) -> str:
    """File contents with comments stripped.

    Scanning raw text would match the comments that explain why these hosts are
    gone -- which is the second time in this change set that a check fired on its
    own documentation of the bug. Python is parsed properly; shell and PowerShell
    get line-level `#` stripping, which is enough because the references being
    guarded against are assignments, not mid-line remarks.
    """
    text = _read(rel)
    if rel.endswith(".py"):
        return "\n".join(
            node.value
            for node in ast.walk(ast.parse(text))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


@pytest.mark.parametrize("rel", SHIPPED_CONFIG_FILES)
def test_no_shipped_default_points_at_a_host_we_do_not_operate(rel: str) -> None:
    """The ratchet. A dead hostname must not come back into any installer default."""
    text = _code_only(rel)
    found = [host for host in DEAD_HOSTS if host in text]
    assert not found, (
        f"{rel} references {found}, which this project does not operate "
        f"(docs/decisions/D6-is-there-a-network.md). A node installed with this "
        f"default connects to nothing, slowly."
    )


def test_the_node_defaults_to_no_bootstrap_router() -> None:
    """An empty router list means multicast scouting only -- correct for a LAN.

    The alternative considered was defaulting to `tcp/localhost:7447`. Rejected:
    that dials a port nothing listens on unless the operator runs a router, which
    trades a dead remote name for a dead local one.
    """
    from node.core.configuration import Settings

    assert Settings(network_auth_token="t" * 64).bootstrap_routers == [], (
        "bootstrap_routers is not empty by default; a fresh install must scout the "
        "local network instead of dialling a fixed host."
    )


def test_the_node_defaults_to_a_local_scheduler() -> None:
    from node.core.configuration import Settings

    # 8000 not 8080: 8080 is the node's own port, so the old default pointed a node
    # at itself.
    assert Settings(network_auth_token="t" * 64).scheduler_url == "http://localhost:8000", (
        "the node's default scheduler_url is not a local Scheduler. Under D6 this "
        "is a self-hosted product: the default must be one the same person runs."
    )


@pytest.mark.parametrize("rel", ["install.sh", "install.ps1"])
def test_the_installer_defaults_to_a_local_scheduler(rel: str) -> None:
    text = _code_only(rel)
    assert "localhost:8000" in text, f"{rel} does not default NODE_SCHEDULER_URL to localhost"


def test_the_dry_run_prints_what_the_real_run_writes() -> None:
    """The dry-run was lying, and the dry-run is what CI checked for two days.

    `install.sh --dry-run` printed `NODE_SCHEDULER_URL=http://localhost:8080` while
    the real path wrote `https://scheduler-publicintelligence.onrender.com`. Two
    different values from the same function, and the gate only ever ran the one that
    was wrong in the other direction.

    ROADMAP 2.8 already found that every dry-run step returns early after printing
    what it *would* do, which is why `scripts/verify_install.sh` runs the installer
    for real. This checks the remaining half: that what it prints matches what it
    writes.
    """
    text = _read("install.sh")

    printed = re.findall(r'log_dry_run "  (NODE_[A-Z_]+)=(.*?)"$', text, flags=re.MULTILINE)
    assert printed, "no dry-run output lines found -- did the format change?"

    written = dict(re.findall(r"^(NODE_[A-Z_]+)=(.*)$", text, flags=re.MULTILINE))

    mismatches = []
    for key, dry_value in printed:
        if key not in written:
            continue
        real = written[key]
        # Both sides interpolate shell variables; compare only concrete literals.
        if "$" in real or "$" in dry_value or "<" in dry_value:
            continue
        if real.replace("\\", "") != dry_value.replace("\\", ""):
            mismatches.append(f"{key}: dry-run says {dry_value!r}, real run writes {real!r}")

    assert not mismatches, (
        "install.sh --dry-run reports values the real run does not write. The "
        f"dry-run is a gate step, so a lie here is a lie CI repeats: {mismatches}"
    )


def test_the_installer_gives_the_dashboard_the_node_credential(tmp_path: Path) -> None:
    """ROADMAP 3.5. The two files must hold the SAME token, written by one process.

    The dashboard talks to the node's control API, which fails closed, so it needs
    the credential the node was just given. Until now that meant reading
    `packages/node/.env` by hand and pasting the value into a second file --
    "acceptable for you, not for a contributor".

    Run for real against a throwaway copy rather than asserted from the source,
    because ROADMAP 2.8 established that every step of `--dry-run` returns early
    after printing what it *would* do: the dry-run cannot prove two files agree.
    """
    import shutil
    import subprocess

    work = tmp_path / "repo"
    shutil.copytree(
        REPO_ROOT,
        work,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "node_modules", "__pycache__", "*.db", ".next"
        ),
        # Copy symlinks as symlinks. install.sh creates a runner symlink at the repo
        # root, and a dangling one -- which is what a stale link from a previous
        # layout looks like -- makes a dereferencing copy raise.
        symlinks=True,
    )

    result = subprocess.run(
        ["bash", str(work / "install.sh"), "--skip-venv", "--skip-docker", "--force"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=work,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]

    node_env = (work / "packages/node/.env").read_text(encoding="utf-8")
    web_env = (work / "packages/website/.env.local").read_text(encoding="utf-8")

    def value(text: str, key: str) -> str:
        for line in text.splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
        raise AssertionError(f"{key} not found in:\n{text}")

    node_token = value(node_env, "NODE_NETWORK_AUTH_TOKEN")
    web_token = value(web_env, "NODE_AUTH_TOKEN")

    assert node_token, "the node was given no credential at all"
    assert web_token == node_token, (
        "the dashboard's NODE_AUTH_TOKEN does not match the node's "
        "NODE_NETWORK_AUTH_TOKEN, so the dashboard will get 401 from the node"
    )
