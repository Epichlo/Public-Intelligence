"""Every path the installers reference must exist (ROADMAP 2.8).

This test exists because `verify.sh` ran `install.sh --dry-run`, and every step of
that script returns early in dry-run mode *after printing what it would do*. So the
gate exercised the printing and never the doing, and CI stayed green for two days
over an installer that exits 1 on its first write -- the paths still pointed at
`Node/`, which the 2026-08-04 monorepo migration renamed to `packages/node/`.

`scripts/verify_install.sh` is the strong check: it runs the installer for real.
This one is the weak-but-universal companion. `verify.sh` skips `install.sh`
entirely on Windows runners, so `install.ps1` can never be covered by a real run
here -- reading its paths is the only coverage it can get without a Windows host.
The two are deliberately different strengths, and this file is the weaker one.

See specs/installer-actually-installs.md.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

INSTALLERS = [
    "install.sh",
    "install.ps1",
    "scripts/launch_host_node.sh",
]

# Repo-relative paths appearing in the installers. Deliberately narrow: this is
# meant to catch a stale directory name, not to parse shell or PowerShell.
#
# The third pattern is what covers `install.ps1`, which builds paths with
# `Join-Path` and so never writes `${PROJECT_ROOT}/...`. Without it that file's
# parametrised case passed vacuously -- found while writing this, by checking which
# assertions actually failed against the broken scripts rather than trusting a red
# count.
PATH_PATTERNS = [
    re.compile(r"\$\{PROJECT_ROOT\}/([A-Za-z0-9_./-]+)"),
    re.compile(r"\$PROJECT_ROOT/([A-Za-z0-9_./-]+)"),
    re.compile(r"[\"'](packages[/\\][A-Za-z0-9_./\\-]+)[\"']"),
]

# A `Node`/`Scheduler`/`website` path SEGMENT: preceded by a separator, followed by
# one, or by a quote or end of line. Matches `${PROJECT_ROOT}/Node/.env` and
# `"${PROJECT_ROOT}/Node"` alike. Plain `[/\\]Node` without the lookahead would hit
# `packages/node` on case-insensitive filesystems and any prose mentioning a path.
STALE_LAYOUT = re.compile(r"[/\\](Node|Scheduler|website)(?=[/\\\"'\s]|$)")

# Paths the installer CREATES rather than reads. Their absence is the normal state
# of a fresh checkout, so requiring them to exist would be wrong.
CREATED_BY_THE_INSTALLER = {
    "packages/node/.env",
    "packages/node/.venv",
    "public-intelligence-node",
}


def referenced_paths(script: str) -> set[str]:
    """Repo-relative paths a script names, minus the ones it creates."""
    text = (REPO_ROOT / script).read_text(encoding="utf-8")
    found: set[str] = set()
    for pattern in PATH_PATTERNS:
        for match in pattern.findall(text):
            # Trim to the first component that the installer creates, so
            # `packages/node/.venv/bin/pip` is judged as `packages/node/.venv`.
            cleaned = match.rstrip("/")
            if any(cleaned == c or cleaned.startswith(f"{c}/") for c in CREATED_BY_THE_INSTALLER):
                continue
            found.add(cleaned)
    return found


@pytest.mark.parametrize("script", INSTALLERS)
def test_every_path_an_installer_references_exists(script: str) -> None:
    """A stale directory name must fail here, not on a host's machine.

    The migration renamed `Node/` to `packages/node/` and left four scripts behind.
    A host on macOS or Linux got `No such file or directory` and exit 1.
    """
    missing = sorted(p for p in referenced_paths(script) if not (REPO_ROOT / p).exists())

    assert not missing, f"{script} references paths that do not exist: {missing}"


@pytest.mark.parametrize("script", INSTALLERS)
def test_no_installer_still_points_at_the_pre_monorepo_layout(script: str) -> None:
    """`Node/`, `Scheduler/` and `website/` have not existed since 2026-08-04.

    Catches the stale name as a path segment, which `"${PROJECT_ROOT}/Node"` is and
    a substring search for `"Node/"` is not -- `scripts/launch_host_node.sh` has
    exactly that form and passed an earlier version of this assertion while being
    thoroughly broken.
    """
    text = (REPO_ROOT / script).read_text(encoding="utf-8")
    stale = sorted(set(STALE_LAYOUT.findall(text)))

    assert not stale, f"{script} still refers to the pre-monorepo layout: {stale}"


def test_the_windows_installer_does_not_fetch_the_archived_repo() -> None:
    """`install.ps1` cloned `Node-PublicIntelligence` when run outside a checkout.

    That repo is the pre-monorepo Node, frozen at the migration. Windows hosts did
    not get an error -- they got a node predating 1.4, 1.6, 2.1, 2.3 and 2.4.
    Silently installing stale software is worse than failing.

    Matches a URL, not the bare name: the file explains this history in a comment
    that names the old repo, and forbidding the *name* would delete the explanation
    of why the code looks the way it does. Fetching it is the defect.
    """
    text = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")
    fetches = re.findall(r"github\.com/Epichlo/([A-Za-z0-9._-]+)", text)

    assert "Node-PublicIntelligence" not in fetches, (
        f"install.ps1 still fetches the archived pre-monorepo repo: {fetches}"
    )


def test_there_is_exactly_one_windows_installer() -> None:
    """Two copies is how the one next to the package drifted.

    `packages/node/install.ps1` never generated `NODE_NETWORK_AUTH_TOKEN`, and the
    node's control API fails closed without it (ROADMAP 0.1) -- so that copy
    produced a node that serves nothing.
    """
    found = sorted(str(p.relative_to(REPO_ROOT)) for p in REPO_ROOT.rglob("install.ps1"))

    assert found == ["install.ps1"], f"expected one Windows installer, found: {found}"


def test_the_windows_installer_still_generates_a_control_api_credential() -> None:
    """The thing the deleted duplicate was missing. Pin it so it cannot go again."""
    text = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "NODE_NETWORK_AUTH_TOKEN" in text
