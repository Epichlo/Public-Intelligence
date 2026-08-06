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

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Pairs of files that must stay compatible, with the number of differing
# significant lines tolerated today. LOWER THESE as pairs converge; never raise
# one without saying why in the commit message.
DUPLICATE_PAIRS: dict[str, tuple[str, str, int]] = {
    "quantization": (
        "packages/node/src/node/core/quantization.py",
        "packages/scheduler/src/scheduler/core/quantization.py",
        0,
    ),
    "kv_cache": (
        "packages/node/src/node/core/kv_cache.py",
        "packages/scheduler/src/scheduler/core/kv_cache.py",
        2,
    ),
    "local_boundary": (
        "packages/node/src/node/core/local_boundary.py",
        "packages/scheduler/src/scheduler/core/local_boundary.py",
        2,
    ),
    "autonomous_orchestrator": (
        "packages/node/src/node/core/autonomous_orchestrator.py",
        "packages/scheduler/src/scheduler/core/autonomous_orchestrator.py",
        14,
    ),
    "transport": (
        "packages/node/src/node/core/transport.py",
        "packages/scheduler/src/scheduler/core/transport.py",
        22,
    ),
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
    return sum(1 for line in diff if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))


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
        data = tomllib.loads((REPO_ROOT / "packages" / pkg.lower() / "pyproject.toml").read_text(encoding="utf-8"))
        dev = data["project"]["optional-dependencies"]["dev"]
        pins[pkg] = sorted(d for d in dev if "==" in d)

    assert pins["Node"] == pins["Scheduler"], (
        f"Pinned dev tools differ:\n  Node:      {pins['Node']}\n"
        f"  Scheduler: {pins['Scheduler']}"
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
        r"^\s*(?:run:|[-\s]*)\s*(ruff|mypy|bandit|pytest)\s+(?!.*verify)", ci, flags=re.M
    )

    assert not forbidden, (
        f"ci.yml runs {sorted(set(forbidden))} directly. Add the check to "
        "scripts/verify.sh instead -- CI is supposed to call that and nothing else."
    )
