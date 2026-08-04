"""Tests for the SchedulerClient."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from node.clients import SchedulerClient, SchedulerError
from node.core.configuration import Settings
from node.models import GPUInfo, Heartbeat, ModelInfo, NodeInfo


@pytest.fixture
def settings() -> Settings:
    """Fixture to provide test settings."""
    return Settings(scheduler_url="http://mock-scheduler:8080")


@pytest.fixture
def node_info() -> NodeInfo:
    """Fixture to provide a valid NodeInfo instance."""
    return NodeInfo(
        node_id="node-1",
        hostname="node.local",
        region="us-east",
        ip_address="192.168.1.50",
        cpu_cores=8,
        ram_total_gb=16.0,
        gpu=GPUInfo(
            name="NVIDIA GeForce RTX 3090",
            vram_total_gb=24.0,
            vram_available_gb=22.0,
        ),
        available_models=[
            ModelInfo(
                name="llama3-8b",
                size_gb=4.7,
                family="llama",
                context_length=8192,
            )
        ],
    )


@pytest.fixture
def heartbeat_data() -> Heartbeat:
    """Fixture to provide a valid Heartbeat instance."""
    return Heartbeat(
        node_id="node-1",
        timestamp=datetime.now(UTC),
        queue_length=0,
        cpu_utilization=10.0,
        ram_available_gb=12.0,
        gpu_utilization=0.0,
        vram_available_gb=0.0,
    )


@pytest.fixture
def dummy_request() -> httpx.Request:
    """Fixture to provide a dummy HTTP request for HTTP responses."""
    return httpx.Request("POST", "http://mock-scheduler:8080")


@pytest.mark.anyio
async def test_register_success_custom_client(
    settings: Settings, node_info: NodeInfo, dummy_request: httpx.Request
) -> None:
    """Verify that register works successfully with a custom client."""
    mock_client = AsyncMock()
    mock_response = httpx.Response(200, request=dummy_request)
    mock_client.request.return_value = mock_response

    client = SchedulerClient(settings, client=mock_client)
    await client.register(node_info)

    expected_payload = node_info.model_dump(mode="json")
    expected_payload["available_models"] = [
        m["name"] for m in expected_payload.get("available_models", [])
    ]
    # `gpu` is no longer overwritten by the client -- it rides along from
    # NodeInfo.gpu as model_dump produced it. See specs/real-hardware-advertisement.md.

    mock_client.request.assert_called_once_with(
        "POST",
        "http://mock-scheduler:8080/nodes/register",
        json=expected_payload,
        headers={},
        timeout=5.0,
    )


@pytest.mark.anyio
@patch("node.clients.scheduler.httpx.AsyncClient")
async def test_register_success_transient_client(
    mock_client_class: AsyncMock,
    settings: Settings,
    node_info: NodeInfo,
    dummy_request: httpx.Request,
) -> None:
    """Verify that register works successfully with a transient client."""
    mock_client = AsyncMock()
    mock_response = httpx.Response(200, request=dummy_request)
    mock_client.request.return_value = mock_response
    mock_client_class.return_value.__aenter__.return_value = mock_client

    client = SchedulerClient(settings)
    await client.register(node_info)

    expected_payload = node_info.model_dump(mode="json")
    expected_payload["available_models"] = [
        m["name"] for m in expected_payload.get("available_models", [])
    ]
    # `gpu` is no longer overwritten by the client -- it rides along from
    # NodeInfo.gpu as model_dump produced it. See specs/real-hardware-advertisement.md.

    mock_client.request.assert_called_once_with(
        "POST",
        "http://mock-scheduler:8080/nodes/register",
        json=expected_payload,
        headers={},
    )


@pytest.mark.anyio
async def test_heartbeat_success_custom_client(
    settings: Settings,
    heartbeat_data: Heartbeat,
    dummy_request: httpx.Request,
) -> None:
    """Verify that heartbeat works successfully with a custom client."""
    mock_client = AsyncMock()
    mock_response = httpx.Response(200, request=dummy_request)
    mock_client.request.return_value = mock_response

    client = SchedulerClient(settings, client=mock_client)
    await client.heartbeat(heartbeat_data)

    expected_payload = heartbeat_data.model_dump(mode="json")
    expected_payload["status"] = "online"

    mock_client.request.assert_called_once_with(
        "POST",
        "http://mock-scheduler:8080/heartbeat",
        json=expected_payload,
        headers={},
        timeout=5.0,
    )


@pytest.mark.anyio
async def test_unregister_success_custom_client(
    settings: Settings, dummy_request: httpx.Request
) -> None:
    """Verify that unregister works successfully with a custom client."""
    mock_client = AsyncMock()
    mock_response = httpx.Response(200, request=dummy_request)
    mock_client.request.return_value = mock_response

    client = SchedulerClient(settings, client=mock_client)
    await client.unregister("node-1")

    mock_client.request.assert_called_once_with(
        "DELETE",
        "http://mock-scheduler:8080/nodes/node-1",
        json=None,
        headers={},
        timeout=5.0,
    )


@pytest.mark.anyio
async def test_server_error_response(
    settings: Settings, node_info: NodeInfo, dummy_request: httpx.Request
) -> None:
    """Verify that a server error status code raises a SchedulerError."""
    mock_client = AsyncMock()
    mock_response = httpx.Response(500, request=dummy_request)
    mock_client.request.return_value = mock_response

    client = SchedulerClient(settings, client=mock_client)
    with pytest.raises(SchedulerError) as exc_info:
        await client.register(node_info)

    assert "status 500" in str(exc_info.value)


@pytest.mark.anyio
async def test_connection_failure(
    settings: Settings, node_info: NodeInfo, dummy_request: httpx.Request
) -> None:
    """Verify that a network connection error raises a SchedulerError."""
    mock_client = AsyncMock()
    mock_client.request.side_effect = httpx.ConnectError(
        "Connection refused",
        request=dummy_request,
    )

    client = SchedulerClient(settings, client=mock_client)
    with pytest.raises(SchedulerError) as exc_info:
        await client.register(node_info)

    assert "Connection refused" in str(exc_info.value)


@pytest.mark.anyio
async def test_timeout_failure(
    settings: Settings, node_info: NodeInfo, dummy_request: httpx.Request
) -> None:
    """Verify that an HTTP request timeout raises a SchedulerError."""
    mock_client = AsyncMock()
    mock_client.request.side_effect = httpx.TimeoutException(
        "Request timed out",
        request=dummy_request,
    )

    client = SchedulerClient(settings, client=mock_client)
    with pytest.raises(SchedulerError) as exc_info:
        await client.register(node_info)

    assert "Request timed out" in str(exc_info.value)


@pytest.mark.anyio
async def test_client_sends_auth_token(settings: Settings, dummy_request: httpx.Request) -> None:
    """Verify that the client passes the X-Network-Auth-Token header when configured."""
    mock_client = AsyncMock()
    mock_response = httpx.Response(200, request=dummy_request)
    mock_client.request.return_value = mock_response

    # Configure the auth token
    settings.network_auth_token = "secure-test-token"
    client = SchedulerClient(settings, client=mock_client)
    await client.unregister("node-1")

    mock_client.request.assert_called_once_with(
        "DELETE",
        "http://mock-scheduler:8080/nodes/node-1",
        json=None,
        headers={"X-Network-Auth-Token": "secure-test-token"},
        timeout=5.0,
    )
