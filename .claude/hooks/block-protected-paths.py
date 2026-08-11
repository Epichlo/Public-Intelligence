#!/usr/bin/env python3
"""PreToolUse: deny writes to secrets and to the machine-verified zone.

Exit 2 is the only "deny" signal a PreToolUse hook has; stderr is fed back to the
model so it learns why. Any other non-zero is read as a crashed hook and does not
block, which is why every unexpected error here exits 0 deliberately -- a broken
enforcer must degrade to the status quo, never brick every tool call in the repo.

Two departures from `docs/CLAUDE_CODE_ARCHITECTURE.md`:

* **Python, not bash+jq.** `tests/test_agent_governance.py` runs these hooks on all
  three CI platforms, and jq is not a given on the Windows legs. One interpreter is
  already a hard dependency of this repo.
* **Bash commands are inspected too.** The blueprint reads `tool_input.file_path`,
  which guards Edit and Write and leaves `echo > zones/verified/x.json` wide open --
  a guard bypassed by the one tool every agent already has is decoration.

What is deliberately NOT blocked: ordinary source edits. Anthropic's guidance is
explicit that interrupting Edit/Write mid-plan breaks multi-step reasoning. Quality
enforcement lives at the Stop hook and in CI.
"""

import json
import shlex
import sys

# Substrings that make a path protected. `.env.example` is the documented sample and
# is excluded below -- .gitignore already carries the same exception.
PROTECTED = ("zones/verified/", ".env", "secrets/", ".pem", ".key")

# Commands that cannot modify their arguments. If `zones/verified` is mentioned and
# every pipeline segment starts with one of these -- and nothing is redirected -- the
# call is a read. Anything else near that path is denied.
#
# A whitelist rather than a blocklist of write verbs, because the blocklist has an
# unbounded tail (`python -c`, `sed -i`, heredocs, `install`, `dd`) and each miss is
# a silent hole.
READ_ONLY = frozenset(
    [
        "cat",
        "ls",
        "head",
        "tail",
        "grep",
        "rg",
        "find",
        "stat",
        "wc",
        "jq",
        "diff",
        "file",
        "less",
        "more",
        "git",
        "test",
        "echo",
    ]
)

DENY = 2
ALLOW = 0


def _protected(path: str) -> bool:
    normalised = path.replace("\\", "/")
    if normalised.endswith(".env.example"):
        return False
    return any(marker in normalised for marker in PROTECTED)


def _writes_to_verified_zone(command: str) -> bool:
    """Judge each pipeline segment on its own, not the command as a whole.

    The first version asked "does this command mention zones/verified, and is any
    part of it not a read?" -- which denied
    `rm -f .verify-receipt.json && git check-ignore zones/verified/x`, where the
    only segment touching the zone was a read and the only write was elsewhere.
    Found by running into it, which is the argument for keeping the hook narrow:
    an over-broad guard trains people to route around the guard.
    """
    normalised = command.replace("\\", "/")
    if "zones/verified" not in normalised:
        return False

    try:
        segments = _segments(normalised)
    except ValueError:
        # Unbalanced quotes: no reliable parse, so no reliable judgement. The
        # settings.json `deny` rule still covers Edit/Write unconditionally.
        return False

    for tokens in segments:
        if not any("zones/verified" in token for token in tokens):
            continue
        # Where a redirect POINTS, not merely that one exists. `cat zones/verified/x
        # 2>/dev/null` sends stderr to /dev/null and writes nothing.
        for index, token in enumerate(tokens):
            redirects = token in (">", ">>") and index + 1 < len(tokens)
            if redirects and "zones/verified" in tokens[index + 1]:
                return True
        if tokens[0] not in READ_ONLY:
            return True
    return False


def _segments(command: str) -> list[list[str]]:
    """Split a command into pipeline segments of shell tokens, respecting quotes.

    `str.split()` on `|` and `;` is wrong in a way that matters: it breaks
    `jq '.a|join(",")' file` into fragments whose first token is `join(","))"'`,
    which is in no whitelist, so a read gets denied. Three legitimate commands were
    refused that way before this used a real lexer.

    `punctuation_chars=True` makes shlex emit `|`, `;`, `&&`, `>` as their own
    tokens while leaving quoted strings intact.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True

    segments: list[list[str]] = [[]]
    for token in lexer:
        if token in (";", "|", "||", "&&", "&"):
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tool_input = payload.get("tool_input") or {}

        path = tool_input.get("file_path")
        if isinstance(path, str) and _protected(path):
            print(
                f"BLOCKED: {path} is protected. Agents may not write secrets, keys, "
                "or zones/verified/ -- that zone records what the gate actually ran, "
                "so a hand-written entry is a forged result. Write your claim to "
                "zones/claimed/ and run ./scripts/verify.sh instead.",
                file=sys.stderr,
            )
            return DENY

        command = tool_input.get("command")
        if isinstance(command, str) and _writes_to_verified_zone(command):
            print(
                "BLOCKED: that command writes into zones/verified/, which only "
                "./scripts/verify.sh may populate -- writing it requires having run "
                "the checks. Reading it is fine.",
                file=sys.stderr,
            )
            return DENY

    # A guard that crashed has no basis to deny, and bricking every tool call in
    # the repo is far worse than the gap it was closing. Fail open, always.
    except Exception:
        return ALLOW

    return ALLOW


if __name__ == "__main__":
    sys.exit(main())
