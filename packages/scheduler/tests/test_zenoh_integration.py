"""Integration tests for the Zenoh router heartbeat transport."""

import asyncio
import base64
import json
from datetime import UTC, datetime

import pytest
import zenoh

from scheduler.core.mesh_auth import PURPOSE_HEARTBEAT, PURPOSE_TELEMETRY, seal
from scheduler.core.zenoh_router import ZenohRouter
from scheduler.models.node import GPUInfo, Node
from scheduler.registry.node_registry import NodeRegistry


@pytest.fixture()
def node_id() -> str:
    return "test-node-zenoh"


# Each node signs with its OWN credential since ROADMAP 2.7. These tests used to
# build envelopes from a fleet-wide TELEMETRY_SECRET_KEY whose default is a
# constant published in this repository.
MESH_TOKEN = "per-install-credential-for-tests"


@pytest.fixture()
def test_node(node_id: str) -> Node:
    return Node(
        node_id=node_id,
        hostname="test-host",
        ip_address="127.0.0.1",
        region="local",
        gpu=GPUInfo(name="unknown", vram_total_gb=16.0, vram_available_gb=16.0),
        cpu_cores=4,
        ram_total_gb=16.0,
        available_models=["llama2"],
    )


@pytest.mark.asyncio
async def test_zenoh_heartbeat_routing(test_node: Node, node_id: str) -> None:
    # 1. Create registry and register node
    registry = NodeRegistry()
    await registry.set_node_token(node_id, MESH_TOKEN)
    await registry.register(test_node)

    # Configure Router session to listen on TCP loopback and disable multicast scouting
    router_config = zenoh.Config()
    router_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:7449"]')
    router_config.insert_json5("scouting/multicast/enabled", "false")

    # 2. Start ZenohRouter with the custom configuration
    router = ZenohRouter(registry, config=router_config)
    router.start()

    # Configure Publisher session to connect directly to the Router TCP endpoint
    pub_config = zenoh.Config()
    pub_config.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7449"]')
    pub_config.insert_json5("scouting/multicast/enabled", "false")
    # An explicit IPv4 loopback listener. Without it zenoh falls back to its
    # default `tcp/[::]:0`, which is an IPv6 wildcard -- so every one of these
    # tests dies with EAFNOSUPPORT on an IPv4-only host (containers, CI images,
    # networks with IPv6 disabled). The assertions are untouched; this only makes
    # an environment assumption that was implicit into one that is stated.
    pub_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:0"]')

    try:
        # 3. Create a local Zenoh session and publisher to publish mock heartbeat
        with zenoh.open(pub_config) as session:
            pub_key = f"public-intelligence/net/{node_id}/heartbeat"
            publisher = session.declare_publisher(pub_key)

            # Wait a short moment to ensure the TCP handshake is fully complete
            await asyncio.sleep(0.2)

            heartbeat_data = {
                "node_id": node_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "status": "online",
                "queue_length": 3,
                "cpu_utilization": 25.5,
                "ram_available_gb": 12.0,
                "gpu_utilization": 50.0,
                "vram_available_gb": 8.0,
            }

            # Sealed since ROADMAP 2.7. Publishing `json.dumps(heartbeat_data)`
            # here -- which is what this test did, and what the node did -- is now
            # dropped by the router as unauthenticated.
            publisher.put(
                seal(
                    heartbeat_data,
                    node_id=node_id,
                    token=MESH_TOKEN,
                    purpose=PURPOSE_HEARTBEAT,
                )
            )
            publisher.undeclare()  # type: ignore[no-untyped-call]

        # 4. Wait for the background Zenoh threads to deliver and process the heartbeat
        # (needs a small sleep as callback delivery is asynchronous across threads)
        for _ in range(20):
            hb = await registry.get_heartbeat(node_id)
            if hb is not None:
                break
            await asyncio.sleep(0.05)

        # 5. Verify the registry updated the heartbeat successfully
        hb = await registry.get_heartbeat(node_id)
        assert hb is not None, "Heartbeat was not processed by ZenohRouter"
        assert hb.node_id == node_id
        assert hb.queue_length == 3
        assert hb.cpu_utilization == 25.5
        assert hb.ram_available_gb == 12.0
        assert hb.gpu_utilization == 50.0
        assert hb.vram_available_gb == 8.0

        # Verify the dampener invariant was decayed to 0.0 on heartbeat update
        dampener = await registry.get_dampener(node_id)
        assert dampener == 0.0

    finally:
        # 6. Stop ZenohRouter cleanly
        router.stop()


@pytest.mark.asyncio
async def test_zenoh_liveliness_deathrattle(test_node: Node, node_id: str) -> None:
    # 1. Create registry and register node
    registry = NodeRegistry()
    await registry.set_node_token(node_id, MESH_TOKEN)
    await registry.register(test_node)
    assert await registry.exists(node_id) is True

    # Configure Router session to listen on TCP loopback and disable multicast scouting
    router_config = zenoh.Config()
    router_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:7450"]')
    router_config.insert_json5("scouting/multicast/enabled", "false")

    # 2. Start ZenohRouter with the custom configuration
    router = ZenohRouter(registry, config=router_config)
    router.start()

    # Configure Publisher session to connect directly to the Router TCP endpoint
    pub_config = zenoh.Config()
    pub_config.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7450"]')
    pub_config.insert_json5("scouting/multicast/enabled", "false")
    # An explicit IPv4 loopback listener. Without it zenoh falls back to its
    # default `tcp/[::]:0`, which is an IPv6 wildcard -- so every one of these
    # tests dies with EAFNOSUPPORT on an IPv4-only host (containers, CI images,
    # networks with IPv6 disabled). The assertions are untouched; this only makes
    # an environment assumption that was implicit into one that is stated.
    pub_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:0"]')

    try:
        # 3. Create a local Zenoh session and declare a liveliness token
        session = zenoh.open(pub_config)
        token_path = f"public-intelligence/net/liveliness/{node_id}"
        token = session.liveliness().declare_token(token_path)

        # Wait a short moment to ensure the TCP handshake is fully complete
        await asyncio.sleep(0.2)

        # 4. Now simulate sudden node session drop by closing the session abruptly
        token.undeclare()  # type: ignore[no-untyped-call]
        session.close()  # type: ignore[no-untyped-call]

        # 5. Wait for the background Zenoh threads to process the deathrattle (DELETE event)
        for _ in range(30):
            exists = await registry.exists(node_id)
            if not exists:
                break
            await asyncio.sleep(0.05)

        # 6. Verify the registry unregistered the node successfully
        assert not await registry.exists(node_id), "Node not unregistered on deathrattle"

    finally:
        # 7. Stop ZenohRouter cleanly
        router.stop()


@pytest.mark.asyncio
async def test_zenoh_telemetry_mapping(test_node: Node, node_id: str) -> None:
    # 1. Create registry and register node
    registry = NodeRegistry()
    await registry.set_node_token(node_id, MESH_TOKEN)
    await registry.register(test_node)

    # Configure Router session to listen on TCP loopback
    router_config = zenoh.Config()
    router_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:7451"]')
    router_config.insert_json5("scouting/multicast/enabled", "false")

    # 2. Start ZenohRouter
    router = ZenohRouter(registry, config=router_config)
    router.start()

    # Configure Publisher session to connect directly to the Router TCP endpoint
    pub_config = zenoh.Config()
    pub_config.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7451"]')
    pub_config.insert_json5("scouting/multicast/enabled", "false")
    # An explicit IPv4 loopback listener. Without it zenoh falls back to its
    # default `tcp/[::]:0`, which is an IPv6 wildcard -- so every one of these
    # tests dies with EAFNOSUPPORT on an IPv4-only host (containers, CI images,
    # networks with IPv6 disabled). The assertions are untouched; this only makes
    # an environment assumption that was implicit into one that is stated.
    pub_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:0"]')

    try:
        # 3. Create a local Zenoh session and publisher
        with zenoh.open(pub_config) as session:
            pub_key = f"public-intelligence/net/nodes/{node_id}/telemetry"
            publisher = session.declare_publisher(pub_key)

            await asyncio.sleep(0.2)

            # Plaintext data
            telemetry_data = {
                "node_id": node_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "cpu_utilization": 42.5,
                "ram_usage_bytes": 10737418240,
                "gpu_utilization": 20.0,
                "vram_usage_bytes": 4294967296,
            }
            sealed = seal(
                telemetry_data,
                node_id=node_id,
                token=MESH_TOKEN,
                purpose=PURPOSE_TELEMETRY,
            )

            publisher.put(sealed)
            publisher.undeclare()  # type: ignore[no-untyped-call]

        # 4. Wait for background delivery
        for _ in range(30):
            if hasattr(registry, "_telemetry") and node_id in registry._telemetry:
                break
            await asyncio.sleep(0.05)

        # 5. Verify the telemetry state mapping
        assert hasattr(registry, "_telemetry"), "Registry does not have _telemetry state"
        mapped_data = registry._telemetry[node_id]
        assert mapped_data["node_id"] == node_id
        assert mapped_data["cpu_utilization"] == 42.5
        assert mapped_data["ram_usage_bytes"] == 10737418240
        assert mapped_data["gpu_utilization"] == 20.0
        assert mapped_data["vram_usage_bytes"] == 4294967296

    finally:
        router.stop()


@pytest.mark.asyncio
async def test_zenoh_telemetry_tampered_payload_rejection(test_node: Node, node_id: str) -> None:
    # 1. Create registry and register node
    registry = NodeRegistry()
    await registry.set_node_token(node_id, MESH_TOKEN)
    await registry.register(test_node)

    # Configure Router session to listen on TCP loopback
    router_config = zenoh.Config()
    router_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:7452"]')
    router_config.insert_json5("scouting/multicast/enabled", "false")

    # 2. Start ZenohRouter
    router = ZenohRouter(registry, config=router_config)
    router.start()

    # Configure Publisher session to connect directly to the Router TCP endpoint
    pub_config = zenoh.Config()
    pub_config.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7452"]')
    pub_config.insert_json5("scouting/multicast/enabled", "false")
    # An explicit IPv4 loopback listener. Without it zenoh falls back to its
    # default `tcp/[::]:0`, which is an IPv6 wildcard -- so every one of these
    # tests dies with EAFNOSUPPORT on an IPv4-only host (containers, CI images,
    # networks with IPv6 disabled). The assertions are untouched; this only makes
    # an environment assumption that was implicit into one that is stated.
    pub_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:0"]')

    try:
        # 3. Create a local Zenoh session and publisher
        with zenoh.open(pub_config) as session:
            pub_key = f"public-intelligence/net/nodes/{node_id}/telemetry"
            publisher = session.declare_publisher(pub_key)

            await asyncio.sleep(0.2)

            # Plaintext data
            telemetry_data = {
                "node_id": node_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "cpu_utilization": 99.9,
            }
            # Seal it properly, THEN flip bytes in the ciphertext. Sealing with the
            # wrong key would also be rejected, but by the key lookup -- this pins
            # that a genuine envelope ALTERED IN FLIGHT is caught, which is the
            # AES-GCM authentication tag doing its job.
            envelope = json.loads(
                seal(
                    telemetry_data,
                    node_id=node_id,
                    token=MESH_TOKEN,
                    purpose=PURPOSE_TELEMETRY,
                )
            )
            tampered = bytearray(base64.b64decode(envelope["ciphertext"]))
            tampered[0] ^= 0xFF
            envelope["ciphertext"] = base64.b64encode(bytes(tampered)).decode()

            publisher.put(json.dumps(envelope))
            publisher.undeclare()  # type: ignore[no-untyped-call]

        # 4. Wait a short moment
        await asyncio.sleep(0.5)

        # 5. Verify the telemetry state remains unmutated (rejected payload)
        assert not hasattr(registry, "_telemetry") or node_id not in registry._telemetry

    finally:
        router.stop()


@pytest.mark.asyncio
async def test_zenoh_telemetry_stale_timestamp_rejection(test_node: Node, node_id: str) -> None:
    from datetime import timedelta

    registry = NodeRegistry()
    await registry.set_node_token(node_id, MESH_TOKEN)
    await registry.register(test_node)

    router_config = zenoh.Config()
    router_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:7453"]')
    router_config.insert_json5("scouting/multicast/enabled", "false")

    router = ZenohRouter(registry, config=router_config)
    router.start()

    pub_config = zenoh.Config()
    pub_config.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7453"]')
    pub_config.insert_json5("scouting/multicast/enabled", "false")
    # An explicit IPv4 loopback listener. Without it zenoh falls back to its
    # default `tcp/[::]:0`, which is an IPv6 wildcard -- so every one of these
    # tests dies with EAFNOSUPPORT on an IPv4-only host (containers, CI images,
    # networks with IPv6 disabled). The assertions are untouched; this only makes
    # an environment assumption that was implicit into one that is stated.
    pub_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:0"]')

    try:
        with zenoh.open(pub_config) as session:
            pub_key = f"public-intelligence/net/nodes/{node_id}/telemetry"
            publisher = session.declare_publisher(pub_key)

            await asyncio.sleep(0.2)

            stale_time = datetime.now(UTC) - timedelta(seconds=35)
            telemetry_data = {
                "node_id": node_id,
                "timestamp": stale_time.isoformat(),
                "cpu_utilization": 50.0,
            }
            sealed = seal(
                telemetry_data,
                node_id=node_id,
                token=MESH_TOKEN,
                purpose=PURPOSE_TELEMETRY,
            )

            publisher.put(sealed)
            publisher.undeclare()  # type: ignore[no-untyped-call]

        await asyncio.sleep(0.5)

        assert not hasattr(registry, "_telemetry") or node_id not in registry._telemetry

    finally:
        router.stop()


@pytest.mark.asyncio
async def test_zenoh_telemetry_future_timestamp_rejection(test_node: Node, node_id: str) -> None:
    from datetime import timedelta

    registry = NodeRegistry()
    await registry.set_node_token(node_id, MESH_TOKEN)
    await registry.register(test_node)

    router_config = zenoh.Config()
    router_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:7454"]')
    router_config.insert_json5("scouting/multicast/enabled", "false")

    router = ZenohRouter(registry, config=router_config)
    router.start()

    pub_config = zenoh.Config()
    pub_config.insert_json5("connect/endpoints", '["tcp/127.0.0.1:7454"]')
    pub_config.insert_json5("scouting/multicast/enabled", "false")
    # An explicit IPv4 loopback listener. Without it zenoh falls back to its
    # default `tcp/[::]:0`, which is an IPv6 wildcard -- so every one of these
    # tests dies with EAFNOSUPPORT on an IPv4-only host (containers, CI images,
    # networks with IPv6 disabled). The assertions are untouched; this only makes
    # an environment assumption that was implicit into one that is stated.
    pub_config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:0"]')

    try:
        with zenoh.open(pub_config) as session:
            pub_key = f"public-intelligence/net/nodes/{node_id}/telemetry"
            publisher = session.declare_publisher(pub_key)

            await asyncio.sleep(0.2)

            future_time = datetime.now(UTC) + timedelta(seconds=15)
            telemetry_data = {
                "node_id": node_id,
                "timestamp": future_time.isoformat(),
                "cpu_utilization": 50.0,
            }
            sealed = seal(
                telemetry_data,
                node_id=node_id,
                token=MESH_TOKEN,
                purpose=PURPOSE_TELEMETRY,
            )

            publisher.put(sealed)
            publisher.undeclare()  # type: ignore[no-untyped-call]

        await asyncio.sleep(0.5)

        assert not hasattr(registry, "_telemetry") or node_id not in registry._telemetry

    finally:
        router.stop()


def test_zenoh_router_wan_configuration() -> None:
    from unittest.mock import MagicMock, patch

    from scheduler.core.config import Settings

    wan_settings = Settings(
        zenoh_listen_endpoints=["tcp/0.0.0.0:7447"],
        zenoh_peer_endpoints=["tcp/scheduler2:7447"],
        bootstrap_routers=["tcp/bootstrap.public-intelligence.net:7447"],
        zenoh_multicast_scouting=False,
        zenoh_gossip_scouting=True,
    )

    with (
        patch("scheduler.core.config.get_settings", return_value=wan_settings),
        patch("zenoh.Config") as mock_config_cls,
    ):
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config

        registry = NodeRegistry()
        ZenohRouter(registry)

        mock_config.insert_json5.assert_any_call(
            "listen/endpoints", json.dumps(["tcp/0.0.0.0:7447"])
        )
        mock_config.insert_json5.assert_any_call("mode", '"router"')
        mock_config.insert_json5.assert_any_call(
            "connect/endpoints",
            json.dumps(
                [
                    "tcp/scheduler2:7447",
                    "tcp/bootstrap.public-intelligence.net:7447",
                ]
            ),
        )
        mock_config.insert_json5.assert_any_call("scouting/multicast/enabled", "false")
        mock_config.insert_json5.assert_any_call("scouting/gossip/enabled", "true")


def test_zenoh_router_bootstrap_and_gossip_configuration() -> None:
    from unittest.mock import MagicMock, patch

    from scheduler.core.config import Settings

    bootstrap_settings = Settings(
        zenoh_listen_endpoints=["tcp/0.0.0.0:7447"],
        zenoh_peer_endpoints=[],
        bootstrap_routers=["tcp/bootstrap.public-intelligence.net:7447"],
        zenoh_gossip_scouting=False,
    )

    with (
        patch("scheduler.core.config.get_settings", return_value=bootstrap_settings),
        patch("zenoh.Config") as mock_config_cls,
    ):
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config

        registry = NodeRegistry()
        ZenohRouter(registry)

        mock_config.insert_json5.assert_any_call(
            "connect/endpoints",
            json.dumps(["tcp/bootstrap.public-intelligence.net:7447"]),
        )
        mock_config.insert_json5.assert_any_call("scouting/gossip/enabled", "false")
