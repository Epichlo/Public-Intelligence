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
    """Verify the client sends its credentials, and which header carries which.

    Two headers since decision D9: `X-Network-Auth-Token` is the fleet's shared
    admission secret, `X-Node-Credential` is this host's own. This asserted a single
    header until then. With only `network_auth_token` set -- the pre-D9 shape, and
    still correct against a Scheduler with no fleet token -- the one secret goes in
    both, which is exactly what this node used to send.
    """
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
        headers={
            "X-Network-Auth-Token": "secure-test-token",
            "X-Node-Credential": "secure-test-token",
        },
        timeout=5.0,
    )


@pytest.mark.anyio
async def test_the_two_tokens_ride_in_separate_headers(
    settings: Settings, dummy_request: httpx.Request
) -> None:
    """Decision D9: an operator who configures both must not have them conflated.

    The failure this pins is not a crash. It is the Scheduler storing the fleet
    secret as this node's per-node credential, which makes every host able to forge
    messages as every other and raises nothing anywhere.
    """
    mock_client = AsyncMock()
    mock_client.request.return_value = httpx.Response(200, request=dummy_request)

    settings.network_auth_token = "this-hosts-own-secret"
    settings.fleet_token = "the-shared-admission-secret"
    await SchedulerClient(settings, client=mock_client).unregister("node-1")

    headers = mock_client.request.call_args.kwargs["headers"]
    assert headers["X-Network-Auth-Token"] == "the-shared-admission-secret"
    assert headers["X-Node-Credential"] == "this-hosts-own-secret"


@pytest.mark.anyio
async def test_error_carries_the_response_status_code(
    settings: Settings, node_info: NodeInfo, dummy_request: httpx.Request
) -> None:
    """Callers must be able to branch on the status without parsing the message.

    Registration reads 409 as "already registered" and the heartbeat loop reads 404
    as "the Scheduler has forgotten this node, register again". Both used to mean
    substring-matching an error string, which would match a node id containing
    "409" and would break on any rewording. See specs/scheduler-outage-resilience.md.
    """
    mock_client = AsyncMock()
    mock_client.request.return_value = httpx.Response(404, request=dummy_request)

    client = SchedulerClient(settings, client=mock_client)
    with pytest.raises(SchedulerError) as exc_info:
        await client.heartbeat(
            Heartbeat(
                node_id="node-1",
                timestamp=datetime.now(UTC),
                queue_length=0,
                cpu_utilization=1.0,
                ram_available_gb=1.0,
                gpu_utilization=1.0,
                vram_available_gb=1.0,
            )
        )

    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_a_request_that_never_landed_has_no_status_code(
    settings: Settings, node_info: NodeInfo, dummy_request: httpx.Request
) -> None:
    """None distinguishes "no response at all" from "the Scheduler said something".

    A refused connection must not be mistaken for a 404, or a node would tear down
    its registration state every time the network hiccuped.
    """
    mock_client = AsyncMock()
    mock_client.request.side_effect = httpx.ConnectError(
        "Connection refused", request=dummy_request
    )

    client = SchedulerClient(settings, client=mock_client)
    with pytest.raises(SchedulerError) as exc_info:
        await client.register(node_info)

    assert exc_info.value.status_code is None


@pytest.mark.anyio
async def test_conflict_is_detected_by_status_not_by_message(
    settings: Settings, dummy_request: httpx.Request
) -> None:
    """A 500 whose body happens to contain "409" must not read as already registered.

    The old check was `"409" in str(e)`, and the error message interpolates
    `e.response.text` -- so any Scheduler error body mentioning that number turned a
    hard failure into a silent "already registered", and the node carried on with a
    registration that had never happened.
    """
    mock_client = AsyncMock()
    mock_client.request.return_value = httpx.Response(
        500, request=dummy_request, text="internal error handling node-409"
    )

    client = SchedulerClient(settings, client=mock_client)
    info = NodeInfo(
        node_id="node-409",
        hostname="node.local",
        region="local",
        ip_address="127.0.0.1",
        cpu_cores=4,
        ram_total_gb=8.0,
        gpu=GPUInfo(name="cpu-only", vram_total_gb=0.0, vram_available_gb=0.0),
        available_models=[],
    )

    with pytest.raises(SchedulerError):
        await client.register(info)
