"""Real host hardware discovery (roadmap 1.2 and 1.3).

Two things used to be invented rather than measured:

- **Registration** (1.2) advertised `{"name": "unknown", "vram_total_gb": 16.0,
  "vram_available_gb": 16.0}` for every node regardless of what the machine was.
- **Heartbeats** (1.3) reported `cpu 15.0`, `ram_available_gb 8.0`,
  `gpu_utilization 0.0`, `vram_available_gb 0.0` on every beat, forever.

The Scheduler filters on the heartbeat's `vram_available_gb` and scores on all four,
so the second was the more damaging: a node reporting a constant 0.0 was excluded
from every task carrying a VRAM floor and scored identically to every other node.

Both now come from `_probe_gpu`, so the static advertisement and the live report
cannot disagree about what the GPU is. Detection order, and why:

1. **NVIDIA via `nvidia-smi`** -- a discrete card is the real thing, so it wins
   whenever one is present, and it reports both free VRAM and utilisation.
2. **Apple Silicon** -- Metal genuinely allocates model weights out of unified
   memory, so reporting it as VRAM is accurate rather than generous. It is shared
   with the OS, which is why free VRAM comes from psutil; utilisation comes from
   `ioreg`, which is readable without sudo.
3. **Neither** -- `cpu-only` with 0 GB. Honest, and it excludes the node from every
   task with a VRAM floor, which is the correct outcome.

Every probe is wrapped: a host whose `nvidia-smi` hangs, whose `sysctl` is missing,
or whose driver reports nonsense degrades to (3) and still registers and heartbeats.
Hardware discovery must never be why a node fails to come up or goes silent and gets
evicted.
"""

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

import psutil

from node.core.apple_silicon import detect_apple_silicon_hardware
from node.models.gpu_info import CPU_ONLY_GPU_NAME, GPUInfo, cpu_only_gpu

logger = logging.getLogger(__name__)

__all__ = [
    "CPU_ONLY_GPU_NAME",
    "HostMetrics",
    "detect_gpu",
    "detect_host_metrics",
    "detect_ram_total_gb",
]

_BYTES_PER_GB = 1024**3

# ioreg prints the accelerator's properties as a flat dict literal; this is the
# GPU-busy percentage Activity Monitor shows.
_IOREG_UTILIZATION = re.compile(r'"Device Utilization %"\s*=\s*(\d+)')


@dataclass(frozen=True)
class HostMetrics:
    """Live host utilisation, sent on every heartbeat."""

    cpu_utilization: float
    ram_available_gb: float
    gpu_utilization: float
    vram_available_gb: float


@dataclass(frozen=True)
class _GpuProbe:
    """A GPU as measured: its capacity, plus how busy it is right now."""

    info: GPUInfo
    utilization: float


def _to_gb(value: Any) -> float:
    """Convert a byte count to GB, returning 0.0 for anything unusable."""
    try:
        return round(float(value) / _BYTES_PER_GB, 2)
    except (TypeError, ValueError):
        return 0.0


def _available_ram_gb() -> float:
    """Free system RAM in gigabytes."""
    return round(psutil.virtual_memory().available / _BYTES_PER_GB, 2)


def _parse_ioreg_utilization(stdout: str) -> float:
    """Extract GPU busy percentage from `ioreg -c AGXAccelerator` output.

    Split out from `_apple_gpu_utilization` so the parse is testable. It cannot be
    covered through the live call: on an idle machine the real figure is legitimately
    0.0, which is indistinguishable from a parse that silently found nothing.

    Returns 0.0 when the key is absent, which is also what a non-Apple host yields.
    """
    match = _IOREG_UTILIZATION.search(stdout)
    if match is None:
        return 0.0
    return min(max(float(match.group(1)), 0.0), 100.0)


def _apple_gpu_utilization() -> float:
    """Read Apple Silicon GPU busy percentage from ioreg.

    Returns 0.0 when ioreg is unavailable. This needs no elevated privileges,
    unlike `powermetrics`, which is why it is used here.
    """
    ioreg = shutil.which("ioreg")
    if not ioreg:
        return 0.0

    proc = subprocess.run(  # noqa: S603
        [ioreg, "-r", "-d", "1", "-w", "0", "-c", "AGXAccelerator"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    return _parse_ioreg_utilization(proc.stdout)


async def _detect_nvidia(collector: Any | None) -> _GpuProbe | None:
    """Return an NVIDIA probe, or None when there is no usable card."""
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
    info = GPUInfo(
        name=name,
        vram_total_gb=total_gb,
        # A driver reporting more free than total is clamped rather than passed
        # through -- the Scheduler scores on available/total and a ratio above 1
        # would rank a broken node top.
        vram_available_gb=min(max(available_gb, 0.0), total_gb),
    )
    utilization = min(max(float(metrics.get("utilization") or 0.0), 0.0), 100.0)
    return _GpuProbe(info=info, utilization=utilization)


def _detect_apple_silicon() -> _GpuProbe | None:
    """Return a unified-memory probe, or None when not Apple Silicon."""
    profile = detect_apple_silicon_hardware()
    if not profile.get("is_apple_silicon"):
        return None

    unified_gb = float(profile.get("unified_memory_gb") or 0.0)
    if unified_gb <= 0.0:
        return None

    # Unified memory is shared with the OS, so free system RAM is the honest
    # estimate of what Metal can still allocate. There is no separate pool.
    available_gb = min(_available_ram_gb(), unified_gb)

    name = str(profile.get("chip_family") or "Apple Silicon").strip()
    info = GPUInfo(
        name=name or "Apple Silicon",
        vram_total_gb=unified_gb,
        vram_available_gb=max(available_gb, 0.0),
    )

    try:
        utilization = _apple_gpu_utilization()
    except Exception as e:
        logger.warning("Apple GPU utilisation read failed, reporting 0.0: %s", e)
        utilization = 0.0

    return _GpuProbe(info=info, utilization=utilization)


async def _probe_gpu(collector: Any | None = None) -> _GpuProbe:
    """Measure the host GPU once. Never raises; degrades to cpu-only at 0 GB.

    Single source of truth for both registration (1.2) and heartbeats (1.3), so a
    node cannot advertise 24 GB total and then heartbeat 0 GB free on the same card.
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

    logger.info("No GPU detected; reporting %s with 0 GB VRAM.", CPU_ONLY_GPU_NAME)
    return _GpuProbe(info=cpu_only_gpu(), utilization=0.0)


async def detect_gpu(collector: Any | None = None) -> GPUInfo:
    """Detect the host's usable GPU for advertisement at registration.

    Args:
        collector: Optional object exposing `collect_gpu_metrics()`, used to
            inject a known nvidia-smi result in tests. Defaults to a real
            `TelemetryCollector`.

    Returns:
        Real hardware where it could be measured; `cpu-only` at 0 GB otherwise.
    """
    return (await _probe_gpu(collector)).info


async def detect_host_metrics(collector: Any | None = None) -> HostMetrics:
    """Measure current host utilisation for a heartbeat.

    Note on CPU: `psutil.cpu_percent(interval=None)` returns 0.0 on its first call
    in a process and is meaningful from the second onward. The heartbeat loop calls
    this repeatedly, so it self-corrects after one interval -- but the first
    heartbeat a node ever sends under-reports CPU. Blocking the loop on a sampling
    interval would be worse.

    Returns:
        Measured values, degrading to conservative ones on any probe failure. Never
        raises: a node that cannot read its own hardware must keep heartbeating
        rather than go silent and be evicted as stale.
    """
    probe = await _probe_gpu(collector)

    try:
        cpu_utilization = float(psutil.cpu_percent(interval=None))
    except Exception as e:
        logger.warning("CPU utilisation read failed, reporting 0.0: %s", e)
        cpu_utilization = 0.0

    try:
        ram_available_gb = _available_ram_gb()
    except Exception as e:
        logger.warning("RAM read failed, reporting 0.0: %s", e)
        ram_available_gb = 0.0

    return HostMetrics(
        cpu_utilization=min(max(cpu_utilization, 0.0), 100.0),
        ram_available_gb=max(ram_available_gb, 0.0),
        gpu_utilization=probe.utilization,
        vram_available_gb=probe.info.vram_available_gb,
    )


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
