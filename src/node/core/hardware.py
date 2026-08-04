"""Real host hardware discovery for node registration (roadmap 1.2).

Registration used to advertise `{"name": "unknown", "vram_total_gb": 16.0,
"vram_available_gb": 16.0}` for every node regardless of what the machine was, so
the Scheduler filtered on `min_vram_gb` and scored by VRAM ratio against numbers
nobody had measured. This reads the host instead.

Detection order, and why:

1. **NVIDIA via `nvidia-smi`** -- a discrete card is the real thing, so it wins
   whenever one is present.
2. **Apple Silicon unified memory** -- Metal genuinely allocates model weights out
   of unified memory, so reporting it as VRAM is accurate rather than generous.
   It is shared with the OS, which is why `vram_available_gb` comes from psutil.
3. **Neither** -- `cpu-only` with 0 GB. Honest, and it excludes the node from every
   task with a VRAM floor, which is the correct outcome.

Every probe is wrapped: a host whose `nvidia-smi` hangs, whose `sysctl` is missing,
or whose driver reports nonsense degrades to (3) and still registers. Hardware
discovery must never be the reason a node fails to come up.
"""

import logging
from typing import Any

import psutil

from node.core.apple_silicon import detect_apple_silicon_hardware
from node.models.gpu_info import CPU_ONLY_GPU_NAME, GPUInfo, cpu_only_gpu

logger = logging.getLogger(__name__)

__all__ = ["CPU_ONLY_GPU_NAME", "detect_gpu", "detect_ram_total_gb"]

_BYTES_PER_GB = 1024**3


def _to_gb(value: Any) -> float:
    """Convert a byte count to GB, returning 0.0 for anything unusable."""
    try:
        return round(float(value) / _BYTES_PER_GB, 2)
    except (TypeError, ValueError):
        return 0.0


async def _detect_nvidia(collector: Any | None) -> GPUInfo | None:
    """Return NVIDIA GPU info, or None when there is no usable card."""
    if collector is None:
        from node.telemetry.collector import TelemetryCollector

        collector = TelemetryCollector()

    metrics = await collector.collect_gpu_metrics()

    name = str(metrics.get("name", "")).strip()
    total_gb = _to_gb(metrics.get("vram_total_bytes", 0))

    # The collector's own miss-signal is name "N/A" with zero bytes.
    if not name or name == "N/A" or total_gb <= 0.0:
        return None

    available_gb = _to_gb(metrics.get("vram_available_bytes", 0))
    return GPUInfo(
        name=name,
        vram_total_gb=total_gb,
        # A driver reporting more free than total is clamped rather than passed
        # through -- the Scheduler scores on available/total and a ratio above 1
        # would rank a broken node top.
        vram_available_gb=min(max(available_gb, 0.0), total_gb),
    )


def _detect_apple_silicon() -> GPUInfo | None:
    """Return unified-memory GPU info, or None when not Apple Silicon."""
    profile = detect_apple_silicon_hardware()
    if not profile.get("is_apple_silicon"):
        return None

    unified_gb = float(profile.get("unified_memory_gb") or 0.0)
    if unified_gb <= 0.0:
        return None

    # Unified memory is shared with the OS, so free system RAM is the honest
    # estimate of what Metal can still allocate. There is no separate pool.
    available_gb = min(round(psutil.virtual_memory().available / _BYTES_PER_GB, 2), unified_gb)

    name = str(profile.get("chip_family") or "Apple Silicon").strip()
    return GPUInfo(
        name=name or "Apple Silicon",
        vram_total_gb=unified_gb,
        vram_available_gb=max(available_gb, 0.0),
    )


async def detect_gpu(collector: Any | None = None) -> GPUInfo:
    """Detect the host's usable GPU for advertisement at registration.

    Args:
        collector: Optional object exposing `collect_gpu_metrics()`, used to
            inject a known nvidia-smi result in tests. Defaults to a real
            `TelemetryCollector`.

    Returns:
        Real hardware where it could be measured; `cpu-only` at 0 GB otherwise.
        Never raises -- see module docstring.
    """
    try:
        nvidia = await _detect_nvidia(collector)
        if nvidia is not None:
            return nvidia
    except Exception as e:
        logger.warning("NVIDIA GPU discovery failed, continuing: %s", e)

    try:
        apple = _detect_apple_silicon()
        if apple is not None:
            return apple
    except Exception as e:
        logger.warning("Apple Silicon discovery failed, continuing: %s", e)

    logger.info("No GPU detected; advertising %s with 0 GB VRAM.", CPU_ONLY_GPU_NAME)
    return cpu_only_gpu()


def detect_ram_total_gb() -> float:
    """Total system RAM in gigabytes.

    Falls back to 1.0 rather than 0.0 only because the Scheduler's `Node` model
    requires `ram_total_gb > 0`; psutil failing here is not a real scenario on
    any platform the installer supports.
    """
    try:
        return round(psutil.virtual_memory().total / _BYTES_PER_GB, 2)
    except Exception as e:
        logger.warning("RAM discovery failed, advertising minimum: %s", e)
        return 1.0
