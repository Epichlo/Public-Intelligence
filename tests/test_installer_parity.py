"""The two installers must agree on what a host cannot install without.

On 2026-08-11 a node ran on a second machine for the first time. Four of the six
defects that stood in the way were the same defect: someone updated `install.sh` and
did not update `install.ps1`. The Windows installer could not pass an invite code
(D4 had made it mandatory), installed `packages/node` without `packages/shared`
(C8 had made it a local dependency), reported success over a failed pip, and printed
a run command that could not find the `.env` it had just written.

None of it was caught, and the reason is structural rather than careless:
`scripts/verify_install.sh` runs `install.sh` for real, and **nothing has ever
executed `install.ps1`**. The gate is bash; the Windows CI legs run the same bash
gate. So that file has been outside "the only definition of does this pass" for its
entire life -- the fifth instance of that pattern here, after tests/ (2.9), the
website (C6), scripts/ (C7) and .claude/, and the first one found by a user.

**These are text-level checks and that is a real limitation, stated rather than
implied.** They read both installers and compare what they mention. They cannot
prove `install.ps1` works, because the gate cannot execute PowerShell on Linux. They
can only prove the two files have not drifted apart again on the specific things
that broke. Running the Windows installer for real needs a Windows runner step and
is out of scope -- see specs/what-two-machines-found.md.

See specs/what-two-machines-found.md.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
POSIX = REPO_ROOT / "install.sh"
WINDOWS = REPO_ROOT / "install.ps1"


def _posix() -> str:
    return POSIX.read_text(encoding="utf-8")


def _windows() -> str:
    return WINDOWS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Feature parity: what a host cannot register without
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("posix_flag", "windows_param", "why"),
    [
        (
            "--invite-code",
            "InviteCode",
            "D4 makes an invite the admission mechanism; a Scheduler that has issued "
            "one refuses a node without it, so an installer that cannot pass it "
            "cannot onboard a host at all",
        ),
        (
            "--network-auth-token",
            "NetworkAuthToken",
            "/nodes/register is guarded by verify_auth_token, which compares against "
            "the Scheduler's fleet token. An installer that only GENERATES a random "
            "token produces a node that can never register -- observed as a 401 loop",
        ),
        (
            "--scheduler-url",
            "SchedulerUrl",
            "without it the node defaults to its own localhost and dials itself",
        ),
        (
            "--bootstrap-router",
            "BootstrapRouter",
            "D6/C1 made reaching another machine an explicit decision rather than a hidden default",
        ),
    ],
)
def test_both_installers_accept_the_same_essentials(
    posix_flag: str, windows_param: str, why: str
) -> None:
    assert posix_flag in _posix(), f"install.sh lost {posix_flag}: {why}"
    assert windows_param in _windows(), f"install.ps1 lost -{windows_param}: {why}"


@pytest.mark.parametrize(
    "env_key",
    ["NODE_INVITE_CODE", "NODE_NETWORK_AUTH_TOKEN", "NODE_SCHEDULER_URL", "NODE_BOOTSTRAP_ROUTERS"],
)
def test_both_installers_write_the_same_env_keys(env_key: str) -> None:
    """Accepting a flag and writing it to .env are different things.

    install.ps1 accepted -SchedulerUrl and wrote it; the invite code had neither a
    parameter nor a line, so a host had to append it by hand.
    """
    assert env_key in _posix(), f"install.sh no longer writes {env_key}"
    assert env_key in _windows(), f"install.ps1 no longer writes {env_key}"


def test_windows_installs_shared_before_node() -> None:
    """`public-intelligence-shared` is a local path dependency with no PyPI presence.

    Installing node first makes pip try to resolve the name from an index, find
    nothing, and fail: "No matching distribution found for public-intelligence-shared".
    install.sh has installed both in order since C8; the Windows copy did not.
    """
    text = _windows()
    assert "packages/shared" in text or "packages\\shared" in text or "$SharedDir" in text, (
        "install.ps1 never installs packages/shared, so installing packages/node "
        "cannot resolve public-intelligence-shared (ROADMAP C8)"
    )

    shared_at = max(text.find("$SharedDir"), text.find("packages/shared"), text.find("shared"))
    node_install = text.find("$NodeDir[dev]")
    if node_install != -1:
        assert shared_at < node_install, (
            "install.ps1 installs packages/node before packages/shared; pip cannot "
            "resolve the local dependency in that order"
        )


# ---------------------------------------------------------------------------
# The worst of the six: claiming success over a failure
# ---------------------------------------------------------------------------


def test_windows_installer_checks_native_exit_codes() -> None:
    """PowerShell's $ErrorActionPreference='Stop' does NOT trap native exit codes.

    pip failed, and the script went on to print "Installation Complete! Host Node is
    Ready", launch a daemon that could not import its own package, report it as
    "launched successfully", and exit 0. A tool that fails loudly costs an afternoon;
    one that claims success while failing costs the afternoon plus the time spent
    looking in the wrong place.

    This repo has now shipped that defect three times in three languages -- the
    orchestrator returning verification_passed=True for a stub (2.10), /v1/batch
    fabricating completions (C9), and this.

    Asserted structurally, because the obvious version does not work: `"$LASTEXITCODE"
    in text` stays true when the guard is gutted, since the variable is still named in
    the failure message it prints. That version survived a mutation that removed every
    guard -- a test for "a check that cannot fail" which itself could not fail.

    So: every native invocation must be followed within three lines by a guard call,
    and the guard must actually compare and exit.
    """
    lines = _windows().splitlines()

    invocations = [
        (i, ln)
        for i, ln in enumerate(lines)
        if ln.strip().startswith("& $Venv") or ln.strip().startswith("& $PythonCmd")
    ]
    assert invocations, "expected install.ps1 to invoke pip or python natively"

    for index, line in invocations:
        window = " ".join(lines[index : index + 4])
        assert "Assert-LastExitCode" in window, (
            f"install.ps1 line {index + 1} runs a native command without checking its "
            f"exit code within the next three lines, so a failure there is silent:\n"
            f"  {line.strip()}"
        )

    body = _windows()
    assert "$LASTEXITCODE -ne 0" in body, "the guard does not compare the exit code"
    assert re.search(r"\$LASTEXITCODE -ne 0[\s\S]{0,400}?exit 1", body), (
        "the guard compares the exit code but never exits non-zero, so a failed step "
        "still lets the installer run on and report success"
    )


def test_the_success_banner_cannot_print_before_the_exit_code_check() -> None:
    """Ordering, not merely presence. A check after the banner is decoration.

    Matched on the line that EMITS the banner, not on any mention of it. The comment
    explaining why the old banner was wrong necessarily quotes it, and a check that
    cannot tell a warning from the thing it warns about would fail on its own
    documentation -- the same use-vs-mention distinction
    `test_the_fleet_wide_secret_is_no_longer_used_anywhere` draws.
    """
    lines = _windows().splitlines()
    emits = [
        i for i, ln in enumerate(lines) if "Write-Host" in ln and "Installation Complete" in ln
    ]
    checks = [i for i, ln in enumerate(lines) if "$LASTEXITCODE" in ln]

    assert emits, "expected install.ps1 to print a success banner"
    assert checks, "expected install.ps1 to check $LASTEXITCODE somewhere"
    assert min(checks) < min(emits), (
        "install.ps1 prints its success banner before any $LASTEXITCODE check, so a "
        "failed install still announces itself as complete"
    )


def test_posix_installer_still_aborts_on_error() -> None:
    """The property install.sh already had, pinned so it is not lost."""
    assert re.search(r"^set -e", _posix(), flags=re.MULTILINE), (
        "install.sh lost `set -e`, so a failing step no longer aborts it"
    )


# ---------------------------------------------------------------------------
# The instruction that could not work
# ---------------------------------------------------------------------------


def test_the_printed_run_command_changes_directory_first() -> None:
    """Settings resolve env_file=".env" against the WORKING DIRECTORY.

    The backgrounded daemon is launched with -WorkingDirectory and is fine. The
    command printed for a human to copy had no `cd`, so following the installer's own
    instructions produced a node on pure defaults: wrong id, no credential, and
    scheduler_url pointing at the host's own localhost. The symptom was a retry loop
    of "All connection attempts failed" against a Scheduler that was up throughout.
    """
    text = _windows()
    tail = text[text.find("To manually check or restart") :]
    assert tail, "install.ps1 no longer prints a manual run command"
    assert "Set-Location" in tail or "cd " in tail, (
        "the run command install.ps1 prints does not change into the node directory, "
        "so the node it starts cannot find the .env the installer just wrote"
    )
