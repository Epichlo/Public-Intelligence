"""Tests for the ZenohHeartbeatClient."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from node.clients.zenoh_heartbeat import ZenohHeartbeatClient
from node.core.configuration import Settings
from node.models import Heartbeat


@pytest.fixture
def settings() -> Settings:
    return Settings(
        node_id="test-node-zenoh",
        hostname="localhost",
        region="local",
        heartbeat_interval_seconds=1,
    )


def test_zenoh_client_start_stop(settings: Settings) -> None:
    client = ZenohHeartbeatClient(settings)

    with patch("zenoh.open") as mock_open:
        mock_session = MagicMock()
        mock_open.return_value = mock_session

        client.start()

        assert client.session is mock_session
        mock_open.assert_called_once()
        mock_session.declare_publisher.assert_called_once_with(
            "public-intelligence/net/test-node-zenoh/heartbeat"
        )

        # Stop client
        client.stop()
        assert client.session is None
        mock_session.close.assert_called_once()


def test_zenoh_client_publish(settings: Settings) -> None:
    client = ZenohHeartbeatClient(settings)

    # Try to publish before start
    hb = Heartbeat(
        node_id="test-node-zenoh",
        timestamp=datetime.now(timezone.utc),
        queue_length=2,
        cpu_utilization=10.0,
        ram_available_gb=8.0,
        gpu_utilization=0.0,
        vram_available_gb=0.0,
    )

    with pytest.raises(RuntimeError, match="Zenoh session is not active"):
        client.publish(hb)

    with patch("zenoh.open") as mock_open:
        mock_session = MagicMock()
        mock_publisher = MagicMock()
        mock_session.declare_publisher.return_value = mock_publisher
        mock_open.return_value = mock_session

        client.start()
        client.publish(hb)

        mock_publisher.put.assert_called_once()
        # Verify JSON contains expected fields
        put_arg = mock_publisher.put.call_args[0][0]
        payload = json.loads(put_arg)
        assert payload["node_id"] == "test-node-zenoh"
        assert payload["status"] == "online"
        assert payload["queue_length"] == 2
        assert payload["cpu_utilization"] == 10.0

        client.stop()
