"""System-wide integration test for the end-to-end task execution pipeline."""

import asyncio
import hashlib
import os
import shutil
import tempfile
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from scheduler.core.engine import SchedulingEngine
from scheduler.core.matchmaker import CapabilityMatchmaker
from scheduler.models.node import GPUInfo
from scheduler.models.node import Node as SchedulerNode
from scheduler.registry.node_registry import NodeRegistry
from src.shared.storage.local import LocalDiskArtifactStore

from node.backends.mock import EchoBackend
from node.core.configuration import Settings
from node.runtime import Runtime


@pytest.fixture
def temp_base_dir() -> Generator[str, None, None]:
    """Provide a temporary directory for out-of-band artifact storage."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.mark.anyio
async def test_end_to_end_pipeline(temp_base_dir: str) -> None:
    """Verify end-to-end task submission.

    Matches nodes, runs execution, and saves output artifact.
    """
    # 1. Setup Mock Control Plane components
    registry = NodeRegistry()

    # Register the compute worker node spec in the Scheduler NodeRegistry
    worker_node_spec = SchedulerNode(
        node_id="worker-node-1",
        hostname="localhost",
        ip_address="127.0.0.1",
        region="us-west",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=24.0),
        cpu_cores=8,
        ram_total_gb=32.0,
        available_models=["echo-model"],
    )
    await registry.local_register(worker_node_spec)

    strategy = CapabilityMatchmaker(registry)
    engine = SchedulingEngine(registry, strategy)

    # 2. Setup Node Runtime components
    settings = Settings(
        node_id="worker-node-1",
        hostname="localhost",
        region="us-west",
    )

    # Mock networking clients to isolate local test runtime
    mock_scheduler = MagicMock()
    mock_scheduler.register = AsyncMock()
    mock_scheduler.heartbeat = AsyncMock()
    mock_scheduler.unregister = AsyncMock()

    from node.models import ModelInfo

    mock_model = ModelInfo(
        name="echo-model",
        size_gb=4.0,
        family="llama",
        context_length=4096,
    )

    mock_ollama = MagicMock()
    mock_ollama.list_models = AsyncMock(return_value=[mock_model])

    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler,
        ollama_client=mock_ollama,
    )

    # Configure custom backend and storage directory on the runtime
    runtime.inference_backend = EchoBackend()
    runtime.artifact_store = LocalDiskArtifactStore(base_directory=temp_base_dir)

    # Start the worker runtime loops
    await runtime.start()

    try:
        # 3. Simulate Client Task Submission & Matchmaking Allocation
        task = {
            "task_id": "test-task-uuid-999",
            "requirements": {
                "model_name": "echo-model",
                "min_vram_gb": 10.0,
            },
        }

        tx_hash, allocated_node_id = await engine.schedule_task(task)

        # Assert correct matchmaking assignment & tx tracking context format
        assert allocated_node_id == "worker-node-1"
        assert len(tx_hash) == 64

        # 4. Route Task to the Worker's input queue
        task_execution_job = {
            "task_id": "test-task-uuid-999",
            "model_name": "echo-model",
            "prompt": "Hello integration testing pipeline",
        }
        await runtime.task_queue.put(task_execution_job)

        # 5. Wait for worker queue processing and join
        await asyncio.wait_for(runtime.task_queue.join(), timeout=5.0)

        # 6. Verify Out-of-band Artifact Store and execution state
        expected_output = "Echo: Hello integration testing pipeline"
        expected_checksum = hashlib.sha256(expected_output.encode("utf-8")).hexdigest()
        expected_art_id = f"art_test-task-uuid-999_{expected_checksum[:12]}"
        expected_file_path = os.path.join(temp_base_dir, f"{expected_art_id}.bin")

        # Assert the physical file was written to disk correctly
        assert os.path.exists(expected_file_path)

        with open(expected_file_path, "rb") as f:
            saved_content = f.read()
        assert saved_content.decode("utf-8") == expected_output

        # Retrieve output metadata representation
        uri = f"file://{expected_file_path}"
        retrieved_data = await runtime.artifact_store.get_artifact(uri)
        assert retrieved_data.decode("utf-8") == expected_output

    finally:
        # Stop background worker tasks
        await runtime.stop()
