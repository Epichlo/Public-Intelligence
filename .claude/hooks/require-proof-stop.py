#!/usr/bin/env python3
"""Stop: refuse to end a session that changed code without machine-checked evidence.

This is the deterministic half of `CLAUDE.md`'s "claims about tests, CI, or behaviour
require output from **this session**". The instruction is followed most of the time.
This is followed every time, because it is an OS process rather than a request.

The contract:

* Nothing changed -> allow. A session that answered a question has nothing to prove,
  and a Stop hook that always blocks is a loop (see the blueprint's caveats).
* Code changed -> require `zones/verified/latest.verified.json` with `verdict: pass`,
  whose `commit` and `state_fingerprint` match the tree right now.
* Anything unexpected -> allow. A guard that cannot compute an answer has no basis
  to block, and wedging the repo is worse than the gap it was closing.

Signalling is `{"decision": "block", "reason": ...}` on stdout with exit 0. Note the
absence of `hookSpecificOutput`: its `hookEventName` enum excludes Stop, so attaching
it makes the runtime discard the whole payload -- the block silently becomes an allow,
which is the worst failure available to this file because it still looks like it works.
"""

import json
import subprocess
import sys
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
# Resolved from this file, never from the working directory: the fingerprint helper
# lives in THIS repo, while the tree being fingerprinted may be somewhere else.
sys.path.insert(0, str(HOOK_DIR.parent.parent / "scripts"))

from state_fingerprint import NotAGitRepositoryError, compute, repo_root  # noqa: E402

BUNDLE = Path("zones") / "verified" / "latest.verified.json"


def _block(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def _git_out(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _session_changed_code(root: Path, session_id: str) -> bool:
    """Dirty tree, or HEAD moved past this session's SessionStart baseline.

    The baseline is what stops `git commit` laundering the work: commit and the tree
    is clean again, so a dirty-tree test alone would wave it through. A missing
    baseline (hook installed mid-session) falls back to the dirty-tree signal rather
    than blocking, because an enforcement gap is not evidence of wrongdoing.
    """
    if _git_out(root, "status", "--porcelain"):
        return True

    if not session_id:
        return False

    baseline_file = root / "zones" / "claimed" / f"session-{session_id}.json"
    try:
        baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False

    recorded = baseline.get("head")
    return bool(recorded) and recorded != _git_out(root, "rev-parse", "HEAD")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    # Unparseable input is no basis to block.
    except Exception:
        return 0

    if payload.get("stop_hook_active"):
        return 0

    try:
        root = repo_root()
        if not _session_changed_code(root, str(payload.get("session_id") or "")):
            return 0

        bundle_path = root / BUNDLE
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _block(
                f"No usable {BUNDLE.as_posix()} exists, but this session changed code. "
                "Run ./scripts/verify.sh and let it write the evidence -- a summary of "
                "what you believe the tests do is not evidence. If the gate cannot run "
                "here, say so explicitly instead of reporting success."
            )

        if bundle.get("verdict") != "pass":
            failed = [
                step.get("step", "?")
                for step in bundle.get("steps", [])
                if step.get("result") != "pass"
            ]
            return _block(
                f"The last gate run FAILED: {', '.join(failed) or 'see the bundle'}. "
                "Fix it and re-run ./scripts/verify.sh, or report the failure plainly. "
                "Do not describe a failing gate as passing."
            )

        current = compute(root)
        head = _git_out(root, "rev-parse", "HEAD")
        if bundle.get("commit") != head or bundle.get("state_fingerprint") != current:
            return _block(
                "The evidence bundle is stale -- the tree has changed since the gate "
                "ran, so it describes code that no longer exists. Re-run "
                "./scripts/verify.sh."
            )

        skipped = bundle.get("skipped") or []
        if skipped:
            print(
                f"note: the passing run skipped {', '.join(skipped)}; "
                "this PASS is weaker than a CI PASS.",
                file=sys.stderr,
            )

    except NotAGitRepositoryError:
        return 0
    # A guard that crashed cannot justify blocking a session. Degrade to the
    # status quo -- an enforcement gap, not a wedged repository.
    except Exception:
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
