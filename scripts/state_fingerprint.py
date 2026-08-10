#!/usr/bin/env python3
"""A hash of the working tree's uncommitted state, so evidence can go stale.

`scripts/verify.sh` records this in the evidence bundle; `.claude/hooks/require-proof-stop.py`
recomputes it and refuses a bundle that no longer matches. That pairing is the whole
mechanism: it turns "the gate passed at some point" into "the gate passed on *this*".

The architecture blueprint's Stop hook took the newest `zones/verified/*.json` by
mtime and trusted it. Run the gate, edit one line, stop -- the bundle is still newest
and still says PASS, about code that no longer exists. `CLAUDE.md` already knew the
shape of this ("if that file's commit is not HEAD, whatever it says is about code
that no longer exists") and only solved half, because the old receipt recorded
`working_tree_dirty` as a boolean and a dirty tree keeps changing afterwards.

ONE implementation, two callers. The gate shells out to the CLI below; the hook
imports `compute`. A second copy of this hashing in bash would drift from this one
silently, and a fingerprint that disagrees with itself fails open every time.

Ignored files are excluded via `--exclude-standard`, which is what lets the gate
write its bundle into the gitignored `zones/` without invalidating the bundle it
just wrote.
"""

import hashlib
import subprocess
import sys
from pathlib import Path


class NotAGitRepositoryError(RuntimeError):
    """Raised when there is no git context to fingerprint."""


def _git(root: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise NotAGitRepositoryError(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


def repo_root(start: Path | None = None) -> Path:
    """The git top level containing `start`, defaulting to the current directory."""
    origin = start or Path.cwd()
    out = _git(origin, "rev-parse", "--show-toplevel")
    return Path(out.decode("utf-8").strip())


def compute(root: Path) -> str:
    """SHA-256 over the tracked diff plus every untracked, non-ignored file.

    `git diff HEAD` covers modifications to tracked files, staged or not. It does NOT
    see untracked files, so a fingerprint over the diff alone would let an entire new
    module land after the gate ran and still match.
    """
    digest = hashlib.sha256()
    digest.update(_git(root, "diff", "HEAD"))

    listing = _git(root, "ls-files", "--others", "--exclude-standard")
    for name in sorted(n for n in listing.decode("utf-8").split("\n") if n):
        digest.update(name.encode("utf-8"))
        try:
            digest.update((root / name).read_bytes())
        except OSError:
            # A file that vanished between listing and reading is still a change.
            digest.update(b"<unreadable>")

    return digest.hexdigest()


def main() -> int:
    try:
        print(compute(repo_root()))
    except NotAGitRepositoryError as exc:
        print(f"not a git repository: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
