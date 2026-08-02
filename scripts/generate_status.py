#!/usr/bin/env python3
"""Regenerate STATUS.md from real signals only.

Every number in STATUS.md comes from a command this script actually ran. Nothing
here is written by hand or by an agent, and nothing is inferred. If a signal
cannot be collected, it is reported as UNKNOWN or UNVERIFIABLE with the reason --
never guessed, never omitted, never defaulted to something reassuring.

Usage:
    python3 scripts/generate_status.py            # regenerate STATUS.md
    python3 scripts/generate_status.py --stdout   # print, don't write

Wired into VERIFY.md step 6.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = ROOT / "STATUS.md"

# (label, interpreter, test path). The root suite is the only one importing both
# `node` and `scheduler`, so it must run under Node's venv -- see VERIFY.md step 1.
SUITES: list[tuple[str, Path, Path]] = [
    ("Scheduler", ROOT / "Scheduler/.venv/bin/python", ROOT / "Scheduler/tests"),
    ("Node", ROOT / "Node/.venv/bin/python", ROOT / "Node/tests"),
    ("Root E2E", ROOT / "Node/.venv/bin/python", ROOT / "tests"),
]

TEST_TIMEOUT_SECONDS = 900


def run(cmd: list[str], cwd: Path = ROOT, timeout: int = 60) -> tuple[int, str]:
    """Run a command, returning (exit_code, combined output).

    Never raises on non-zero exit -- a failing command is a signal to report,
    not an error to hide.
    """
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"


# --------------------------------------------------------------------------
# Test signals
# --------------------------------------------------------------------------


@dataclass
class SuiteResult:
    """Outcome of one pytest run."""

    name: str
    status: str  # PASS | FAIL | NOT RUN
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration: str = ""
    detail: str = ""

    @property
    def total(self) -> int:
        """Assertions that actually executed."""
        return self.passed + self.failed + self.errors


def parse_pytest_summary(output: str) -> dict[str, int | str]:
    """Pull counts out of a pytest summary line.

    Reads the real summary line rather than trusting the exit code alone, so a
    suite that collected zero tests is not silently reported as a pass.
    """
    counts: dict[str, int | str] = {}
    for key in ("passed", "failed", "error", "errors", "skipped"):
        match = re.search(rf"(\d+) {key}\b", output)
        if match:
            normalized = "errors" if key == "error" else key
            counts[normalized] = int(match.group(1))
    duration = re.search(r"in ([\d.]+)s", output)
    if duration:
        counts["duration"] = f"{duration.group(1)}s"
    return counts


def run_suite(name: str, python: Path, tests: Path) -> SuiteResult:
    """Execute one pytest suite and capture its real result."""
    if not python.exists():
        return SuiteResult(name, "NOT RUN", detail=f"interpreter missing: {rel(python)}")
    if not tests.exists():
        return SuiteResult(name, "NOT RUN", detail=f"test path missing: {rel(tests)}")

    code, output = run(
        [str(python), "-m", "pytest", str(tests), "-q"],
        timeout=TEST_TIMEOUT_SECONDS,
    )
    counts = parse_pytest_summary(output)

    if code == 124:
        return SuiteResult(name, "NOT RUN", detail=f"timed out after {TEST_TIMEOUT_SECONDS}s")

    result = SuiteResult(
        name=name,
        status="PASS" if code == 0 else "FAIL",
        passed=int(counts.get("passed", 0)),
        failed=int(counts.get("failed", 0)),
        errors=int(counts.get("errors", 0)),
        skipped=int(counts.get("skipped", 0)),
        duration=str(counts.get("duration", "")),
    )

    # A zero-exit run that collected nothing is not a pass.
    if result.status == "PASS" and result.total == 0:
        result.status = "NOT RUN"
        result.detail = "pytest exited 0 but collected no tests"
    elif result.status == "FAIL":
        tail = [ln for ln in output.splitlines() if ln.strip()][-1:]
        result.detail = tail[0][:200] if tail else f"exit code {code}"

    return result


# --------------------------------------------------------------------------
# Git + CI signals
# --------------------------------------------------------------------------


def git_signals() -> dict[str, str]:
    """Collect commit, branch, remote, and working-tree state."""
    signals: dict[str, str] = {}

    code, out = run(["git", "log", "-1", "--pretty=%h|%s|%an|%ad", "--date=iso"])
    if code == 0 and "|" in out:
        sha, subject, author, date = out.split("|", 3)
        signals |= {
            "commit": sha,
            "subject": subject,
            "author": author,
            "date": date,
        }
    else:
        signals["commit"] = "UNKNOWN"

    code, out = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    signals["branch"] = out if code == 0 else "UNKNOWN"

    code, out = run(["git", "remote", "-v"])
    signals["remote"] = out.splitlines()[0] if (code == 0 and out) else "NONE CONFIGURED"

    code, out = run(["git", "status", "--porcelain"])
    if code == 0:
        dirty = [ln for ln in out.splitlines() if ln.strip()]
        signals["tree"] = "clean" if not dirty else f"{len(dirty)} uncommitted change(s)"
        signals["dirty_detail"] = "\n".join(f"  {ln}" for ln in dirty[:10])
    else:
        signals["tree"] = "UNKNOWN"
        signals["dirty_detail"] = ""

    code, out = run(["git", "rev-list", "--count", "HEAD"])
    signals["commit_count"] = out if code == 0 else "UNKNOWN"

    return signals


def ci_signal() -> tuple[str, str]:
    """Determine real CI status, or why it cannot be determined.

    Returns (status, reason). Never returns a passing status it did not observe.
    """
    workflow = ROOT / ".github/workflows"
    if not workflow.exists() or not any(workflow.iterdir()):
        return "NONE", "no workflow files in .github/workflows"

    code, remote = run(["git", "remote", "-v"])
    if code != 0 or not remote.strip():
        return (
            "UNVERIFIABLE",
            "no git remote configured on the root repo -- CI has nowhere to run, "
            "so no run history can exist",
        )

    if shutil.which("gh") is None:
        return "UNVERIFIABLE", "gh CLI not installed -- cannot query run history"

    code, out = run(["gh", "run", "list", "--limit", "1", "--json", "conclusion,headSha"])
    if code != 0:
        return "UNVERIFIABLE", f"gh run list failed: {out[:160]}"
    if not out.strip() or out.strip() == "[]":
        return "UNVERIFIABLE", "gh returned no runs for this repo"
    if '"conclusion":"success"' in out.replace(" ", ""):
        return "PASS", "latest run concluded success"
    return "FAIL", f"latest run did not succeed: {out[:160]}"


def submodule_signals() -> list[tuple[str, str, str]]:
    """Report each submodule's pinned commit and whether config exists."""
    rows: list[tuple[str, str, str]] = []
    code, out = run(["git", "ls-files", "-s"])
    if code != 0:
        return rows
    for line in out.splitlines():
        if line.startswith("160000"):
            parts = line.split()
            sha, path = parts[1], parts[-1]
            ccode, subject = run(
                ["git", "-C", path, "log", "-1", "--pretty=%s"], timeout=30
            )
            rows.append((path, sha[:8], subject if ccode == 0 else "UNKNOWN"))
    return rows


def rel(path: Path) -> str:
    """Path relative to repo root, for display."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------


def render(results: list[SuiteResult], git: dict[str, str]) -> str:
    """Build STATUS.md from collected signals."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    ci_status, ci_reason = ci_signal()
    submodules = submodule_signals()

    ran = [r for r in results if r.status in ("PASS", "FAIL")]
    total_passed = sum(r.passed for r in ran)
    total_failed = sum(r.failed + r.errors for r in ran)
    total_skipped = sum(r.skipped for r in ran)

    if not ran:
        overall = "UNKNOWN -- no suite ran"
    elif any(r.status == "FAIL" for r in results):
        overall = "FAILING"
    elif any(r.status == "NOT RUN" for r in results):
        overall = "PARTIAL -- some suites did not run"
    else:
        overall = "PASSING"

    lines = [
        "# STATUS",
        "",
        "<!-- GENERATED FILE -- DO NOT EDIT BY HAND. -->",
        "<!-- Regenerate with: python3 scripts/generate_status.py -->",
        "<!-- Every value below came from a command run at the timestamp shown. -->",
        "",
        f"**Generated:** {now}",
        f"**Test status:** {overall}",
        "",
        "## Tests",
        "",
        "| Suite | Status | Passed | Failed | Skipped | Time |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for r in results:
        if r.status == "NOT RUN":
            lines.append(f"| {r.name} | NOT RUN | - | - | - | - |")
        else:
            lines.append(
                f"| {r.name} | {r.status} | {r.passed} | {r.failed + r.errors} "
                f"| {r.skipped} | {r.duration or '-'} |"
            )

    lines += [
        f"| **Total** | **{overall}** | **{total_passed}** | **{total_failed}** "
        f"| **{total_skipped}** | |",
        "",
    ]

    notes = [r for r in results if r.detail]
    if notes:
        lines.append("Notes:")
        lines += [f"- **{r.name}**: {r.detail}" for r in notes]
        lines.append("")

    lines += [
        "Reproduce:",
        "",
        "```bash",
    ]
    for name, python, tests in SUITES:
        lines.append(f"{rel(python)} -m pytest {rel(tests)} -q   # {name}")
    lines += ["```", "", "## Git", ""]

    if git.get("commit") == "UNKNOWN":
        lines.append("- **Last commit:** UNKNOWN (git log failed)")
    else:
        lines += [
            f"- **Last commit:** `{git['commit']}` {git.get('subject', '')}",
            f"- **Author / date:** {git.get('author', '?')} — {git.get('date', '?')}",
        ]
    lines += [
        f"- **Branch:** {git.get('branch', 'UNKNOWN')}",
        f"- **Total commits:** {git.get('commit_count', 'UNKNOWN')}",
        f"- **Remote:** {git.get('remote', 'UNKNOWN')}",
        f"- **Working tree:** {git.get('tree', 'UNKNOWN')}",
    ]
    if git.get("dirty_detail"):
        lines += ["", "```", git["dirty_detail"], "```"]

    if submodules:
        lines += ["", "## Submodules", "", "| Path | Pinned | Subject |", "| --- | --- | --- |"]
        lines += [f"| {p} | `{s}` | {msg[:60]} |" for p, s, msg in submodules]
        gitmodules = ROOT / ".gitmodules"
        if not gitmodules.exists():
            lines += [
                "",
                "> **`.gitmodules` is missing.** These gitlinks are tracked but have no "
                "config to resolve them, so a fresh clone (and CI checkout) gets empty "
                "directories.",
            ]

    lines += [
        "",
        "## CI",
        "",
        f"- **Status:** {ci_status}",
        f"- **Reason:** {ci_reason}",
        "",
    ]
    if ci_status == "UNVERIFIABLE":
        lines.append(
            "> CI status is reported as UNVERIFIABLE rather than assumed. "
            "Do not record a CI pass anywhere until this reads PASS."
        )
        lines.append("")

    lines += [
        "---",
        "",
        "Generated by `scripts/generate_status.py` as step 6 of `VERIFY.md`. "
        "If a number here looks wrong, fix the script or the code — not this file.",
        "",
    ]

    return "\n".join(lines)


def main() -> int:
    """Collect signals and write STATUS.md."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stdout", action="store_true", help="print to stdout instead of writing"
    )
    args = parser.parse_args()

    print("Collecting real signals (this runs the test suites)...", file=sys.stderr)

    results = []
    for name, python, tests in SUITES:
        print(f"  running {name}...", file=sys.stderr)
        result = run_suite(name, python, tests)
        print(f"    {result.status} {result.passed}p/{result.failed + result.errors}f", file=sys.stderr)
        results.append(result)

    content = render(results, git_signals())

    if args.stdout:
        print(content)
    else:
        STATUS_FILE.write_text(content, encoding="utf-8")
        print(f"Wrote {rel(STATUS_FILE)}", file=sys.stderr)

    # Non-zero when a suite actually failed, so this can gate a hook or CI step.
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
