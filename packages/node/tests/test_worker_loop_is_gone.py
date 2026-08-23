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

This file is the ratchet: it fails if any of the path comes back.
"""

import importlib
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
