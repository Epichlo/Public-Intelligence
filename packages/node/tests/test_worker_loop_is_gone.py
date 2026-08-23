"""The dead task-queue execution path is gone, and stays gone.

`Runtime._worker_loop` consumed a `task_queue` that nothing in `src` ever fed,
generated through an `InferenceBackend` that was only ever assigned
`EchoBackend`, wrote each result to an `ArtifactStore` nothing
read back, and published the metadata over Zenoh. The live serving path is
`api/inference.py` -> `clients/ollama.py` (`OllamaClient`) -- a different class
that never touched any of it.

Deleted rather than repaired (N1/C9 precedent): there was nothing to repair it
*to*. The tests that fed the queue by hand -- including the one named
`test_end_to_end_pipeline` -- exercised this path precisely because it had no
other entrance; they were deleted with it.

This file is the ratchet: it fails if any of the path comes back -- including
the quiet way it could come back. Deleting a committed package directory can
leave an UNTRACKED `__pycache__/` behind on disk; a source-less directory is
still a namespace package to importlib, so `node.backends` imports "fine",
`ModuleNotFoundError` never raises, and this file's first test silently stops
testing anything. The ghost shape itself is pinned shut below.
"""

import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from node.core.configuration import Settings
from node.runtime import Runtime

# Modules of the removed execution path. `node.backends` and `node.storage`
# each had one production caller -- the worker loop -- and zero after it.
DEAD_MODULES = (
    "node.backends",
    "node.backends.base",
    "node.backends.mock",
    "node.backends.ollama",
    "node.storage",
    "node.storage.base",
    "node.storage.local",
)

# Instance attributes that existed only to serve that path.
DEAD_RUNTIME_ATTRS = (
    "task_queue",
    "worker_task",
    "inference_backend",
    "artifact_store",
)


def test_the_dead_modules_stay_unimportable() -> None:
    for module in DEAD_MODULES:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)


def _ghost_directories(package_root: Path) -> list[Path]:
    """Directories under the installed package that hold no source files.

    A directory whose only content is `__pycache__/` (or nothing at all) is
    the residue of a deleted package: untracked by git, invisible to review,
    and -- because a source-less directory still imports as a namespace
    package -- enough to make `importlib.import_module` SUCCEED against dead
    bytecode. Exactly what defeated the import ratchet above it would never
    notice.
    """
    return [
        directory
        for directory in sorted(package_root.rglob("*"))
        if directory.is_dir()
        and directory.name != "__pycache__"
        and not any(child.is_file() for child in directory.iterdir())
    ]


def test_no_directory_under_the_package_is_a_bytecode_ghost() -> None:
    """The namespace-ghost shape stays impossible, for every future deletion.

    This is the committed guard the manual `rm -rf` of `backends/` and
    `storage/` `__pycache__` residue could not be: the next package deletion
    leaves the same trap, and this test -- not a person remembering the last
    incident -- is what catches it.
    """
    package_root = Path(importlib.import_module("node").__file__).parent
    ghosts = _ghost_directories(package_root)

    assert not ghosts, (
        "Source-less directories found under the node package. A directory "
        f"containing only __pycache__/ still imports as a namespace package, "
        f"which defeats the import ratchet in this very file. Delete them: "
        f"{[str(g) for g in ghosts]}"
    )


def test_the_ghost_walk_actually_walks_the_package() -> None:
    """Guards the guard: the walk above must see a real, populated tree.

    Pointed at the wrong root it would pass on an empty directory list -- a
    ratchet that always passes is worse than none.
    """
    package_root = Path(importlib.import_module("node").__file__).parent
    walked = [d for d in package_root.rglob("*") if d.is_dir() and d.name != "__pycache__"]

    seen = {d.name for d in walked}
    missing = {"api", "clients", "core", "models", "telemetry"} - seen
    assert not missing, f"ghost walk looks broken; did not see {sorted(missing)} in {sorted(seen)}"
    assert (package_root / "clients" / "ollama.py").is_file()


def test_runtime_carries_no_queue_or_backend_state() -> None:
    runtime = Runtime(
        settings=Settings(node_id="test-node", hostname="localhost", region="local"),
        scheduler_client=AsyncMock(),
        ollama_client=AsyncMock(),
        zenoh_client=MagicMock(),
    )

    for attr in DEAD_RUNTIME_ATTRS:
        assert not hasattr(runtime, attr), f"dead wiring came back: Runtime.{attr}"
    assert not hasattr(Runtime, "_worker_loop"), "the worker loop came back"


def test_the_live_serving_path_survived_the_removal() -> None:
    """Guards the guard: proves this ratchet watches a real codebase.

    The class the deletion must NOT have touched is `OllamaClient`, which is
    what `api/inference.py` actually calls -- distinct from the deleted
    `backends/ollama.py`, whose name it shares.
    """
    from node.clients.ollama import OllamaClient

    for loop in ("_heartbeat_loop", "_model_refresh_loop", "_collect_heartbeat_metrics"):
        assert callable(getattr(Runtime, loop))

    assert callable(OllamaClient.generate)
