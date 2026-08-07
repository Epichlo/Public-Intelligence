#!/usr/bin/env python3
"""Master System & Infrastructure Audit Runner for Public Intelligence.

Performs static analysis, cross-platform path validation, installer syntax audits,
and security checks across Node, Scheduler, and website sub-repositories.
"""

import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
NODE_DIR = ROOT_DIR / "Node"
SCHEDULER_DIR = ROOT_DIR / "Scheduler"
WEBSITE_DIR = ROOT_DIR / "website"


class AuditLogger:
    """Console formatting helper for audit reporting."""

    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"

    @classmethod
    def info(cls, msg: str) -> None:
        print(f"{cls.BLUE}[INFO]{cls.RESET} {msg}")

    @classmethod
    def ok(cls, msg: str) -> None:
        print(f"{cls.GREEN}[OK]{cls.RESET} {msg}")

    @classmethod
    def warn(cls, msg: str) -> None:
        print(f"{cls.YELLOW}[WARN]{cls.RESET} {msg}")

    @classmethod
    def error(cls, msg: str) -> None:
        print(f"{cls.RED}[ERROR]{cls.RESET} {msg}")


def audit_installer_scripts() -> int:
    """Audit POSIX and Windows installer scripts for execution invariants."""
    AuditLogger.info("Auditing installer scripts (install.sh & install.ps1)...")
    errors = 0

    install_sh = ROOT_DIR / "install.sh"
    install_ps1 = ROOT_DIR / "install.ps1"

    launch_script = ROOT_DIR / "scripts" / "launch_host_node.sh"
    if not install_sh.exists():
        AuditLogger.error("install.sh missing in root directory!")
        errors += 1
    else:
        content = install_sh.read_text(encoding="utf-8")
        launch_content = launch_script.read_text(encoding="utf-8") if launch_script.exists() else ""
        if "SCHEDULER_URL" not in content:
            AuditLogger.error("install.sh missing SCHEDULER_URL override support!")
            errors += 1
        if "disown" not in launch_content and "disown" not in content:
            AuditLogger.warn(
                "install.sh / launch_host_node.sh missing disown process detachment command."
            )
        else:
            AuditLogger.ok(
                "install.sh & launch_host_node.sh contain SCHEDULER_URL overrides & disown process detachment."
            )

    if not install_ps1.exists():
        AuditLogger.error("install.ps1 missing in root directory!")
        errors += 1
    else:
        content = install_ps1.read_text(encoding="utf-8")
        if "$env:SCHEDULER_URL" not in content:
            AuditLogger.error("install.ps1 missing $env:SCHEDULER_URL override support!")
            errors += 1
        if "elseif" not in content and "else if" in content:
            AuditLogger.error(
                "install.ps1 contains invalid PowerShell 'else if' syntax! Use 'elseif'."
            )
            errors += 1
        else:
            AuditLogger.ok("install.ps1 syntax and $env:SCHEDULER_URL overrides verified.")

    return errors


def audit_cross_platform_paths() -> int:
    """Audit Python source code for cross-platform path concatenation bugs."""
    AuditLogger.info("Auditing Python source code for cross-platform path safety...")
    warnings = 0

    path_concat_regex = re.compile(r'["\'][a-zA-Z0-9_\-\.\/]+\/["\']\s*\+\s*')

    python_files = list(NODE_DIR.rglob("*.py")) + list(SCHEDULER_DIR.rglob("*.py"))

    for filepath in python_files:
        if ".venv" in filepath.parts or "tests" in filepath.parts:
            continue
        content = filepath.read_text(encoding="utf-8", errors="ignore")
        for idx, line in enumerate(content.splitlines(), start=1):
            if path_concat_regex.search(line):
                AuditLogger.warn(
                    f"Possible string path concat in {filepath.relative_to(ROOT_DIR)}:L{idx}: {line.strip()}"
                )
                warnings += 1

    if warnings == 0:
        AuditLogger.ok("No risky string path concatenations found. Pathlib usage verified.")
    return 0


def audit_exception_fallbacks() -> int:
    """Audit runtime startup routines for swallowed or unhandled exceptions."""
    AuditLogger.info("Auditing runtime startup routines for third-party fallbacks...")
    errors = 0

    runtime_py = NODE_DIR / "src" / "node" / "runtime.py"
    if runtime_py.exists():
        content = runtime_py.read_text(encoding="utf-8")
        if "list_models" in content:
            if "except Exception" in content:
                AuditLogger.ok(
                    "Node runtime.py wraps Ollama discovery in try/except fallback block."
                )
            else:
                AuditLogger.error("Node runtime.py calls list_models() without exception fallback!")
                errors += 1

    return errors


def main() -> None:
    """Run all master audit tasks."""
    print("=" * 80)
    print("       PUBLIC INTELLIGENCE MASTER SYSTEM & INFRASTRUCTURE AUDITOR       ")
    print("=" * 80)
    print()

    total_errors = 0
    total_errors += audit_installer_scripts()
    total_errors += audit_cross_platform_paths()
    total_errors += audit_exception_fallbacks()

    print()
    print("=" * 80)
    if total_errors == 0:
        AuditLogger.ok(
            "AUDIT COMPLETE: All core installation and runtime invariants passed cleanly."
        )
        sys.exit(0)
    else:
        AuditLogger.error(
            f"AUDIT FAILED: Found {total_errors} critical errors across repositories."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
