"""Things that exist twice in this repo, and must not drift further apart.

Node and Scheduler are separate git repositories with no shared installable
package, so several modules exist as copies. CLAUDE.md has warned about this for a
while; the warning did not stop `autonomous_orchestrator.py` from diverging when a
fix landed on one copy only, and it did not stop `transport.py` reaching a 22-line
difference. A comment cannot enforce anything. A test can.

**These are ratchets, not gates.** Each pair has a recorded drift budget equal to
where it stands today. The tests fail when a pair drifts *further*, not because it
is drifted now — otherwise they would be red on arrival and get deleted. When you
converge a pair, lower its budget; the test then holds the new line.

`tests/test_mesh_protocol_parity.py` covers the one pair that is strictly identical
and round-trips real data through both copies. This file covers the rest.
"""

import json
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Pairs of files that must stay compatible, with the number of differing
# significant lines tolerated today. LOWER THESE as pairs converge; never raise
# one without saying why in the commit message.
#
# Four pairs left this table on 2026-08-07 and the reason matters, because "the
# ratchet has fewer entries" reads like progress and here it is mostly relocation:
#
#   quantization, kv_cache, local_boundary, transport -> experimental/ (ROADMAP C2).
#     Still duplicated, still drifting, just no longer part of the shipped system.
#     Tracked below under EXPERIMENTAL_PAIRS so the drift does not vanish from view.
#   autonomous_orchestrator -> DELETED (ROADMAP 2.10). It returned
#     verification_passed=True for a stub that ran nothing.
DUPLICATE_PAIRS: dict[str, tuple[str, str, int]] = {
    "mesh_protocol": (
        "packages/node/src/node/core/mesh_protocol.py",
        "packages/scheduler/src/scheduler/core/mesh_protocol.py",
        0,
    ),
    "mesh_auth": (
        "packages/node/src/node/core/mesh_auth.py",
        "packages/scheduler/src/scheduler/core/mesh_auth.py",
        0,
    ),
}

# The same ratchet, applied to the quarantined copies. They are not shipped, so a
# regression here is not urgent -- but dropping them from measurement entirely would
# turn "we stopped tracking it" into "the drift went away".
EXPERIMENTAL_PAIRS: dict[str, tuple[str, str, int]] = {
    "quantization": (
        "experimental/node/quantization.py",
        "experimental/scheduler/quantization.py",
        0,
    ),
    "kv_cache": ("experimental/node/kv_cache.py", "experimental/scheduler/kv_cache.py", 2),
    "local_boundary": (
        "experimental/node/local_boundary.py",
        "experimental/scheduler/local_boundary.py",
        2,
    ),
    "transport": ("experimental/node/transport.py", "experimental/scheduler/transport.py", 22),
}


def _significant_lines(path: Path) -> list[str]:
    """Lines that carry meaning: no blanks, no comments, no import statements.

    Imports are excluded because the copies legitimately differ there -- one says
    `from node.` and the other `from scheduler.`. Everything else should converge.
    """
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("import ", "from ")):
            continue
        out.append(line)
    return out


def _drift(a: Path, b: Path) -> int:
    """Count significant lines present in one copy but not the other."""
    import difflib

    diff = difflib.unified_diff(_significant_lines(a), _significant_lines(b), lineterm="", n=0)
    return sum(
        1 for line in diff if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


@pytest.mark.parametrize("name", sorted(DUPLICATE_PAIRS))
def test_duplicate_pair_has_not_drifted_further(name: str) -> None:
    """A duplicated module may not diverge beyond its recorded budget."""
    left, right, budget = DUPLICATE_PAIRS[name]
    a, b = REPO_ROOT / left, REPO_ROOT / right

    if not a.exists() or not b.exists():
        pytest.skip(f"{name}: one copy is absent, nothing to compare")

    actual = _drift(a, b)

    assert actual <= budget, (
        f"{name} drifted further apart: {actual} differing lines, budget {budget}.\n"
        f"  {left}\n  {right}\n"
        "Either apply the change to BOTH copies, or -- if the divergence is "
        "deliberate -- raise the budget in this file and say why in the commit."
    )


@pytest.mark.parametrize("name", sorted(DUPLICATE_PAIRS))
def test_duplicate_pair_budget_is_not_stale(name: str) -> None:
    """A converged pair must have its budget lowered, or the ratchet stops working.

    Without this, budgets only ever describe the worst the pair has ever been, and
    a pair could silently re-drift back up to an obsolete allowance.
    """
    left, right, budget = DUPLICATE_PAIRS[name]
    a, b = REPO_ROOT / left, REPO_ROOT / right

    if not a.exists() or not b.exists():
        pytest.skip(f"{name}: one copy is absent")

    actual = _drift(a, b)

    assert actual >= budget, (
        f"{name} is now at {actual} differing lines but its budget is still {budget}. "
        f"Lower the budget in {Path(__file__).name} to {actual} to hold the improvement."
    )


def test_gpu_info_pair_has_the_same_fields() -> None:
    """The two GPUInfo models are a wire contract, so their fields must match.

    Added as a deliberate fifth duplicate by roadmap 1.2. Structural equality is
    checkable here even though the files are not identical.
    """
    from node.models.gpu_info import GPUInfo as NodeGPUInfo
    from scheduler.models.node import GPUInfo as SchedulerGPUInfo

    node_fields = {n: str(f.annotation) for n, f in NodeGPUInfo.model_fields.items()}
    sched_fields = {n: str(f.annotation) for n, f in SchedulerGPUInfo.model_fields.items()}

    assert node_fields == sched_fields, (
        "GPUInfo diverged between Node and Scheduler. These describe the same JSON "
        "object in a registration payload; a field on one side and not the other is "
        "a 422 the first time a real node registers."
    )


# --------------------------------------------------------------------------
# Tooling config, which is duplicated for the same reason the modules are
# --------------------------------------------------------------------------


def _ruff_block(pyproject: Path) -> dict:
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["ruff"]


def test_both_packages_lint_under_identical_rules() -> None:
    """`ruff check ./Node ./Scheduler` must mean one thing, not two.

    Ruff resolves config per-directory, so divergent `[tool.ruff]` blocks meant the
    same file passed in one subtree and failed in the other -- ARG was enabled on
    Node only, and line-length differed by one. "Does this pass lint" had no single
    answer, which is how three ARG violations were dismissed as out-of-scope and
    reached main.
    """
    node = _ruff_block(REPO_ROOT / "packages" / "node" / "pyproject.toml")
    sched = _ruff_block(REPO_ROOT / "packages" / "scheduler" / "pyproject.toml")

    assert node == sched, (
        "The [tool.ruff] blocks in Node/pyproject.toml and Scheduler/pyproject.toml "
        "have diverged. They must stay byte-identical; a root config file is not an "
        "option because these are separate repositories."
    )


def test_both_packages_pin_the_same_tool_versions() -> None:
    """A tool version that differs between packages gives two answers again.

    Local ran ruff 0.16.0 while CI resolved 0.16.1, because CI installed them
    unpinned with `--upgrade`.
    """
    pins = {}
    for pkg in ("Node", "Scheduler"):
        data = tomllib.loads(
            (REPO_ROOT / "packages" / pkg.lower() / "pyproject.toml").read_text(encoding="utf-8")
        )
        dev = data["project"]["optional-dependencies"]["dev"]
        pins[pkg] = sorted(d for d in dev if "==" in d)

    assert pins["Node"] == pins["Scheduler"], (
        f"Pinned dev tools differ:\n  Node:      {pins['Node']}\n  Scheduler: {pins['Scheduler']}"
    )
    assert pins["Node"], "dev tools must be pinned exactly (==), not floored (>=)"


def test_ci_delegates_to_the_verify_script() -> None:
    """CI must not grow its own list of checks alongside scripts/verify.sh.

    Two lists is the condition that produced the original failure. This fails if a
    `run:` step in the test matrix invokes a linter or pytest directly instead of
    going through the one gate.
    """
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    forbidden = re.findall(
        r"^\s*(?:run:|[-\s]*)\s*(ruff|mypy|bandit|pytest)\s+(?!.*verify)",
        ci,
        flags=re.MULTILINE,
    )

    assert not forbidden, (
        f"ci.yml runs {sorted(set(forbidden))} directly. Add the check to "
        "scripts/verify.sh instead -- CI is supposed to call that and nothing else."
    )


# ---------------------------------------------------------------------------
# Gate coverage. Three times now the defect found was a check's ABSENCE rather
# than a check's failure: tests/ was unlinted until ROADMAP 2.9, tests/ was
# untyped and the website unchecked until C6/C7, and scripts/ -- which contains
# the gate itself -- was outside all of it until the same change.
#
# Each was invisible for the same reason: verify.sh is trusted as total and was
# silently partial. These tests make the NEXT such directory fail loudly when it
# is added, instead of two roadmap items later.
# ---------------------------------------------------------------------------

# Directories that hold Python and are deliberately not linted, with the reason.
# Adding a name here is a decision someone has to write down.
LINT_EXEMPT_DIRS = {
    ".venv": "third-party code",
    ".git": "not source",
    "docs": "prose; any Python here is illustrative",
}


def _verify_script() -> str:
    return (REPO_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")


def test_every_python_directory_is_linted_by_the_gate() -> None:
    """A top-level directory containing Python must be named in a ruff invocation.

    This is the ratchet for the pattern above. It does not check that the linting
    is *correct* -- only that the directory is not sitting outside "the only
    definition of does this pass" while appearing to be inside it.
    """
    script = _verify_script()
    linted = set(re.findall(r"-m ruff (?:check|format)[^\n]*?\./(\w+)", script))

    unlinted = []
    for child in sorted(REPO_ROOT.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name in LINT_EXEMPT_DIRS:
            continue
        if not any(child.rglob("*.py")):
            continue
        if child.name not in linted:
            unlinted.append(child.name)

    assert not unlinted, (
        f"{unlinted} contain Python and are not passed to ruff by scripts/verify.sh. "
        f"Either add them to the gate or add them to LINT_EXEMPT_DIRS with a reason. "
        f"Currently linted: {sorted(linted)}"
    )


def test_experimental_is_linted_but_its_tests_do_not_run():
    """ROADMAP C2's real goal: the reported test count must mean something.

    Excluding `experimental/` from the gate entirely would let ~2,000 lines rot, and
    linting costs nothing. What C2 wanted was for the shipping test number to stop
    being inflated by suites covering features this product decided not to have. So
    the modules are linted and their tests are not run -- and this test pins both
    halves, because either one flipping quietly would undo the point.
    """
    script = _verify_script()
    assert "ruff check ./experimental" in script, "experimental/ is no longer linted"
    assert "pytest ./experimental" not in script and "pytest experimental" not in script, (
        "experimental/ tests are in the gate again -- the green count now includes "
        "features that are cut from v1."
    )


def test_the_gate_type_checks_the_root_test_suite() -> None:
    """ROADMAP C7. mypy on tests/ is only meaningful because of the py.typed markers.

    Without them mypy answers `missing library stubs or py.typed marker` for every
    import into node and scheduler, so the step would pass while verifying nothing
    about the contract these tests assert. Both facts are checked together, because
    either one alone is a check that reports success for doing no work.
    """
    assert "-m mypy tests" in _verify_script(), (
        "scripts/verify.sh no longer type-checks tests/ (ROADMAP C7)."
    )

    for package in ("node", "scheduler"):
        marker = REPO_ROOT / "packages" / package / "src" / package / "py.typed"
        assert marker.exists(), (
            f"{marker.relative_to(REPO_ROOT)} is missing. Without it, `mypy tests` "
            f"silently stops checking anything that crosses into {package}."
        )


def test_the_gate_checks_the_website() -> None:
    """ROADMAP C6. The website has a test script, a runner config, and gate steps."""
    script = _verify_script()
    assert "website lint" in script and "website tests" in script, (
        "scripts/verify.sh no longer runs the website checks (ROADMAP C6)."
    )

    package_json = json.loads(
        (REPO_ROOT / "packages" / "website" / "package.json").read_text(encoding="utf-8")
    )
    assert "test" in package_json["scripts"], "packages/website has no `test` script."

    # `passWithNoTests: false` is what stops the step going green on zero test
    # files, which would be the same silent-partial failure in a new costume.
    config = (REPO_ROOT / "packages" / "website" / "vitest.config.mts").read_text(encoding="utf-8")
    assert "passWithNoTests: false" in config, (
        "vitest must not pass with no tests -- a green step that ran nothing is "
        "exactly what putting the website in the gate was meant to prevent."
    )


def test_ci_installs_what_the_gate_needs_to_avoid_skipping() -> None:
    """The website steps skip when node_modules is absent. CI must never skip them.

    Locally that skip is a deliberate kindness to Python-only contributors, and the
    summary line says which checks did not run. In CI it would be a green PASS over
    unchecked code, so CI installs the dependencies.
    """
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "npm ci" in ci, (
        "ci.yml does not install the website dependencies, so scripts/verify.sh "
        "will skip the website checks and still report PASS."
    )
