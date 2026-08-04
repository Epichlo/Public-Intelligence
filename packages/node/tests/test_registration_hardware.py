"""Registration advertises real hardware end to end (roadmap 1.2).

`test_hardware_profile.py` covers detection in isolation. These cover the wiring:
that what was detected is what actually reaches the Scheduler, and that the
hardcoded `{"name": "unknown", "vram_total_gb": 16.0}` is gone from the payload.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from node.clients import SchedulerClient
from node.core.configuration import Settings
from node.models import ModelInfo, NodeInfo
from node.models.gpu_info import GPUInfo
from node.runtime import Runtime


@pytest.fixture
def settings() -> Settings:
    """Settings pointing at a mock Scheduler."""
    return Settings(
        node_id="test-node",
        hostname="localhost",
        region="local",
        scheduler_url="http://mock-scheduler:8080",
        heartbeat_interval_seconds=1,
    )


@pytest.mark.anyio
async def test_register_sends_the_nodes_own_gpu(settings: Settings) -> None:
    """The registration payload carries NodeInfo.gpu, not an injected literal."""
    node_info = NodeInfo(
        node_id="node-1",
        hostname="node.local",
        region="us-east",
        ip_address="192.168.1.50",
        cpu_cores=8,
        ram_total_gb=64.0,
        gpu=GPUInfo(
            name="NVIDIA GeForce RTX 4090",
            vram_total_gb=24.0,
            vram_available_gb=20.5,
        ),
        available_models=[
            ModelInfo(name="llama3-8b", size_gb=4.7, family="llama", context_length=8192)
        ],
    )

    mock_client = AsyncMock()
    mock_client.request.return_value = httpx.Response(
        201, request=httpx.Request("POST", "http://mock-scheduler:8080")
    )

    await SchedulerClient(settings, client=mock_client).register(node_info)

    payload = mock_client.request.call_args.kwargs["json"]
    assert payload["gpu"] == {
        "name": "NVIDIA GeForce RTX 4090",
        "vram_total_gb": 24.0,
        "vram_available_gb": 20.5,
    }
    assert payload["ram_total_gb"] == 64.0
    # available_models is still flattened to names for the Scheduler's contract.
    assert payload["available_models"] == ["llama3-8b"]


@pytest.mark.anyio
async def test_register_sends_zero_vram_for_cpu_only_node(settings: Settings) -> None:
    """A CPU-only node advertises 0 GB and is not silently upgraded to 16."""
    node_info = NodeInfo(
        node_id="node-1",
        hostname="node.local",
        region="us-east",
        ip_address="192.168.1.50",
        cpu_cores=4,
        ram_total_gb=8.0,
        gpu=GPUInfo(name="cpu-only", vram_total_gb=0.0, vram_available_gb=0.0),
    )

    mock_client = AsyncMock()
    mock_client.request.return_value = httpx.Response(
        201, request=httpx.Request("POST", "http://mock-scheduler:8080")
    )

    await SchedulerClient(settings, client=mock_client).register(node_info)

    payload = mock_client.request.call_args.kwargs["json"]
    assert payload["gpu"]["vram_total_gb"] == 0.0
    assert payload["gpu"]["name"] == "cpu-only"


@pytest.mark.anyio
async def test_runtime_registers_with_detected_hardware(settings: Settings) -> None:
    """Runtime.start() advertises what detection found, not placeholders."""
    mock_scheduler_client = AsyncMock()
    mock_ollama_client = AsyncMock()
    mock_ollama_client.list_models.return_value = []
    mock_zenoh_client = MagicMock()
    mock_zenoh_client.session = None

    detected = GPUInfo(
        name="NVIDIA A100-SXM4-40GB",
        vram_total_gb=40.0,
        vram_available_gb=39.0,
    )

    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=mock_ollama_client,
        zenoh_client=mock_zenoh_client,
    )

    with (
        patch("node.runtime.detect_gpu", AsyncMock(return_value=detected)),
        patch("node.runtime.detect_ram_total_gb", return_value=128.0),
    ):
        await runtime.start()

    await runtime.stop()

    registered: NodeInfo = mock_scheduler_client.register.call_args.args[0]
    assert registered.gpu.name == "NVIDIA A100-SXM4-40GB"
    assert registered.gpu.vram_total_gb == 40.0
    assert registered.gpu.vram_available_gb == 39.0
    assert registered.ram_total_gb == 128.0


@pytest.mark.anyio
async def test_runtime_startup_survives_hardware_detection_failure(
    settings: Settings,
) -> None:
    """Detection blowing up must not stop the node from registering."""
    mock_scheduler_client = AsyncMock()
    mock_ollama_client = AsyncMock()
    mock_ollama_client.list_models.return_value = []
    mock_zenoh_client = MagicMock()
    mock_zenoh_client.session = None

    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=mock_ollama_client,
        zenoh_client=mock_zenoh_client,
    )

    with patch("node.runtime.detect_gpu", AsyncMock(side_effect=RuntimeError("probe died"))):
        await runtime.start()
        # Checked before stop(), which legitimately flips this to "unregistered".
        assert runtime.registration_status == "registered"

    await runtime.stop()

    registered: NodeInfo = mock_scheduler_client.register.call_args.args[0]
    assert registered.gpu.vram_total_gb == 0.0
    assert registered.gpu.name == "cpu-only"
