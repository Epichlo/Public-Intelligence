"""`experimental/` must stay unreachable from shipping code (ROADMAP C2).

A directory named "experimental" that production imports from is not a quarantine,
it is a folder. This is the enforcement.

The move itself was prompted by three live defects, all caused by cut-feature
plumbing wired into live paths, none caught by 664 passing tests: streamed
completions republished to the mesh in plaintext, streaming deadlocking after four
chunks, and every node opening an unauthenticated wildcard subscriber that read host
shared memory by attacker-supplied name. See experimental/README.md.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTAL = REPO_ROOT / "experimental"

# Modules that moved out. Shipping code importing any of these by its OLD path is
# just as broken as importing the new one, and fails at runtime rather than here --
# so both spellings are checked.
QUARANTINED_MODULE_NAMES = {
    "transport",
    "local_boundary",
    "boundary_engine",
    "kv_cache",
    "quantization",
}


def _shipping_python_files() -> list[Path]:
    return [
        p
        for p in (REPO_ROOT / "packages").rglob("*.py")
        if "node_modules" not in p.parts and "egg-info" not in str(p)
    ]


def _string_literals_in(path: Path) -> list[str]:
    """Every string constant in a file, ignoring comments.

    Scanning raw text would match the explanatory comments this change added -- which
    it did, on the first run. A check that fails on its own documentation of the bug
    is not measuring the bug.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _imports_in(path: Path) -> list[tuple[str, int]]:
    """Every module name imported by a file, with its line number."""
    found: list[tuple[str, int]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, node.lineno))
    return found


def test_experimental_exists_and_holds_the_cut_features() -> None:
    """Guards against the directory being emptied without the ROADMAP being updated."""
    assert EXPERIMENTAL.is_dir(), "experimental/ is gone -- was C2 reverted?"
    for package in ("node", "scheduler"):
        for module in QUARANTINED_MODULE_NAMES:
            path = EXPERIMENTAL / package / f"{module}.py"
            assert path.exists(), f"{path.relative_to(REPO_ROOT)} is missing"


def test_no_shipping_module_imports_experimental() -> None:
    """The actual quarantine. `packages/` may not import from `experimental`."""
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module}"
        for path in _shipping_python_files()
        for module, lineno in _imports_in(path)
        if module.split(".")[0] == "experimental"
    ]
    assert not offenders, (
        "shipping code imports from experimental/, which makes the quarantine "
        f"decorative: {offenders}"
    )


@pytest.mark.parametrize("package", ["node", "scheduler"])
def test_the_cut_modules_are_not_importable_from_the_installed_package(package: str) -> None:
    """`node.core.transport` and friends must not resolve any more.

    Checked as an import failure rather than as a missing file, because a stale
    `.pyc`, an editable-install path entry, or a re-added shim would all make the
    file check pass while the module still resolved.
    """
    import importlib

    for module in QUARANTINED_MODULE_NAMES:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"{package}.core.{module}")


def test_the_split_stage_listener_stays_removed() -> None:
    """Runtime must not re-acquire the unauthenticated tensor subscriber.

    Duplicated deliberately from the node suite: that test asserts on the Runtime
    class, this one asserts on the source of the shipping tree, so re-introducing
    the subscription in a different module still fails.
    """
    offenders = [
        f"{path.relative_to(REPO_ROOT)}"
        for path in _shipping_python_files()
        if "tests" not in path.parts
        and any("tensors/*" in literal for literal in _string_literals_in(path))
    ]
    assert not offenders, (
        "a wildcard tensor-topic subscription is back in shipping code. It was "
        f"unauthenticated and read host shared memory by supplied name: {offenders}"
    )


def test_shipping_code_does_not_publish_generated_text_to_the_transport_topic() -> None:
    """No shipping module may reference the plaintext stream topic.

    `public-intelligence/net/transport/stream/{id}` carried every generated token in
    the clear, on a wildcard-subscribable key. The topic string itself is the thing
    to keep out of shipping code -- an import ban would not have caught it, because
    the leak was a string, not a symbol.
    """
    offenders = [
        f"{path.relative_to(REPO_ROOT)}"
        for path in _shipping_python_files()
        if "tests" not in path.parts
        and any("net/transport/stream" in literal for literal in _string_literals_in(path))
    ]
    assert not offenders, offenders
