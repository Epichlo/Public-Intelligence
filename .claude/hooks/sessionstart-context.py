#!/usr/bin/env python3
"""SessionStart: record this session's baseline, and put real repo state in context.

Two jobs, both cheap:

1. **Record `HEAD`** into `zones/claimed/session-<id>.json`. `require-proof-stop.py`
   compares against it so that committing a change does not launder it -- commit and
   the tree is clean again, which a dirty-tree check alone would wave through.

2. **Print state to stdout**, which SessionStart injects into the context window. The
   point is that these facts are *measured at session start* rather than recalled:
   `CLAUDE.md` records a session that reported "CI unverifiable" for a change whose CI
   run had already failed, because prose in a doc cannot notice when it goes stale.

Failure here is silent and total by design. A session that starts without its baseline
loses one enforcement signal; a session that cannot start at all loses everything.
"""

import json
import subprocess
import sys
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOK_DIR.parent.parent / "scripts"))

from state_fingerprint import repo_root  # noqa: E402


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    # No payload means no session id, which costs the baseline and nothing else.
    except Exception:
        payload = {}

    try:
        root = repo_root()
        head = _git(root, "rev-parse", "HEAD")

        session_id = str(payload.get("session_id") or "")
        if session_id:
            claimed = root / "zones" / "claimed"
            claimed.mkdir(parents=True, exist_ok=True)
            (claimed / f"session-{session_id}.json").write_text(
                json.dumps(
                    {"head": head, "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD")}
                ),
                encoding="utf-8",
            )

        bundle = root / "zones" / "verified" / "latest.verified.json"
        try:
            evidence = json.loads(bundle.read_text(encoding="utf-8"))
            state = (
                f"{evidence.get('verdict')} for commit {str(evidence.get('commit'))[:8]}"
                if evidence.get("commit") == head
                else "STALE -- the last gate run describes a different commit"
            )
        except (OSError, ValueError):
            state = "none -- the gate has not run against this checkout"

        dirty = _git(root, "status", "--porcelain")
        print(f"Branch {_git(root, 'rev-parse', '--abbrev-ref', 'HEAD')} at {head[:8]}.")
        print(f"Gate evidence: {state}.")
        print(f"Working tree: {'dirty' if dirty else 'clean'}.")
        print("Recent commits:")
        print(_git(root, "log", "--oneline", "-5"))
        print(
            "Reminder: zones/verified/ is written by ./scripts/verify.sh alone. "
            "A completion claim needs a matching bundle, not a recollection."
        )
    # Never stop a session from starting. Losing the baseline costs one
    # enforcement signal; failing here would cost the whole session.
    except Exception:
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
