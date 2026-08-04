"""The node measures the metrics it heartbeats (roadmap 1.3).

`runtime._collect_heartbeat_metrics` returned five constants marked "(placeholders)".
The Scheduler filters on the heartbeat's `vram_available_gb` and scores on all of
them, so a node reporting a constant 0.0 was excluded from every VRAM-gated task
and indistinguishable from every other node. See specs/real-heartbeat-metrics.md.

Live VRAM must come from the same NVIDIA -> Apple Silicon -> cpu-only ordering that
registration uses, or a node can advertise 24 GB total and heartbeat 0 GB free on
the same hardware.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import psutil
import pytest

from node.core.configuration import Settings
from node.core.hardware import (
    _apple_gpu_utilization,
    _parse_ioreg_utilization,
    detect_host_metrics,
)
from node.runtime import Runtime

GIB = 1024**3


class _FakeCollector:
    def __init__(self, gpu: dict[str, Any] | None = None, raises: bool = False) -> None:
        self._gpu = gpu
        self._raises = raises

    async def collect_gpu_metrics(self) -> dict[str, Any]:
        if self._raises:
            raise RuntimeError("nvidia-smi exploded")
        assert self._gpu is not None
        return self._gpu


def _no_apple_silicon() -> dict[str, Any]:
    return {
        "is_apple_silicon": False,
        "chip_family": "Unknown",
        "unified_memory_gb": 0.0,
        "metal_supported": False,
    }


def _apple_silicon() -> dict[str, Any]:
    return {
        "is_apple_silicon": True,
        "chip_family": "Apple M3 Max",
        "unified_memory_gb": 36.0,
        "metal_supported": True,
    }


def _nvidia(util: float = 62.0, free_gb: float = 9.5) -> dict[str, Any]:
    return {
        "name": "NVIDIA GeForce RTX 4090",
        "utilization": util,
        "vram_total_bytes": int(24.0 * GIB),
        "vram_available_bytes": int(free_gb * GIB),
        "vram_used_bytes": int((24.0 - free_gb) * GIB),
    }


def _no_gpu() -> dict[str, Any]:
    return {
        "name": "N/A",
        "utilization": 0.0,
        "vram_total_bytes": 0,
        "vram_available_bytes": 0,
        "vram_used_bytes": 0,
    }


@pytest.mark.anyio
async def test_reports_real_nvidia_utilization_and_free_vram() -> None:
    """On NVIDIA both live GPU figures come from nvidia-smi, not constants."""
    with patch("node.core.hardware.detect_apple_silicon_hardware", _no_apple_silicon):
        metrics = await detect_host_metrics(_FakeCollector(_nvidia(util=62.0, free_gb=9.5)))

    assert metrics.gpu_utilization == pytest.approx(62.0)
    assert metrics.vram_available_gb == pytest.approx(9.5, abs=0.01)


@pytest.mark.anyio
async def test_reports_apple_silicon_free_unified_memory() -> None:
    """Apple Silicon reports free unified memory, never a hardcoded 0.0.

    This is the case the old placeholder broke worst: the node registers 36 GB of
    unified memory as VRAM, then heartbeats 0 GB free, and the matchmaker drops it
    from every VRAM-gated task.
    """
    with (
        patch("node.core.hardware.detect_apple_silicon_hardware", _apple_silicon),
        patch("node.core.hardware._apple_gpu_utilization", return_value=13.0),
    ):
        metrics = await detect_host_metrics(_FakeCollector(_no_gpu()))

    assert metrics.vram_available_gb > 0.0
    assert metrics.vram_available_gb <= 36.0
    assert metrics.gpu_utilization == pytest.approx(13.0)


@pytest.mark.anyio
async def test_cpu_only_host_reports_zero_gpu_metrics() -> None:
    """No GPU means 0.0, which correctly excludes it from VRAM-gated work."""
    with patch("node.core.hardware.detect_apple_silicon_hardware", _no_apple_silicon):
        metrics = await detect_host_metrics(_FakeCollector(_no_gpu()))

    assert metrics.gpu_utilization == 0.0
    assert metrics.vram_available_gb == 0.0


@pytest.mark.anyio
async def test_reports_real_cpu_and_ram() -> None:
    """CPU and RAM come from psutil and are within the host's actual bounds."""
    with patch("node.core.hardware.detect_apple_silicon_hardware", _no_apple_silicon):
        metrics = await detect_host_metrics(_FakeCollector(_no_gpu()))

    total_gb = psutil.virtual_memory().total / GIB
    assert 0.0 <= metrics.cpu_utilization <= 100.0
    assert 0.0 < metrics.ram_available_gb <= total_gb
    # The old placeholder was exactly 8.0 on every host regardless of hardware.
    assert metrics.ram_available_gb == pytest.approx(
        psutil.virtual_memory().available / GIB, abs=1.5
    )


@pytest.mark.anyio
async def test_metric_collection_degrades_instead_of_raising() -> None:
    """A node that cannot read its GPU must keep heartbeating, not go silent."""
    with patch("node.core.hardware.detect_apple_silicon_hardware", _no_apple_silicon):
        metrics = await detect_host_metrics(_FakeCollector(raises=True))

    assert metrics.gpu_utilization == 0.0
    assert metrics.vram_available_gb == 0.0
    assert metrics.ram_available_gb > 0.0


@pytest.mark.anyio
async def test_runtime_heartbeat_reports_measured_values_and_real_queue_depth() -> None:
    """The runtime sends what it measured, including actual pending work."""
    runtime = Runtime(
        settings=Settings(node_id="test-node", hostname="localhost", region="local"),
        scheduler_client=AsyncMock(),
        ollama_client=AsyncMock(),
        zenoh_client=MagicMock(),
    )
    runtime.task_queue.put_nowait({"task": "one"})
    runtime.task_queue.put_nowait({"task": "two"})

    fake = MagicMock(
        cpu_utilization=73.5,
        ram_available_gb=11.25,
        gpu_utilization=41.0,
        vram_available_gb=6.75,
    )

    with patch("node.runtime.detect_host_metrics", AsyncMock(return_value=fake)):
        metrics = await runtime._collect_heartbeat_metrics()

    assert metrics["cpu_utilization"] == 73.5
    assert metrics["ram_available_gb"] == 11.25
    assert metrics["gpu_utilization"] == 41.0
    assert metrics["vram_available_gb"] == 6.75
    assert metrics["queue_length"] == 2


@pytest.mark.anyio
async def test_runtime_heartbeat_metrics_are_not_the_old_placeholders() -> None:
    """Guards the exact constants this feature removed, measured on this host."""
    runtime = Runtime(
        settings=Settings(node_id="test-node", hostname="localhost", region="local"),
        scheduler_client=AsyncMock(),
        ollama_client=AsyncMock(),
        zenoh_client=MagicMock(),
    )

    metrics = await runtime._collect_heartbeat_metrics()

    assert metrics["ram_available_gb"] != 8.0, "still returning the placeholder RAM"
    assert metrics["ram_available_gb"] == pytest.approx(
        psutil.virtual_memory().available / GIB, abs=2.0
    )


# ---------------------------------------------------------------------------
# ioreg parsing.
#
# These cannot be covered by calling `_apple_gpu_utilization` on this machine: an
# idle Apple GPU genuinely reports 0.0, which is indistinguishable from a parse
# that found nothing. The fixture below is real `ioreg -r -d 1 -c AGXAccelerator`
# output, truncated, with the utilisation value substituted.
# ---------------------------------------------------------------------------

_IOREG_SAMPLE = """
+-o AGXAcceleratorG16X  <class AGXAcceleratorG16X, id 0x10000041e, registered>
    {
      "IOPlatformSleepAction" = 4294967300
      "PerformanceStatistics" = {"Alloc system memory"=1105920,"In use system memory"=0}
      "Device Utilization %"=__UTIL__
      "GPUConfigurationVariable" = {"num_cores"=40,"gpu_gen"=16}
      "IOClass" = "AGXAcceleratorG16X"
    }
"""


def _ioreg_output(util: int) -> str:
    """Real ioreg output with the utilisation value substituted.

    `str.format` is unusable here: ioreg prints nested dict literals, so the sample
    is full of unescaped braces.
    """
    return _IOREG_SAMPLE.replace("__UTIL__", str(util))


def test_parses_utilization_from_real_ioreg_output() -> None:
    """The regex must find the value in genuine ioreg output, not just a stub."""
    assert _parse_ioreg_utilization(_ioreg_output(37)) == 37.0
    assert _parse_ioreg_utilization(_ioreg_output(0)) == 0.0
    assert _parse_ioreg_utilization(_ioreg_output(100)) == 100.0


def test_parses_zero_when_key_is_absent() -> None:
    """A non-Apple host, or a driver without the key, reports 0.0 rather than raising."""
    assert _parse_ioreg_utilization("") == 0.0
    assert _parse_ioreg_utilization('+-o SomeOtherDevice\n  { "IOClass" = "x" }') == 0.0


def test_clamps_an_out_of_range_utilization() -> None:
    """A driver reporting above 100 must not inflate a node's score."""
    assert _parse_ioreg_utilization('"Device Utilization %"=250') == 100.0


def test_live_ioreg_read_returns_a_valid_percentage() -> None:
    """The real call must stay in range on this host, whatever the GPU is doing.

    Deliberately does not assert a non-zero value: the GPU is usually idle, so that
    would be flaky. The parse itself is covered above.
    """
    assert 0.0 <= _apple_gpu_utilization() <= 100.0
