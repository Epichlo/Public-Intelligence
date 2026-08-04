"""Tests for real host hardware discovery used at registration (roadmap 1.2).

Registration previously advertised a hardcoded `{"name": "unknown",
"vram_total_gb": 16.0, "vram_available_gb": 16.0}` for every node regardless of
hardware, so the Scheduler's matchmaking filtered and scored against fiction.
These cover the three real shapes a host can take, and the failure paths.
"""

from typing import Any
from unittest.mock import patch

import psutil
import pytest

from node.core.hardware import CPU_ONLY_GPU_NAME, detect_gpu, detect_ram_total_gb

GIB = 1024**3


class _FakeCollector:
    """Stands in for TelemetryCollector with a fixed nvidia-smi result."""

    def __init__(self, gpu: dict[str, Any] | None = None, raises: bool = False) -> None:
        self._gpu = gpu
        self._raises = raises

    async def _collect_gpu_metrics(self) -> dict[str, Any]:
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


def _apple_silicon(unified_gb: float = 36.0) -> dict[str, Any]:
    return {
        "is_apple_silicon": True,
        "chip_family": "Apple M3 Max",
        "unified_memory_gb": unified_gb,
        "metal_supported": True,
    }


def _nvidia(name: str = "NVIDIA GeForce RTX 4090", total_gb: float = 24.0,
            free_gb: float = 20.0) -> dict[str, Any]:
    return {
        "name": name,
        "utilization": 12.0,
        "vram_total_bytes": int(total_gb * GIB),
        "vram_available_bytes": int(free_gb * GIB),
        "vram_used_bytes": int((total_gb - free_gb) * GIB),
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
async def test_detect_gpu_reports_real_nvidia_values() -> None:
    """An NVIDIA host advertises the name and VRAM nvidia-smi actually reported."""
    collector = _FakeCollector(_nvidia())

    with patch("node.core.hardware.detect_apple_silicon_hardware", _no_apple_silicon):
        gpu = await detect_gpu(collector)

    assert gpu.name == "NVIDIA GeForce RTX 4090"
    assert gpu.vram_total_gb == pytest.approx(24.0, abs=0.01)
    assert gpu.vram_available_gb == pytest.approx(20.0, abs=0.01)


@pytest.mark.anyio
async def test_detect_gpu_prefers_nvidia_over_apple_silicon() -> None:
    """A discrete NVIDIA card wins over unified memory when both are present."""
    collector = _FakeCollector(_nvidia())

    with patch("node.core.hardware.detect_apple_silicon_hardware", _apple_silicon):
        gpu = await detect_gpu(collector)

    assert gpu.name == "NVIDIA GeForce RTX 4090"
    assert gpu.vram_total_gb == pytest.approx(24.0, abs=0.01)


@pytest.mark.anyio
async def test_detect_gpu_reports_apple_silicon_unified_memory() -> None:
    """Metal genuinely uses unified memory as VRAM, so it is advertised as such."""
    collector = _FakeCollector(_no_gpu())

    with patch("node.core.hardware.detect_apple_silicon_hardware", _apple_silicon):
        gpu = await detect_gpu(collector)

    assert gpu.name == "Apple M3 Max"
    assert gpu.vram_total_gb == pytest.approx(36.0, abs=0.01)
    # Unified memory is shared with the OS, so what is free is what psutil says
    # is free -- never more than the total.
    assert 0.0 <= gpu.vram_available_gb <= 36.0


@pytest.mark.anyio
async def test_detect_gpu_reports_zero_on_cpu_only_host() -> None:
    """A host with no GPU says 0 GB rather than inventing 16."""
    collector = _FakeCollector(_no_gpu())

    with patch("node.core.hardware.detect_apple_silicon_hardware", _no_apple_silicon):
        gpu = await detect_gpu(collector)

    assert gpu.name == CPU_ONLY_GPU_NAME
    assert gpu.vram_total_gb == 0.0
    assert gpu.vram_available_gb == 0.0


@pytest.mark.anyio
async def test_detect_gpu_degrades_when_collection_raises() -> None:
    """Hardware discovery failing must not block registration."""
    collector = _FakeCollector(raises=True)

    with patch("node.core.hardware.detect_apple_silicon_hardware", _no_apple_silicon):
        gpu = await detect_gpu(collector)

    assert gpu.name == CPU_ONLY_GPU_NAME
    assert gpu.vram_total_gb == 0.0


@pytest.mark.anyio
async def test_detect_gpu_degrades_when_apple_probe_raises() -> None:
    """A sysctl failure degrades to cpu-only rather than propagating."""
    collector = _FakeCollector(_no_gpu())

    def _boom() -> dict[str, Any]:
        raise OSError("sysctl unavailable")

    with patch("node.core.hardware.detect_apple_silicon_hardware", _boom):
        gpu = await detect_gpu(collector)

    assert gpu.name == CPU_ONLY_GPU_NAME
    assert gpu.vram_total_gb == 0.0


@pytest.mark.anyio
async def test_detect_gpu_clamps_available_above_total() -> None:
    """A driver reporting more free than total is clamped, not passed through."""
    collector = _FakeCollector(_nvidia(total_gb=8.0, free_gb=12.0))

    with patch("node.core.hardware.detect_apple_silicon_hardware", _no_apple_silicon):
        gpu = await detect_gpu(collector)

    assert gpu.vram_total_gb == pytest.approx(8.0, abs=0.01)
    assert gpu.vram_available_gb == pytest.approx(8.0, abs=0.01)


@pytest.mark.anyio
async def test_detect_gpu_uses_real_collector_by_default() -> None:
    """Called with no collector it still returns a usable, non-negative profile."""
    gpu = await detect_gpu()

    assert gpu.name
    assert gpu.vram_total_gb >= 0.0
    assert 0.0 <= gpu.vram_available_gb <= max(gpu.vram_total_gb, 0.0) or gpu.vram_total_gb == 0.0


def test_detect_ram_total_gb_matches_psutil() -> None:
    """Total RAM is read from the host, not the hardcoded 16.0 it used to return."""
    expected = psutil.virtual_memory().total / GIB

    assert detect_ram_total_gb() == pytest.approx(expected, abs=0.01)
    assert detect_ram_total_gb() > 0.0
