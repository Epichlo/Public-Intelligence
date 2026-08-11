"""The governance layer that stops an agent certifying its own work.

`CLAUDE.md`, `VERIFY.md` and the two skills all say "do not mark your own work
verified". They are instructions to a probabilistic model, and this repo has the
receipts for what that is worth: `VERIFY.md`'s verdict block records a session that
found "four security holes and two false statements *in my own work from earlier in
the same session*".

`.claude/hooks/` is the deterministic layer underneath those instructions. It runs as
an OS process on every tool call and every stop, whether or not the model cooperates.
This file is what stops the enforcement layer from being decorative -- a hook that
exits 0 on everything looks identical to a working one from the outside.

See `specs/the-agent-cannot-certify-itself.md` and
`docs/CLAUDE_CODE_ARCHITECTURE.md` (Pillars 1-3).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_DIR = REPO_ROOT / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"

BLOCK_HOOK = HOOKS_DIR / "block-protected-paths.py"
STOP_HOOK = HOOKS_DIR / "require-proof-stop.py"
SESSION_HOOK = HOOKS_DIR / "sessionstart-context.py"

# Exit code 2 is the only signal a PreToolUse hook has for "deny this tool call".
# Any other non-zero is a hook crash, which the runtime treats as non-blocking.
DENY = 2
ALLOW = 0


def _run_hook(
    hook: Path, payload: dict[str, object], cwd: Path | None = None
) -> tuple[int, str, str]:
    """Feed a hook real JSON on stdin, the way the runtime does.

    The existence check is load-bearing, not defensive. `python missing-file.py` exits
    2, which is also the deny code -- so with no hook on disk every "this is blocked"
    assertion passed for the wrong reason. Thirteen of these tests were green before a
    line of the implementation existed. An assertion that cannot fail proves nothing.
    """
    assert hook.exists(), f"{hook.relative_to(REPO_ROOT)} does not exist"
    proc = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# Pillar 1 -- the governance files exist and say what they must
# ---------------------------------------------------------------------------


def test_settings_declares_plan_mode_and_denies_the_protected_paths() -> None:
    """Permission arrays are evaluated deny -> ask -> allow, and deny is absolute.

    A `deny` entry cannot be overridden by any later allow, by any scope that merges
    on top, or by `bypassPermissions`. That makes the deny array -- not the hook --
    the load-bearing half of the protection, so it is checked first.
    """
    settings = json.loads((CLAUDE_DIR / "settings.json").read_text(encoding="utf-8"))
    permissions = settings["permissions"]

    assert permissions["defaultMode"] == "plan", (
        "defaultMode must be 'plan' so a session starts read-only (Pillar 2)."
    )

    deny = " ".join(permissions["deny"])
    for pattern in ("zones/verified", ".env", "secrets/", ".pem"):
        assert pattern in deny, f"{pattern!r} is not denied in .claude/settings.json"


def test_settings_registers_both_enforcement_hooks() -> None:
    """A hook file nobody calls is a file, not an enforcement layer."""
    settings = json.loads((CLAUDE_DIR / "settings.json").read_text(encoding="utf-8"))
    registered = json.dumps(settings["hooks"])

    assert "block-protected-paths.py" in registered, "PreToolUse hook is not registered"
    assert "require-proof-stop.py" in registered, "Stop hook is not registered"
    assert "sessionstart-context.py" in registered, "SessionStart hook is not registered"


@pytest.mark.parametrize(
    "rule",
    ["verification.md", "security.md", "scheduler.md", "node.md", "website.md"],
)
def test_the_rules_files_exist(rule: str) -> None:
    assert (CLAUDE_DIR / "rules" / rule).exists(), f".claude/rules/{rule} is missing"


@pytest.mark.parametrize(
    ("rule", "glob"),
    [
        ("scheduler.md", "packages/scheduler/**"),
        ("node.md", "packages/node/**"),
        ("website.md", "packages/website/**"),
    ],
)
def test_package_rules_are_scoped_to_their_package(rule: str, glob: str) -> None:
    """A path-scoped rule loads only for matching files.

    Without the `paths:` frontmatter the rule loads unconditionally, which spends
    context on every session and puts scheduler rules in front of an agent editing
    the website. The blueprint's ~150-instruction ceiling is the reason this matters.
    """
    text = (CLAUDE_DIR / "rules" / rule).read_text(encoding="utf-8")
    assert text.startswith("---"), f"{rule} has no frontmatter block"
    frontmatter = text.split("---")[1]
    assert "paths:" in frontmatter, f"{rule} has no `paths:` frontmatter key"
    assert glob in frontmatter, f"{rule} is not scoped to {glob}"


def test_the_verification_rule_is_reachable_from_claude_md() -> None:
    """`.claude/rules/` auto-loading is asserted by the architecture doc, not verified.

    If the installed build does not load `rules/*.md`, the anti-self-certification
    rule silently becomes inert markdown. CLAUDE.md certainly loads, so it carries a
    pointer -- belt and braces for the one rule that must not go missing.
    """
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert ".claude/rules/" in claude_md, (
        "CLAUDE.md does not point at .claude/rules/, so the verification rule "
        "depends entirely on an unverified auto-load mechanism."
    )


# ---------------------------------------------------------------------------
# Pillar 2 -- the subagents, and the separation that makes verification independent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent", ["explorer.md", "planner.md", "implementer.md", "independent-verifier.md"]
)
def test_the_agent_files_exist(agent: str) -> None:
    assert (CLAUDE_DIR / "agents" / agent).exists(), f".claude/agents/{agent} is missing"


def test_the_verifier_cannot_edit_what_it_verifies() -> None:
    """This is the whole point of the subagent split.

    A verifier that can edit source can fix its own verification target, and an agent
    that fixes the thing it is judging is not independent. `isolation: worktree` is
    the other half: it reads a checkout the implementing session cannot have dirtied.
    """
    text = (CLAUDE_DIR / "agents" / "independent-verifier.md").read_text(encoding="utf-8")
    frontmatter = text.split("---")[1]

    assert "isolation: worktree" in frontmatter, "independent-verifier must run in its own worktree"
    disallowed = [line for line in frontmatter.splitlines() if "disallowedTools" in line]
    assert disallowed, "independent-verifier does not declare disallowedTools"
    assert "Write" in disallowed[0] and "Edit" in disallowed[0], (
        f"independent-verifier must deny Write and Edit, got: {disallowed[0]!r}"
    )


def test_the_implementer_is_told_it_may_not_declare_victory() -> None:
    text = (CLAUDE_DIR / "agents" / "implementer.md").read_text(encoding="utf-8")
    assert "zones/verified" in text, "implementer.md must name the zone it is forbidden to write"


# ---------------------------------------------------------------------------
# Pillar 3 -- the PreToolUse hook
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "zones/verified/DEC-014.verified.json",
        "zones/verified/latest.verified.json",
        ".env",
        ".env.local",
        "secrets/signing.key",
        "packages/scheduler/keys/private.pem",
    ],
)
def test_protected_paths_are_denied(path: str) -> None:
    code, _out, err = _run_hook(BLOCK_HOOK, {"tool_input": {"file_path": path}})
    assert code == DENY, f"writing {path} was allowed (exit {code})"
    assert err.strip(), "a denial must explain itself on stderr -- that text is fed back"


@pytest.mark.parametrize(
    "path",
    [
        "packages/node/src/node/runtime.py",
        "zones/claimed/task.claim.json",
        "specs/some-feature.md",
        "ROADMAP.md",
    ],
)
def test_ordinary_source_paths_are_allowed(path: str) -> None:
    """Anthropic's guidance is explicit that blocking ordinary edits breaks planning.

    The hook guards secrets and the verified zone. Quality enforcement belongs at the
    Stop hook and in CI, not in the middle of a multi-step edit.
    """
    code, _out, _err = _run_hook(BLOCK_HOOK, {"tool_input": {"file_path": path}})
    assert code == ALLOW, f"writing {path} was blocked (exit {code})"


@pytest.mark.parametrize(
    "command",
    [
        "echo '{}' > zones/verified/latest.verified.json",
        "cat x >> zones/verified/forged.json",
        "cp /tmp/x zones/verified/y.json",
        "tee zones/verified/z.json",
    ],
)
def test_shell_redirection_into_the_verified_zone_is_denied(command: str) -> None:
    """A path guard that only reads `file_path` is bypassed by `echo >`.

    The blueprint's hook checks Edit/Write only. Leaving Bash unguarded would make
    the verified zone writable by the one tool every agent already has.
    """
    code, _out, err = _run_hook(BLOCK_HOOK, {"tool_input": {"command": command}})
    assert code == DENY, f"`{command}` was allowed (exit {code})"
    assert err.strip(), "a denial must explain itself on stderr"


@pytest.mark.parametrize(
    "command",
    [
        "./scripts/verify.sh",
        "git status --porcelain",
        "cat zones/verified/latest.verified.json",
        "ls zones/verified/",
    ],
)
def test_reading_the_verified_zone_is_allowed(command: str) -> None:
    """Reading the evidence is how an agent learns it has none. Only writes are denied."""
    code, _out, _err = _run_hook(BLOCK_HOOK, {"tool_input": {"command": command}})
    assert code == ALLOW, f"`{command}` was blocked (exit {code})"


@pytest.mark.parametrize(
    "command",
    [
        "rm -f .verify-receipt.json && git check-ignore -q zones/verified/x.json",
        "echo hi > /tmp/note && cat zones/verified/latest.verified.json",
        "mkdir -p zones/claimed && ls zones/verified/",
        "cat zones/verified/latest.verified.json 2>/dev/null",
        "grep -c step zones/verified/latest.verified.json 2>/dev/null | head -1",
        # A pipe INSIDE a quoted argument is not a shell pipe. Splitting the raw
        # string on "|" turned this into a fragment starting `join(","))"'`, which
        # is in no whitelist, so reading the evidence was denied.
        "jq -r '.skipped|join(\",\")' zones/verified/latest.verified.json",
        "jq -r '.steps[] | select(.result != \"pass\")' zones/verified/latest.verified.json",
    ],
)
def test_a_write_elsewhere_does_not_condemn_a_read_of_the_zone(command: str) -> None:
    """Regression: the guard judged the whole command, not the segment that matters.

    Every one of these writes somewhere harmless and only *reads* the verified zone.
    The first version denied them all, because it asked "is zones/verified mentioned,
    and is any part of this not a read?". Caught by running into it while cleaning up
    the artifact this change replaces.

    An over-broad guard is not a safe default -- it trains people to route around the
    guard, and a guard people route around protects nothing.
    """
    code, _out, err = _run_hook(BLOCK_HOOK, {"tool_input": {"command": command}})
    assert code == ALLOW, f"`{command}` was blocked (exit {code}): {err.strip()}"


def test_the_block_hook_fails_open_on_malformed_input() -> None:
    """A crashing enforcer must degrade to the status quo, not brick every tool call."""
    proc = subprocess.run(
        [sys.executable, str(BLOCK_HOOK)],
        input="this is not json",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == ALLOW, (
        f"malformed stdin produced exit {proc.returncode}; a hook that cannot parse "
        "its input must not block the tool call"
    )


# ---------------------------------------------------------------------------
# Pillar 3 -- the Stop hook, against a real throwaway git repository
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A real git repo, because the hook's whole job is reading real git state."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    # `zones/` is gitignored here for the same reason it is in the real repo, and the
    # test does not work without it: the fingerprint counts untracked non-ignored
    # files, so an un-ignored bundle would invalidate itself the instant it landed.
    (repo / ".gitignore").write_text("zones/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    (repo / "zones" / "verified").mkdir(parents=True)
    (repo / "zones" / "claimed").mkdir(parents=True)
    return repo


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def _fingerprint(repo: Path) -> str:
    """Ask the one implementation, so the test cannot drift from the hook."""
    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "state_fingerprint.py")],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _write_bundle(repo: Path, **overrides: object) -> None:
    bundle: dict[str, object] = {
        "verdict": "pass",
        "commit": _head(repo),
        "state_fingerprint": _fingerprint(repo),
        "skipped": [],
        "steps": [{"step": "pytest", "result": "pass"}],
    }
    bundle.update(overrides)
    (repo / "zones" / "verified" / "latest.verified.json").write_text(
        json.dumps(bundle), encoding="utf-8"
    )


def _blocked(stdout: str) -> bool:
    if not stdout.strip():
        return False
    return json.loads(stdout).get("decision") == "block"


def test_a_clean_tree_with_no_changes_is_allowed_to_stop(sandbox: Path) -> None:
    """A session that answered a question must not be wedged.

    This is the failure mode the architecture doc warns about by name: a Stop hook
    that always blocks creates a loop. Nothing changed, so there is nothing to prove.
    """
    code, out, _err = _run_hook(STOP_HOOK, {"stop_hook_active": False}, cwd=sandbox)
    assert code == ALLOW
    assert not _blocked(out), f"a no-op session was blocked: {out}"


def test_uncommitted_code_with_no_evidence_is_blocked(sandbox: Path) -> None:
    (sandbox / "code.py").write_text("x = 2\n", encoding="utf-8")
    code, out, _err = _run_hook(STOP_HOOK, {"stop_hook_active": False}, cwd=sandbox)
    assert code == ALLOW, "the hook signals via stdout JSON, not via its exit code"
    assert _blocked(out), "changed code with no evidence bundle was allowed to stop"


def test_matching_passing_evidence_is_allowed(sandbox: Path) -> None:
    (sandbox / "code.py").write_text("x = 2\n", encoding="utf-8")
    _write_bundle(sandbox)
    _code, out, _err = _run_hook(STOP_HOOK, {"stop_hook_active": False}, cwd=sandbox)
    assert not _blocked(out), f"valid current evidence was rejected: {out}"


def test_a_failing_bundle_is_blocked(sandbox: Path) -> None:
    (sandbox / "code.py").write_text("x = 2\n", encoding="utf-8")
    _write_bundle(sandbox, verdict="FAIL", steps=[{"step": "pytest", "result": "FAIL"}])
    _code, out, _err = _run_hook(STOP_HOOK, {"stop_hook_active": False}, cwd=sandbox)
    assert _blocked(out), "a FAIL bundle was treated as proof of success"
    assert "pytest" in out, "the block reason must name what failed"


def test_evidence_goes_stale_the_moment_the_code_changes(sandbox: Path) -> None:
    """The blueprint's newest-by-mtime lookup passes here. That is the bug.

    Run the gate, then edit one line, then stop: the bundle is still the newest file
    on disk and still says PASS, about code that no longer exists. Binding the bundle
    to a fingerprint of the tree is what makes 'it passed' mean 'this passed'.
    """
    (sandbox / "code.py").write_text("x = 2\n", encoding="utf-8")
    _write_bundle(sandbox)
    (sandbox / "code.py").write_text("x = 3  # edited after the gate ran\n", encoding="utf-8")

    _code, out, _err = _run_hook(STOP_HOOK, {"stop_hook_active": False}, cwd=sandbox)
    assert _blocked(out), "evidence from before the edit was accepted after it"


def test_an_untracked_file_invalidates_the_evidence(sandbox: Path) -> None:
    """`git diff HEAD` does not see untracked files, so a fingerprint over the diff
    alone would let a whole new module land after the gate ran."""
    (sandbox / "code.py").write_text("x = 2\n", encoding="utf-8")
    _write_bundle(sandbox)
    (sandbox / "sneaked_in.py").write_text("import os\n", encoding="utf-8")

    _code, out, _err = _run_hook(STOP_HOOK, {"stop_hook_active": False}, cwd=sandbox)
    assert _blocked(out), "a new untracked file did not invalidate the evidence"


def test_committing_the_work_does_not_launder_it(sandbox: Path) -> None:
    """The clean-tree shortcut must not become the bypass.

    Write code, commit it, stop. The tree is clean, so a dirty-tree proxy alone would
    wave this through. The SessionStart baseline is what closes it.
    """
    baseline_head = _head(sandbox)
    (sandbox / "zones" / "claimed").mkdir(parents=True, exist_ok=True)
    (sandbox / "zones" / "claimed" / "session-abc.json").write_text(
        json.dumps({"head": baseline_head}), encoding="utf-8"
    )

    (sandbox / "code.py").write_text("x = 2\n", encoding="utf-8")
    _git(sandbox, "add", "-A")
    _git(sandbox, "commit", "-q", "-m", "work")

    _code, out, _err = _run_hook(
        STOP_HOOK, {"stop_hook_active": False, "session_id": "abc"}, cwd=sandbox
    )
    assert _blocked(out), "committing the change was accepted as a substitute for verifying it"


def test_stop_hook_active_short_circuits(sandbox: Path) -> None:
    """Mandatory guard. Without it a single failing state loops until the block cap."""
    (sandbox / "code.py").write_text("x = 2\n", encoding="utf-8")
    _code, out, _err = _run_hook(STOP_HOOK, {"stop_hook_active": True}, cwd=sandbox)
    assert not _blocked(out), "stop_hook_active did not short-circuit the check"


def test_the_stop_hook_emits_no_hook_specific_output(sandbox: Path) -> None:
    """A Stop hook's `hookEventName` enum excludes Stop.

    Attaching `hookSpecificOutput` makes the runtime discard the entire payload --
    the block silently becomes an allow, which is the worst possible failure for
    this hook because it looks like it is working.
    """
    (sandbox / "code.py").write_text("x = 2\n", encoding="utf-8")
    _code, out, _err = _run_hook(STOP_HOOK, {"stop_hook_active": False}, cwd=sandbox)
    assert "hookSpecificOutput" not in out, (
        "hookSpecificOutput on a Stop hook causes the runtime to discard the block"
    )


def test_the_stop_hook_fails_open_outside_a_git_repository(tmp_path: Path) -> None:
    """No git, no fingerprint, no basis to block. Degrade to the status quo."""
    _code, out, _err = _run_hook(STOP_HOOK, {"stop_hook_active": False}, cwd=tmp_path)
    assert not _blocked(out), "the hook blocked where it could not compute an answer"


def test_the_stop_hook_fails_open_on_malformed_input() -> None:
    proc = subprocess.run(
        [sys.executable, str(STOP_HOOK)],
        input="not json at all",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == ALLOW
    assert not _blocked(proc.stdout)


# ---------------------------------------------------------------------------
# The gate writes the evidence, because writing it requires having run the checks
# ---------------------------------------------------------------------------


def test_the_gate_writes_the_evidence_bundle() -> None:
    script = (REPO_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    assert "zones/verified/latest.verified.json" in script, (
        "scripts/verify.sh does not write the evidence bundle the Stop hook reads"
    )
    assert "state_fingerprint" in script, (
        "the bundle must carry a fingerprint or it cannot be checked for staleness"
    )


def test_there_is_only_one_evidence_artifact() -> None:
    """Two files recording the same verdict is the 'two lists' failure in miniature.

    `.verify-receipt.json` was the old name. It is replaced, not supplemented -- a
    stale second artifact is exactly what a future session would read as current.

    Matched on USE rather than mention, the same distinction
    `test_the_fleet_wide_secret_is_no_longer_used_anywhere` draws: the comment
    explaining what the old artifact was gets to keep its explanation.
    """
    script = (REPO_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    assert 'verify-receipt.json"' not in script.replace("zones/verified", ""), (
        "scripts/verify.sh still redirects into the superseded .verify-receipt.json"
    )
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert ".verify-receipt.json" not in claude_md, (
        "CLAUDE.md still documents the superseded receipt path as current"
    )


def test_the_gate_lints_its_own_enforcement_code() -> None:
    """`.claude/hooks/` decides whether work may complete. It does not get to be exempt.

    The ratchet in test_source_parity.py skipped dotted directories, so this code
    would have sat outside the gate while appearing to be inside it -- the pattern
    that has now bitten this repo three times.
    """
    script = (REPO_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    assert "./.claude" in script, "scripts/verify.sh does not lint .claude/"
