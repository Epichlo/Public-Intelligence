"""Unit tests for resource telemetry collection and Zenoh heartbeat loops."""

from unittest.mock import MagicMock, patch

import pytest

from node.core.configuration import Settings
from node.telemetry.collector import TelemetryCollector
from node.telemetry.heartbeat import ZenohTelemetryHeartbeat


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


@pytest.mark.anyio
async def test_zenoh_telemetry_heartbeat_uri() -> None:
    """Verify that the telemetry channel URI matches specification."""
    settings = Settings(
        node_id="test-node-555",
        hostname="localhost",
        region="us-east",
    )
    heartbeat = ZenohTelemetryHeartbeat(settings=settings)
    assert heartbeat._key_expr == "public-intelligence/net/nodes/test-node-555/telemetry"


@pytest.mark.anyio
async def test_zenoh_telemetry_heartbeat_lifecycle() -> None:
    """Verify start, stop, and deadman offline packet publish behaviors."""
    settings = Settings(
        node_id="test-node-555",
        hostname="localhost",
        region="us-east",
    )

    mock_pub = MagicMock()
    mock_pub.undeclare = MagicMock()
    mock_pub.put = MagicMock()

    mock_session = MagicMock()
    mock_session.declare_publisher.return_value = mock_pub
    mock_session.close = MagicMock()

    with patch("zenoh.open", return_value=mock_session):
        heartbeat = ZenohTelemetryHeartbeat(settings=settings)
        await heartbeat.start()

        assert heartbeat.is_running is True
        assert heartbeat.session == mock_session
        assert heartbeat.publisher == mock_pub

        # Stop triggers graceful exit frame
        await heartbeat.stop()

        assert heartbeat.is_running is False
        assert heartbeat.session is None

        # Assert correct deadman switch payload
        mock_pub.put.assert_called_with(
            '{"node_id": "test-node-555", "status": "OFFLINE", '
            '"cpu_utilization": 0.0, "ram_utilization_pct": 0.0, '
            '"gpu_utilization": 0.0}'
        )
