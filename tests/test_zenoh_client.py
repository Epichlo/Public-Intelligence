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
        mock_liveliness = MagicMock()
        mock_session.liveliness.return_value = mock_liveliness
        mock_token = MagicMock()
        mock_liveliness.declare_token.return_value = mock_token

        client.start()

        assert client.session is mock_session
        mock_open.assert_called_once()
        mock_session.declare_publisher.assert_called_once_with(
            "public-intelligence/net/test-node-zenoh/heartbeat"
        )
        mock_liveliness.declare_token.assert_called_once_with(
            "public-intelligence/net/liveliness/test-node-zenoh"
        )
        assert client.liveliness_token is mock_token

        # Stop client
        client.stop()
        assert client.session is None
        assert client.liveliness_token is None
        mock_token.undeclare.assert_called_once()
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


def test_zenoh_client_wan_configuration() -> None:
    wan_settings = Settings(
        node_id="test-node-wan",
        zenoh_router_url="tcp/router.public-intelligence.net:7447",
        zenoh_peer_endpoints=["tcp/peer1:7447"],
        bootstrap_routers=["tcp/bootstrap.public-intelligence.net:7447"],
        zenoh_multicast_scouting=False,
    )
    client = ZenohHeartbeatClient(wan_settings)

    with patch("zenoh.open") as mock_open, patch("zenoh.Config") as mock_config_cls:
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config
        mock_session = MagicMock()
        mock_open.return_value = mock_session

        client.start()

        mock_config.insert_json5.assert_any_call(
            "connect/endpoints",
            json.dumps(
                [
                    "tcp/router.public-intelligence.net:7447",
                    "tcp/peer1:7447",
                    "tcp/bootstrap.public-intelligence.net:7447",
                ]
            ),
        )
        mock_config.insert_json5.assert_any_call("mode", '"client"')
        mock_config.insert_json5.assert_any_call("scouting/multicast/enabled", "false")
        mock_config.insert_json5.assert_any_call("scouting/gossip/enabled", "true")
        client.stop()


def test_zenoh_client_is_connected(settings: Settings) -> None:
    client = ZenohHeartbeatClient(settings)
    assert not client.is_connected()

    with patch("zenoh.open") as mock_open:
        mock_session = MagicMock()
        mock_open.return_value = mock_session

        client.start()
        assert client.is_connected()

        client.stop()
        assert not client.is_connected()


def test_zenoh_client_bootstrap_fallback_and_gossip_scouting() -> None:
    bootstrap_settings = Settings(
        node_id="test-node-bootstrap",
        bootstrap_routers=["tcp/bootstrap.public-intelligence.net:7447"],
        zenoh_gossip_scouting=True,
    )
    client = ZenohHeartbeatClient(bootstrap_settings)

    with patch("zenoh.open") as mock_open, patch("zenoh.Config") as mock_config_cls:
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config
        mock_session = MagicMock()
        mock_open.return_value = mock_session

        client.start()

        mock_config.insert_json5.assert_any_call(
            "connect/endpoints",
            json.dumps(["tcp/bootstrap.public-intelligence.net:7447"]),
        )
        mock_config.insert_json5.assert_any_call("mode", '"client"')
        mock_config.insert_json5.assert_any_call("scouting/gossip/enabled", "true")
        client.stop()


def test_zenoh_client_gossip_scouting_disabled() -> None:
    disabled_settings = Settings(
        node_id="test-node-gossip-disabled",
        zenoh_gossip_scouting=False,
    )
    client = ZenohHeartbeatClient(disabled_settings)

    with patch("zenoh.open") as mock_open, patch("zenoh.Config") as mock_config_cls:
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config
        mock_session = MagicMock()
        mock_open.return_value = mock_session

        client.start()

        mock_config.insert_json5.assert_any_call("scouting/gossip/enabled", "false")
        client.stop()
