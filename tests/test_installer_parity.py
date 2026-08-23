"""The two installers must agree on what a host cannot install without.

On 2026-08-11 a node ran on a second machine for the first time. Four of the six
defects that stood in the way were the same defect: someone updated `install.sh` and
did not update `install.ps1`. The Windows installer could not pass an invite code
(D4 had made it mandatory), installed `packages/node` without `packages/shared`
(C8 had made it a local dependency), reported success over a failed pip, and printed
a run command that could not find the `.env` it had just written.

None of it was caught, and the reason is structural rather than careless:
`scripts/verify_install.sh` runs `install.sh` for real, and **nothing had ever
executed `install.ps1`**. The gate is bash; the Windows CI legs run the same bash
gate. So that file was outside "the only definition of does this pass" for its
entire life -- the fifth instance of that pattern here, after tests/ (2.9), the
website (C6), scripts/ (C7) and .claude/, and the first one found by a user.

**These are text-level checks and that is a real limitation, stated rather than
implied.** They read both installers and compare what they mention. They cannot
prove `install.ps1` works, because they cannot execute PowerShell on Linux.
Execution now exists -- `.github/workflows/ci.yml::install-windows` runs the
installer for real against a throwaway copy on a Windows runner and asserts the
installed venv imports the node package -- but CI runs between commits, while these
checks run on every gate invocation and fail on the exact drifts that broke real
hosts. One proves the thing works; the other says WHICH thing drifted. Both halves
are needed; neither substitutes for the other.

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
    [
        "NODE_INVITE_CODE",
        "NODE_NETWORK_AUTH_TOKEN",
        "NODE_FLEET_TOKEN",
        "NODE_SCHEDULER_URL",
        "NODE_BOOTSTRAP_ROUTERS",
    ],
)
def test_both_installers_write_the_same_env_keys(env_key: str) -> None:
    """Accepting a flag and writing it to .env are different things.

    install.ps1 accepted -SchedulerUrl and wrote it; the invite code had neither a
    parameter nor a line, so a host had to append it by hand.
    """
    assert env_key in _posix(), f"install.sh no longer writes {env_key}"
    assert env_key in _windows(), f"install.ps1 no longer writes {env_key}"


def test_neither_installer_overwrites_the_per_install_credential() -> None:
    """Decision D9: the fleet token is written beside the node's own key, not over it.

    For one day both installers assigned the operator-supplied fleet token to the
    variable holding the generated per-install credential. That is the exact hole D9
    closes -- every host on the fleet ends up with the same key, so any of them can
    seal a mesh envelope as any other, and the Scheduler cannot tell.

    It leaked further than registration: install.sh copies that same variable into
    the dashboard's `.env.local` as NODE_AUTH_TOKEN, so the fleet secret was written
    to a second file as well.

    Matched on assignment, not mention -- both files necessarily name both variables
    in the comments explaining the split.
    """
    posix_assignments = re.findall(r"^\s*AUTH_TOKEN_VAL=(.*)$", _posix(), flags=re.MULTILINE)
    assert posix_assignments, "install.sh no longer assigns AUTH_TOKEN_VAL at all"
    for value in posix_assignments:
        assert "NETWORK_AUTH_TOKEN" not in value, (
            "install.sh assigns the operator's fleet token to AUTH_TOKEN_VAL, which is "
            "this host's own credential and is also copied to the dashboard env "
            f"(decision D9): AUTH_TOKEN_VAL={value.strip()}"
        )

    windows_assignments = re.findall(r"^\s*\$AuthToken\s*=\s*(.*)$", _windows(), flags=re.MULTILINE)
    assert windows_assignments, "install.ps1 no longer assigns $AuthToken at all"
    for value in windows_assignments:
        assert "$NetworkAuthToken" not in value, (
            "install.ps1 assigns the operator's fleet token to $AuthToken, which is "
            f"this host's own credential (decision D9): $AuthToken = {value.strip()}"
        )


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


def test_both_git_fetches_are_guarded_like_every_pip_call() -> None:
    """install.ps1 ran `git pull` and `git clone --depth 1` without checking exits.

    $ErrorActionPreference does not trap native exit codes, so an offline or partial
    fetch silently installed whatever stale tree already sat under
    %USERPROFILE%/PublicIntelligence and reported that as a fresh successful install
    -- the same defect class the pip guards above them were added for. Both native
    fetches get the identical guard.
    """
    lines = _windows().splitlines()
    fetches = [(i, ln) for i, ln in enumerate(lines) if re.match(r"^\s*git\s", ln)]
    assert len(fetches) >= 2, (
        "expected both the update pull and the fresh clone to still be native git calls"
    )
    unguarded = []
    for index, line in fetches:
        window = "\n".join(lines[index : index + 4])
        if "Assert-LastExitCode" not in window:
            unguarded.append(f"line {index + 1}: {line.strip()}")
    assert not unguarded, (
        "native git calls whose failure would silently keep a stale tree, without "
        f"an exit-code guard within four lines: {unguarded}"
    )


def test_the_env_file_writer_cannot_emit_a_bom() -> None:
    """install.ps1 wrote .env with Set-Content -Encoding UTF8, which under Windows
    PowerShell 5.1 emits a UTF-8 BOM. python-dotenv reads env files as utf-8 WITHOUT
    stripping one, so the first key arrived as \\ufeffNODE_ID, pydantic-settings never
    matched it, and every such host silently registered as the default id
    "node-local", colliding with any second host queryable through the mesh.

    The writer must be an API whose encoding cannot depend on which powershell hosts
    the script.
    """
    text = _windows()
    writers = [
        ln.strip()
        for ln in text.splitlines()
        if re.match(r"^\s*\[System\.IO\.File\]::WriteAllText\(", ln)
    ]
    assert writers, ".env is written through no API whose encoding can be controlled"
    for writer in writers:
        assert "UTF8Encoding($false)" in writer, (
            f".env writer does not force BOM-less UTF-8: {writer}"
        )

    # Matched on the exact broken call shape, so a comment explaining the fix
    # cannot satisfy this and reverting cannot hide behind prose.
    reverted = re.search(
        r"^Set-Content\s+-Path\s+\$EnvFile\s+-Value\s+\$EnvContent\b",
        text,
        flags=re.MULTILINE,
    )
    assert reverted is None, (
        ".env is written with Set-Content again; under Windows PowerShell 5.1 that "
        "emits a UTF-8 BOM and the first key stops parsing (\\ufeffNODE_ID)"
    )


def test_the_daemon_success_claim_follows_evidence_of_liveness() -> None:
    """install.ps1 printed "[OK] Host Node daemon launched successfully" right after
    Start-Process, unconditionally. A detached pythonw discards its output and
    $ErrorActionPreference traps nothing for it, so a late startup failure printed
    success -- and a re-run over a live old daemon could not bind its port, died
    quietly, and STILL printed success while traffic kept hitting the STALE
    pre-update node. scripts/launch_host_node.sh polls /health before claiming
    victory; the Windows installer has to meet the same bar.

    Asserted structurally, use-vs-mention: the success line is matched only where it
    is EMITTED, and between the launch and that emission there must live a captured
    process, an exited-process check, a bounded probe of the node's own /health, and
    a loud non-zero abort when none of it comes good.
    """
    lines = _windows().splitlines()

    launches = [i for i, ln in enumerate(lines) if re.search(r"\$Daemon\s*=\s*Start-Process\b", ln)]
    claims = [
        i
        for i, ln in enumerate(lines)
        if re.match(r"\s*Write-Host", ln) and "daemon launched successfully" in ln.lower()
    ]
    assert len(launches) == 1, f"expected exactly one daemon launch, found {len(launches)}"
    assert len(claims) == 1, f"expected exactly one daemon success claim, found {len(claims)}"
    launch_index, claim_index = launches[0], claims[0]
    assert launch_index < claim_index, "the success claim prints before the launch"

    between = "\n".join(lines[launch_index:claim_index])
    assert "-PassThru" in between, (
        "the launch does not capture the process, so nothing afterwards can check it"
    )
    assert "HasExited" in between, "nothing checks whether the daemon died during startup"
    assert re.search(r'\$HealthUrl\s*=\s*"http://localhost:\$NodePort/health"', between), (
        "the liveness probe is not pointed at the node's own /health endpoint"
    )
    assert "Invoke-WebRequest" in between, "no health probe is issued at all"
    assert re.search(r"^(\s*)exit 1$", between, flags=re.MULTILINE), (
        "a failed liveness check must abort loudly instead of falling through to "
        "the success message"
    )


def test_the_daemon_launch_leaves_its_words_on_record() -> None:
    """The daemon must launch with both output streams captured to files.

    The first real execution of this installer (windows-latest CI, 2026-08-23)
    watched the daemon die with exit code 1 in its first seconds -- and could not
    say why, because the launcher used pythonw, under which sys.stdout and
    sys.stderr are None INSIDE the interpreter, so a traceback prints nowhere at
    all, and Start-Process without redirects discards whatever survived anyway.
    The POSIX launcher has always kept `nohup >> node.log`; the Windows launcher
    has to meet the same bar: venv python.exe (not pythonw), both streams
    redirected into files under packages\\node, and the failure path printing
    those files' contents before exiting.
    """
    text = _windows()

    launches = [ln for ln in text.splitlines() if re.search(r"\$Daemon\s*=\s*Start-Process\b", ln)]
    assert len(launches) == 1, f"expected exactly one daemon launch, found {len(launches)}"
    launch = launches[0]
    # Use-vs-mention (this file's convention): explaining WHY pythonw is banned in a
    # comment is fine; launching under it is not.
    assert not re.search(r"Start-Process[^`]*pythonw", text, flags=re.DOTALL), (
        "install.ps1 still launches the daemon under pythonw: its stdout/stderr are "
        "None inside Python, so crash tracebacks vanish and death is undiagnosable"
    )
    # Start-Process parameters continue across backtick continuations; the whole
    # launch block is what must carry the redirects, so search from the launch line.
    tail = text[text.index(launch) :]
    head = tail[:2000]
    assert "-RedirectStandardOutput" in head, (
        "the daemon's stdout is not redirected to a file, so its startup output is lost"
    )
    assert "-RedirectStandardError" in head, (
        "the daemon's stderr is not redirected to a file, so a traceback would be lost"
    )
    assert re.search(r"-FilePath\s+\$VenvPython\b", launch + tail[:200]), (
        "the daemon must run under the venv's python.exe, whose streams can be captured"
    )

    failure = text[text.index("if (-not $Serving)") :]
    assert "Get-Content" in failure[:2500], (
        "the liveness-failure abort does not print the daemon's own log lines, so a "
        "host operator sees the symptom but never the cause"
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
