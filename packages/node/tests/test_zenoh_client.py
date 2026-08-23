"""Tests for the ZenohHeartbeatClient."""

import json
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from node.clients.zenoh_heartbeat import ZenohHeartbeatClient
from node.core.configuration import Settings
from node.core.mesh_auth import PURPOSE_HEARTBEAT, open_envelope
from node.models import Heartbeat


@pytest.fixture
def settings() -> Settings:
    return Settings(
        node_id="test-node-zenoh",
        hostname="localhost",
        region="local",
        heartbeat_interval_seconds=1,
        # Heartbeats are sealed with a key derived from this since ROADMAP 2.7. The
        # client refuses to publish without one, because the Scheduler would drop
        # an unsigned frame and publishing it would only look like it worked.
        network_auth_token="per-install-credential-for-tests",
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
        timestamp=datetime.now(UTC),
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
        # The payload is a SEALED envelope since ROADMAP 2.7, not plain JSON --
        # opened here with the same credential the client signed it with, which is
        # also what proves the two ends agree.
        put_arg = mock_publisher.put.call_args[0][0]
        payload = open_envelope(
            put_arg,
            node_id=settings.node_id,
            token=settings.network_auth_token or "",
            purpose=PURPOSE_HEARTBEAT,
        )
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


def test_publish_failures_flip_is_connected_false_after_the_window(settings: Settings) -> None:
    """A dead transport must age out of is_connected without any local teardown.

    `is_connected` used to be `self.session is not None`, which stays true
    forever after a mid-life transport drop -- /health/ready reported a live
    WAN over a link that carried nothing. Liveness now comes from confirmed
    publishes, so simulated failures plus an elapsed window flip it False.
    """
    hb = Heartbeat(
        node_id="test-node-zenoh",
        timestamp=datetime.now(UTC),
        queue_length=0,
        cpu_utilization=10.0,
        ram_available_gb=8.0,
        gpu_utilization=0.0,
        vram_available_gb=0.0,
    )

    with patch("zenoh.open") as mock_open:
        mock_session = MagicMock()
        mock_publisher = MagicMock()
        mock_session.declare_publisher.return_value = mock_publisher
        mock_open.return_value = mock_session

        client = ZenohHeartbeatClient(settings)
        # Shrink the real window (2x heartbeat_interval_seconds); the test
        # measures actual elapsed time against it.
        client.staleness_window_seconds = 0.05

        client.start()
        assert client.is_connected()

        client.publish(hb)
        assert client.is_connected()
        assert client.seconds_since_last_publish() is not None

        # The transport dies: every publish fails from here on. No stop(), no
        # session teardown -- the session OBJECT is untouched.
        mock_publisher.put.side_effect = OSError("zenoh link down")
        with pytest.raises(OSError):
            client.publish(hb)
        with pytest.raises(OSError):
            client.publish(hb)

        time.sleep(0.06)
        assert not client.is_connected()
        assert client.session is not None  # nothing was torn down

        # Recovery: one confirmed publish restores the evidence.
        mock_publisher.put.side_effect = None
        client.publish(hb)
        assert client.is_connected()

        client.stop()


def test_seconds_since_last_publish_is_none_before_any_publish(settings: Settings) -> None:
    """A never-published client has no evidence to report an age for."""
    client = ZenohHeartbeatClient(settings)
    assert client.seconds_since_last_publish() is None


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
