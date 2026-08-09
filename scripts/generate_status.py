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
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = ROOT / "STATUS.md"

# (label, interpreter, test path). One venv now runs all three; before the
# monorepo migration each package had its own and only Node's could import both.
SUITES: list[tuple[str, Path, Path]] = [
    ("Scheduler", ROOT / ".venv/bin/python", ROOT / "packages/scheduler/tests"),
    ("Node", ROOT / ".venv/bin/python", ROOT / "packages/node/tests"),
    ("Root E2E", ROOT / ".venv/bin/python", ROOT / "tests"),
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
            (
                "no git remote configured on the root repo -- CI has nowhere to run, "
                "so no run history can exist"
            ),
        )

    if shutil.which("gh") is None:
        return "UNVERIFIABLE", "gh CLI not installed -- cannot query run history"

    code, out = run(["gh", "run", "list", "--limit", "20", "--json", "conclusion,headSha"])
    if code != 0:
        return "UNVERIFIABLE", f"gh run list failed: {out[:160]}"
    if not out.strip() or out.strip() == "[]":
        return "UNVERIFIABLE", "gh returned no runs for this repo"

    try:
        runs = json.loads(out)
    except json.JSONDecodeError:
        return "UNVERIFIABLE", f"could not parse gh output: {out[:160]}"

    # THE COMMIT MATTERS, NOT THE RECENCY.
    #
    # This used to report the latest run's conclusion as this repo's CI status,
    # regardless of which commit that run covered. On 2026-08-09 that printed
    # "CI: PASS" while HEAD was EIGHT COMMITS ahead of anything CI had ever seen --
    # a green badge for code that had never been built.
    #
    # It is the same failure this file exists to prevent, inside the file itself:
    # a measurement presented as current that describes a moment that has passed.
    # CLAUDE.md records a session reporting "CI unverifiable" for a change whose CI
    # run had already failed; this is that error with the sign flipped.
    hcode, head = run(["git", "rev-parse", "HEAD"])
    head = head.strip()
    if hcode != 0 or not head:
        return "UNVERIFIABLE", "could not resolve HEAD to compare against run history"

    for entry in runs:
        if entry.get("headSha") == head:
            if entry.get("conclusion") == "success":
                return "PASS", f"run for HEAD ({head[:8]}) concluded success"
            return "FAIL", f"run for HEAD ({head[:8]}) concluded {entry.get('conclusion')!r}"

    latest = runs[0]
    behind = "unknown"
    bcode, count = run(["git", "rev-list", "--count", f"{latest.get('headSha')}..HEAD"])
    if bcode == 0 and count.strip():
        behind = count.strip()
    return (
        "UNVERIFIED",
        (
            f"CI has never run for HEAD ({head[:8]}). The most recent run covers "
            f"{str(latest.get('headSha'))[:8]}, which is {behind} commit(s) behind. "
            f"Its conclusion ({latest.get('conclusion')!r}) says nothing about this code."
        ),
    )


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
            ccode, subject = run(["git", "-C", path, "log", "-1", "--pretty=%s"], timeout=30)
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
        (
            f"| **Total** | **{overall}** | **{total_passed}** | **{total_failed}** "
            f"| **{total_skipped}** | |"
        ),
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
        lines += [
            "",
            "## Submodules",
            "",
            "| Path | Pinned | Subject |",
            "| --- | --- | --- |",
        ]
        lines += [f"| {p} | `{s}` | {msg[:60]} |" for p, s, msg in submodules]
        gitmodules = ROOT / ".gitmodules"
        if not gitmodules.exists():
            lines += [
                "",
                (
                    "> **`.gitmodules` is missing.** These gitlinks are tracked but "
                    "have no config to resolve them, so a fresh clone (and CI "
                    "checkout) gets empty directories."
                ),
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

    lines += repo_facts_section()

    lines += [
        "---",
        "",
        (
            "Generated by `scripts/generate_status.py` as step 6 of `VERIFY.md`. "
            "If a number here looks wrong, fix the script or the code — not this file."
        ),
        "",
    ]

    return "\n".join(lines)


def repo_facts_section() -> list[str]:
    """Measure the facts that used to be hand-written prose in CLAUDE.md.

    That section asserted, under a heading meaning "trust this without checking",
    that the root repo had no remote, that `.gitmodules` did not exist, and that CI
    had never run. All were false, and one session repeated them in a completion
    report rather than spending a command. Prose cannot notice when it goes stale.
    These are measured on every run instead.
    """
    lines = ["", "## Repo facts", "", "_Measured, not asserted. Re-run to refresh._", ""]

    # --- remotes ---
    lines += ["| Repo | Remote | Branch | Tracking |", "| --- | --- | --- | --- |"]
    for name, path in [
        ("root", ROOT),
    ]:
        if not (path / ".git").exists():
            lines.append(f"| {name} | (not a git repo) | - | - |")
            continue
        _, remote = run(["git", "remote", "get-url", "origin"], cwd=path)
        _, branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
        code, upstream = run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=path
        )
        remote = remote.strip() or "**NONE**"
        tracking = upstream.strip() if code == 0 else "**none**"
        lines.append(f"| {name} | `{remote}` | {branch.strip()} | {tracking} |")
    lines.append("")

    # --- .gitmodules ---
    # The polarity here was INVERTED and stayed that way after the monorepo
    # migration. Absent `.gitmodules` used to mean a broken clone; since 2026-08-04
    # the packages are ordinary directories, and its absence is the CORRECT state --
    # `.github/workflows/ci.yml`'s fresh-clone job explicitly fails if the file comes
    # back. STATUS.md was reporting the right configuration as a defect.
    gm = ROOT / ".gitmodules"
    if gm.exists():
        code, out = run(["git", "config", "-f", str(gm), "--get-regexp", r"submodule\..*\.path"])
        mapped = sorted(line.split()[-1] for line in out.splitlines() if line.strip())
        lines.append(
            f"- **`.gitmodules`:** **PRESENT and it should not be** — maps "
            f"{', '.join(mapped) or '(nothing)'}. The packages are ordinary "
            f"directories since the monorepo migration; CI's fresh-clone job fails "
            f"when this file exists."
        )
    else:
        lines.append(
            "- **`.gitmodules`:** absent, which is correct — `packages/` are ordinary "
            "directories since the 2026-08-04 monorepo migration, and CI's "
            "fresh-clone job asserts this file does not come back."
        )

    # --- interpreters and pinned tools ---
    node_py = ROOT / ".venv/bin/python"
    for label, py in [("root", node_py)]:
        if py.exists():
            _, ver = run([str(py), "-V"])
            lines.append(f"- **{label} venv interpreter:** {ver.strip()}")
    _, ruff_v = run([str(node_py), "-m", "ruff", "--version"])
    if ruff_v.strip():
        lines.append(f"- **ruff:** {ruff_v.strip()} (pinned in both pyproject `[dev]` extras)")

    # --- duplicate-module drift ---
    # Shipping pairs only. quantization / kv_cache / local_boundary / transport moved
    # to experimental/ under ROADMAP C2 and autonomous_orchestrator was deleted under
    # 2.10, so a table listing them here would report drift for code that is either
    # not shipped or not present. tests/test_source_parity.py still ratchets the
    # experimental copies -- measurement continues, it just stopped being reported as
    # if it described the product.
    # The SHIPPED tree has no duplicated pairs left (ROADMAP C8): mesh_protocol and
    # mesh_auth moved to packages/shared, and there is one copy. What remains
    # duplicated lives in experimental/, is not shipped, and is ratcheted by
    # tests/test_source_parity.py -- reported here so "no drift" cannot be read as
    # "no duplication anywhere".
    pairs = [
        (
            "quantization (experimental)",
            "experimental/node/quantization.py",
            "experimental/scheduler/quantization.py",
        ),
        (
            "kv_cache (experimental)",
            "experimental/node/kv_cache.py",
            "experimental/scheduler/kv_cache.py",
        ),
        (
            "local_boundary (experimental)",
            "experimental/node/local_boundary.py",
            "experimental/scheduler/local_boundary.py",
        ),
        (
            "transport (experimental)",
            "experimental/node/transport.py",
            "experimental/scheduler/transport.py",
        ),
    ]
    drift_rows = []
    for name, left, right in pairs:
        a, b = ROOT / left, ROOT / right
        if not (a.exists() and b.exists()):
            continue
        drift_rows.append(f"| {name} | {_significant_drift(a, b)} |")
    if drift_rows:
        lines += [
            "",
            "**Duplicated modules** (differing significant lines; imports and comments excluded).",
            "Ratcheted by `tests/test_source_parity.py` — these may not increase.",
            "",
            "| Pair | Drift |",
            "| --- | --- |",
            *drift_rows,
        ]

    lines.append("")
    return lines


def _significant_drift(a: Path, b: Path) -> int:
    """Differing meaningful lines between two copies of a module."""
    import difflib

    def sig(p: Path) -> list[str]:
        out = []
        # Explicit encoding: this file reads source from packages/, and
        # `read_text()` with no encoding resolves to the platform default -- UTF-8
        # here, cp1252 on a Windows runner. One non-ASCII byte in a scanned module
        # is all it takes. ROADMAP 2.9 enabled ruff's PLW1514 for exactly this and
        # pointed it at packages/ and tests/; scripts/ was still outside the gate,
        # so this violation survived in the script that GENERATES the status file.
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "import ", "from ")):
                continue
            out.append(line)
        return out

    diff = difflib.unified_diff(sig(a), sig(b), lineterm="", n=0)
    return sum(1 for ln in diff if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")))


def main() -> int:
    """Collect signals and write STATUS.md."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout", action="store_true", help="print to stdout instead of writing")
    args = parser.parse_args()

    print("Collecting real signals (this runs the test suites)...", file=sys.stderr)

    results = []
    for name, python, tests in SUITES:
        print(f"  running {name}...", file=sys.stderr)
        result = run_suite(name, python, tests)
        print(
            f"    {result.status} {result.passed}p/{result.failed + result.errors}f",
            file=sys.stderr,
        )
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
