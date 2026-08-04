"""The runtime must actually declare the mesh inference queryable.

`ZenohInferenceServer` being correct is worth nothing if nothing starts it. These tests
pin the wiring: a node with a live Zenoh session serves mesh inference, a node whose
Zenoh connection was deferred still boots, and shutdown stops accepting work.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from node.core.configuration import Settings
from node.core.mesh_protocol import infer_key_expr
from node.models import ModelInfo
from node.runtime import Runtime

NODE_ID = "test-node-mesh-wiring"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        node_id=NODE_ID,
        hostname="localhost",
        region="local",
        heartbeat_interval_seconds=1,
        network_auth_token="wiring-token",
    )


@pytest.fixture
def scheduler_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def ollama_client() -> AsyncMock:
    mock = AsyncMock()
    mock.list_models.return_value = [
        ModelInfo(name="llama3-8b", size_gb=4.7, family="llama", context_length=8192)
    ]
    return mock


@pytest.mark.anyio
async def test_start_declares_the_inference_queryable(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """With a live session, the node must advertise itself as reachable over the mesh."""
    zenoh_client = MagicMock()
    session = MagicMock()
    zenoh_client.session = session

    runtime = Runtime(
        settings=settings,
        scheduler_client=scheduler_client,
        ollama_client=ollama_client,
        zenoh_client=zenoh_client,
    )

    try:
        await runtime.start()

        assert runtime.mesh_inference_server is not None
        assert runtime.mesh_inference_server.is_serving() is True
        declared_keys = [call.args[0] for call in session.declare_queryable.call_args_list]
        assert infer_key_expr(NODE_ID) in declared_keys, (
            f"node did not declare its inference queryable; declared: {declared_keys}"
        )
    finally:
        await runtime.stop()


@pytest.mark.anyio
async def test_stop_stops_serving_mesh_inference(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A stopped node must not keep answering queries."""
    zenoh_client = MagicMock()
    zenoh_client.session = MagicMock()

    runtime = Runtime(
        settings=settings,
        scheduler_client=scheduler_client,
        ollama_client=ollama_client,
        zenoh_client=zenoh_client,
    )
    await runtime.start()
    server = runtime.mesh_inference_server
    assert server is not None and server.is_serving() is True

    await runtime.stop()

    assert server.is_serving() is False


@pytest.mark.anyio
async def test_node_without_a_zenoh_session_still_boots(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """Mesh inference is unavailable, not fatal, when the mesh connection is deferred.

    `ZenohHeartbeatClient.start` swallows connection failures and leaves `session` as
    None. The node must still come up and serve over HTTP.
    """
    zenoh_client = MagicMock()
    zenoh_client.session = None

    runtime = Runtime(
        settings=settings,
        scheduler_client=scheduler_client,
        ollama_client=ollama_client,
        zenoh_client=zenoh_client,
    )

    try:
        await runtime.start()

        assert runtime.is_running is True
        assert (
            runtime.mesh_inference_server is None
            or runtime.mesh_inference_server.is_serving() is False
        )
    finally:
        await runtime.stop()
