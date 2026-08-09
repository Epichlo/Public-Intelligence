"""`STATUS.md` must not report CI green for a commit CI has never seen.

Found during the VERIFY step 6 pass on 2026-08-09. `scripts/generate_status.py` read
the **most recent** workflow run and printed its conclusion as this repo's CI status,
with no reference to which commit that run covered. It printed **"CI: PASS"** while
HEAD was nine commits ahead of anything CI had ever built.

That is the failure this whole file-generation approach exists to prevent, occurring
inside the generator: a measurement presented as current that describes a moment
which has passed. `CLAUDE.md` records the mirror-image mistake -- a session reporting
"CI unverifiable" for a change whose CI run had already failed -- and draws the
conclusion that prose cannot notice when it goes stale. Neither can a generated file,
if what it generates is the wrong question's answer.

The fix is that the run must be matched to HEAD. These tests pin all three outcomes,
because a function that could only ever return UNVERIFIED would satisfy the headline
case and be useless.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_generator() -> Any:
    path = REPO_ROOT / "scripts" / "generate_status.py"
    spec = importlib.util.spec_from_file_location("generate_status", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_status"] = module
    spec.loader.exec_module(module)
    return module


generate_status = _load_generator()

HEAD = "a" * 40
OLDER = "b" * 40


def _fake_run(runs: list[dict[str, str]], behind: str = "9"):
    """Stand in for the module's `run()` shell helper."""

    def _run(cmd: list[str], **kwargs: Any) -> tuple[int, str]:
        if cmd[:3] == ["gh", "run", "list"]:
            return 0, json.dumps(runs)
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, HEAD
        if cmd[:3] == ["git", "rev-list", "--count"]:
            return 0, behind
        if cmd[:2] == ["git", "remote"]:
            return 0, "origin\thttps://example.invalid/repo.git (fetch)"
        return 0, ""

    return _run


def test_a_successful_run_for_head_is_reported_as_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        generate_status, "run", _fake_run([{"headSha": HEAD, "conclusion": "success"}])
    )
    monkeypatch.setattr(generate_status.shutil, "which", lambda _: "/usr/bin/gh")

    status, reason = generate_status.ci_signal()

    assert status == "PASS"
    assert HEAD[:8] in reason


def test_a_failed_run_for_head_is_reported_as_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        generate_status, "run", _fake_run([{"headSha": HEAD, "conclusion": "failure"}])
    )
    monkeypatch.setattr(generate_status.shutil, "which", lambda _: "/usr/bin/gh")

    status, _ = generate_status.ci_signal()

    assert status == "FAIL"


def test_a_green_run_for_an_older_commit_is_not_reported_as_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual bug. A green badge for code CI has never built.

    UNVERIFIED, not PASS and not FAIL: CI has said nothing about this commit, and
    both of the other answers would be inventing one.
    """
    monkeypatch.setattr(
        generate_status, "run", _fake_run([{"headSha": OLDER, "conclusion": "success"}])
    )
    monkeypatch.setattr(generate_status.shutil, "which", lambda _: "/usr/bin/gh")

    status, reason = generate_status.ci_signal()

    assert status == "UNVERIFIED"
    assert "never run for HEAD" in reason
    # The distance matters: "one commit behind" and "nine commits behind" are very
    # different amounts of unverified change, and the reader should not have to go
    # and measure it.
    assert "9 commit(s) behind" in reason


def test_the_status_file_does_not_claim_ci_passed_for_an_unbuilt_head() -> None:
    """The generated artefact itself, as committed.

    Reading the file rather than the function, because the function being right does
    not help if the checked-in STATUS.md was generated before the fix.
    """
    status_md = (REPO_ROOT / "STATUS.md").read_text(encoding="utf-8")
    ci_block = status_md.split("## CI", 1)[1].split("##", 1)[0]

    if "**Status:** PASS" in ci_block:
        assert "run for HEAD" in ci_block, (
            "STATUS.md claims CI passed without naming the commit that run covered."
        )
