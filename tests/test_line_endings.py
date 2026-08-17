"""Shell scripts are LF in the index, and `.gitattributes` keeps them that way.

CI was red on all three Windows legs from 2026-08-09 to 2026-08-17 -- across the
`v1.0.0` release commit -- partly because `shellcheck` could not parse
`install.sh`::

    In install.sh line 395:
    ^-- SC1017 (error): Literal carriage return. Run script through tr -d '\\r' .
    ...
    ^-^ SC1042 (error): Close matches include 'EOF\\r' (!= 'EOF').

Nothing was wrong with the committed file: it is LF in the index on every
platform. There was **no `.gitattributes`**, so `actions/checkout` applied the
Windows runner's `core.autocrlf=true` and rewrote every `.sh` file to CRLF on
checkout. shellcheck was right to refuse it -- a here-document terminator with a
trailing CR genuinely does not match its opener, which is why the errors cascade
from `SC1017` into `SC1073`/`SC1041`/`SC1042`/`SC1072`.

**These assertions read the INDEX, not the working tree.** On Linux a working-tree
check passes vacuously -- the files are LF here no matter what `.gitattributes`
says -- so it would pin nothing and would have been green throughout the eight
days CI was red. `git ls-files --eol` reports what git has stored and what the
attributes resolve to, which is the thing that actually differs per platform.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GITATTRIBUTES = REPO_ROOT / ".gitattributes"


def _ls_files_eol() -> list[tuple[str, str, str]]:
    """Return (index_eol, resolved_attr, path) for every tracked shell script.

    `git ls-files --eol` prints e.g.::

        i/lf    w/lf    attr/text eol=lf      \tinstall.sh

    The attribute field **contains spaces**, so it is taken as everything from
    `attr/` up to the tab rather than by splitting on whitespace. Splitting
    yielded `attr/text` and silently discarded the `eol=lf` this whole file
    exists to assert -- a parser bug that made every assertion here fail for the
    wrong reason, which red-green caught and reading the code had not.
    """
    result = subprocess.run(
        ["git", "ls-files", "--eol", "-z", "--", "*.sh"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    rows: list[tuple[str, str, str]] = []
    for entry in result.stdout.split("\0"):
        if not entry.strip():
            continue
        info, _, path = entry.partition("\t")
        index_eol = next((f for f in info.split() if f.startswith("i/")), "")
        # Everything from `attr/` to the tab -- NOT a whitespace split, because
        # the resolved attributes are themselves space-separated.
        attr = "attr/" + info.partition("attr/")[2].strip()
        rows.append((index_eol, attr, path.strip()))
    return rows


def test_gitattributes_exists() -> None:
    """The file whose absence broke Windows CI for eight days."""
    assert GITATTRIBUTES.is_file(), (
        ".gitattributes is missing. Without it a Windows checkout applies "
        "core.autocrlf=true and rewrites every .sh file to CRLF, which shellcheck "
        "rejects with SC1017. See specs/ci-green-on-windows.md."
    )


def test_shell_scripts_are_pinned_to_lf() -> None:
    """`*.sh` must resolve to `eol=lf`, so a Windows checkout gets LF."""
    text = GITATTRIBUTES.read_text(encoding="utf-8")
    directives = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert any("*.sh" in line and "eol=lf" in line for line in directives), (
        "No directive pins *.sh to eol=lf. Found:\n  " + "\n  ".join(directives)
    )


def test_every_tracked_shell_script_resolves_to_lf() -> None:
    """Not just the pattern -- what git actually resolves for each real file.

    A rule can exist and still miss a file (a later overriding line, a path the
    glob does not reach). This asserts the resolved attribute per tracked script,
    which is what a Windows checkout will act on.
    """
    rows = _ls_files_eol()
    assert rows, "no tracked .sh files found -- this test is not checking anything"

    unpinned = [(attr, path) for _, attr, path in rows if "eol=lf" not in attr]
    assert not unpinned, (
        "these tracked shell scripts do not resolve to eol=lf, so a Windows "
        "checkout will convert them to CRLF and shellcheck will fail:\n  "
        + "\n  ".join(f"{path} -> {attr}" for attr, path in unpinned)
    )


def test_no_shell_script_is_stored_with_crlf() -> None:
    """The index itself must be LF. `.gitattributes` fixes checkout, not history.

    If a CRLF file were committed before the rule existed, the rule alone would
    not clean it -- so this checks the stored bytes rather than trusting the
    attribute.
    """
    crlf = [path for index_eol, _, path in _ls_files_eol() if index_eol == "i/crlf"]
    assert not crlf, (
        "these shell scripts are stored with CRLF in the index and must be "
        "renormalised (`git add --renormalize .`):\n  " + "\n  ".join(crlf)
    )


@pytest.mark.parametrize(
    "script",
    [
        "install.sh",
        "scripts/verify.sh",
        "scripts/bootstrap.sh",
        "scripts/install-hooks.sh",
        "scripts/verify_install.sh",
        "scripts/launch_host_node.sh",
    ],
)
def test_the_scripts_the_gate_shellchecks_are_covered(script: str) -> None:
    """The exact file list `scripts/verify.sh` passes to shellcheck.

    Named individually so that adding a script to the gate without covering it
    here is visible. `install.sh` is the one that actually broke.
    """
    assert (REPO_ROOT / script).is_file(), f"{script} is missing"
    rows = {path: attr for _, attr, path in _ls_files_eol()}
    assert script in rows, f"{script} is not tracked by git"
    assert "eol=lf" in rows[script], f"{script} resolves to {rows[script]}, not eol=lf"
