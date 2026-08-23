"""Unit tests for resource telemetry collection.

The `ZenohTelemetryHeartbeat` that used to share this file is gone: it
published plaintext JSON on the telemetry topic, which the Scheduler's
authenticated-mesh-ingress gate silently drops -- a publisher whose every
frame vanished without an error, and whose only observable effect would
have been nodes aging out of the registry. Production telemetry goes
through `node.core.telemetry.TelemetryEmitter`, which seals envelopes.
tests/test_unsigned_telemetry_heartbeat_is_gone.py pins the removal.
"""

import pytest

from node.telemetry.collector import TelemetryCollector


@pytest.mark.anyio
async def test_telemetry_collector_types() -> None:
    """Verify that the collector outputs expected types and ranges."""
    collector = TelemetryCollector()
    metrics = await collector.collect()

    # 1. Assert CPU & Memory type specifications
    assert isinstance(metrics["cpu_utilization"], float)
    assert isinstance(metrics["cpu_cores"], int)
    assert isinstance(metrics["ram_total_bytes"], int)
    assert isinstance(metrics["ram_available_bytes"], int)
    assert isinstance(metrics["ram_used_bytes"], int)
    assert isinstance(metrics["ram_utilization_pct"], float)

    # 2. Assert GPU/VRAM type specifications
    assert isinstance(metrics["gpu_name"], str)
    assert isinstance(metrics["gpu_utilization"], float)
    assert isinstance(metrics["vram_total_bytes"], int)
    assert isinstance(metrics["vram_available_bytes"], int)
    assert isinstance(metrics["vram_used_bytes"], int)

    # 3. Assert value bounds
    assert metrics["cpu_cores"] >= 1
    assert metrics["ram_total_bytes"] > 0
    assert 0.0 <= metrics["ram_utilization_pct"] <= 100.0
