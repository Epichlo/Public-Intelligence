"""Tests for the Runtime module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from node.clients import SchedulerError
from node.core.configuration import Settings
from node.models import ModelInfo
from node.runtime import Runtime

# This node's own credential. Since ROADMAP 2.7 telemetry is sealed with a key
# derived from it, not from a fleet-wide secret.
TELEMETRY_TEST_TOKEN = "per-install-credential-for-tests"


@pytest.fixture
def settings() -> Settings:
    """Fixture to provide test settings with short heartbeat interval."""
    return Settings(
        node_id="test-node",
        hostname="localhost",
        region="local",
        heartbeat_interval_seconds=1,
    )


@pytest.fixture
def mock_scheduler_client() -> AsyncMock:
    """Fixture to provide a mocked SchedulerClient."""
    return AsyncMock()


@pytest.fixture
def mock_ollama_client() -> AsyncMock:
    """Fixture to provide a mocked OllamaClient."""
    mock = AsyncMock()
    mock.list_models.return_value = [
        ModelInfo(name="llama3-8b", size_gb=4.7, family="llama", context_length=8192)
    ]
    return mock


@pytest.fixture
def mock_zenoh_client() -> MagicMock:
    """Fixture to provide a mocked ZenohHeartbeatClient."""
    return MagicMock()


@pytest.mark.anyio
async def test_runtime_successful_startup(
    settings: Settings,
    mock_scheduler_client: AsyncMock,
    mock_ollama_client: AsyncMock,
    mock_zenoh_client: MagicMock,
) -> None:
    """Verify that start registers the node and launches the heartbeat task."""
    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=mock_ollama_client,
        zenoh_client=mock_zenoh_client,
    )

    try:
        await runtime.start()

        assert runtime.is_running is True
        assert runtime.heartbeat_task is not None
        assert not runtime.heartbeat_task.done()

        mock_ollama_client.list_models.assert_called_once()
        mock_scheduler_client.register.assert_called_once()
    finally:
        await runtime.stop()


@pytest.mark.anyio
async def test_runtime_registration_failure(
    settings: Settings,
    mock_scheduler_client: AsyncMock,
    mock_ollama_client: AsyncMock,
    mock_zenoh_client: MagicMock,
) -> None:
    """Verify start propagates a NON-SchedulerError from registration.

    This still fails fast on purpose. A bare `Exception` from the register call is
    a bug in this node, not the Scheduler being unreachable -- only `SchedulerError`
    is survivable, and `test_scheduler_outage.py` pins that half. Roadmap 1.6
    changed which exceptions kill startup, not whether any do.
    """
    mock_scheduler_client.register.side_effect = Exception("Registration rejected")

    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=mock_ollama_client,
        zenoh_client=mock_zenoh_client,
    )

    with pytest.raises(Exception, match="Registration rejected"):
        await runtime.start()

    assert runtime.is_running is False
    assert runtime.heartbeat_task is None


@pytest.mark.anyio
async def test_heartbeat_loop_execution(
    settings: Settings,
    mock_scheduler_client: AsyncMock,
    mock_ollama_client: AsyncMock,
    mock_zenoh_client: MagicMock,
) -> None:
    """Verify that the heartbeat loop periodically sends heartbeats."""

    async def mock_sleep(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(0)

    # Mock the imported async_sleep locally to speed up tests and yield control
    with patch("node.runtime.async_sleep", new_callable=AsyncMock) as mock_sleep_func:
        mock_sleep_func.side_effect = mock_sleep
        runtime = Runtime(
            settings=settings,
            scheduler_client=mock_scheduler_client,
            ollama_client=mock_ollama_client,
            zenoh_client=mock_zenoh_client,
        )

        try:
            await runtime.start()
            # Allow loop to execute a few iterations using real sleep
            await asyncio.sleep(0.01)
            assert mock_scheduler_client.heartbeat.call_count > 0
        finally:
            await runtime.stop()


@pytest.mark.anyio
async def test_graceful_shutdown(
    settings: Settings,
    mock_scheduler_client: AsyncMock,
    mock_ollama_client: AsyncMock,
    mock_zenoh_client: MagicMock,
) -> None:
    """Verify that stop cancels task, unregisters, and marks running as False."""
    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=mock_ollama_client,
        zenoh_client=mock_zenoh_client,
    )

    await runtime.start()
    task = runtime.heartbeat_task
    assert task is not None
    assert not task.done()

    await runtime.stop()

    assert runtime.is_running is False
    assert runtime.heartbeat_task is None
    assert task.done() or task.cancelled()

    mock_scheduler_client.unregister.assert_called_once_with(settings.node_id)


@pytest.mark.anyio
async def test_graceful_shutdown_unregister_failure(
    settings: Settings,
    mock_scheduler_client: AsyncMock,
    mock_ollama_client: AsyncMock,
    mock_zenoh_client: MagicMock,
) -> None:
    """Verify shutdown is still graceful when Scheduler unregister raises an error."""
    mock_scheduler_client.unregister.side_effect = SchedulerError("Unregister connection failed")

    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=mock_ollama_client,
        zenoh_client=mock_zenoh_client,
    )

    await runtime.start()
    # Should not raise exception
    await runtime.stop()

    assert runtime.is_running is False
    mock_scheduler_client.unregister.assert_called_once()


@pytest.mark.anyio
async def test_telemetry_emitter_lifecycle() -> None:
    """Verify that TelemetryEmitter collects and publishes data, and can be stopped."""

    import zenoh

    from node.core.telemetry import (
        TelemetryEmitter,
        get_cpu_utilization,
        get_ram_usage_bytes,
    )

    # Basic system metric collection check
    cpu = get_cpu_utilization()
    ram = get_ram_usage_bytes()
    assert 0.0 <= cpu <= 100.0
    assert ram >= 0

    # Start mock Zenoh session for loopback testing
    config = zenoh.Config()
    config.insert_json5("scouting/multicast/enabled", "false")
    # Explicit IPv4 loopback listener -- see test_zenoh_integration.py. The zenoh
    # default is `tcp/[::]:0`, an IPv6 wildcard, which is EAFNOSUPPORT on an
    # IPv4-only host. Assertions unchanged; the environment assumption is now stated.
    config.insert_json5("listen/endpoints", '["tcp/127.0.0.1:0"]')

    with zenoh.open(config) as session:
        emitter = TelemetryEmitter(
            node_id="test-node-telemetry",
            zenoh_session=session,
            auth_token=TELEMETRY_TEST_TOKEN,
            interval=0.1,
        )

        # We subscribe to the topic to see if the emitter publishes data
        received_payloads = []

        def on_sample(sample: zenoh.Sample) -> None:
            try:
                payload_str = sample.payload.to_string()
            except AttributeError:
                try:
                    payload_str = sample.payload.decode("utf-8")  # type: ignore[attr-defined]
                except (AttributeError, UnicodeDecodeError):
                    payload_str = str(sample.payload)
            received_payloads.append(payload_str)

        sub = session.declare_subscriber(emitter.topic, on_sample)

        emitter.start()
        # Wait a moment for at least one emission
        await asyncio.sleep(0.3)
        await emitter.stop()

        assert len(received_payloads) > 0

        # Opened with the node's OWN credential. This used to derive keys from a
        # fleet-wide TELEMETRY_SECRET_KEY defaulting to a constant published in this
        # repo, which meant this assertion would have passed for a forgery too.
        from node.core.mesh_auth import PURPOSE_TELEMETRY, open_envelope

        metrics = open_envelope(
            received_payloads[0],
            node_id="test-node-telemetry",
            token=TELEMETRY_TEST_TOKEN,
            purpose=PURPOSE_TELEMETRY,
        )
        assert metrics["node_id"] == "test-node-telemetry"
        assert 0.0 <= metrics["cpu_utilization"] <= 100.0
        assert "ram_usage_bytes" in metrics
        assert metrics["gpu_utilization"] == 0.0
        assert metrics["vram_usage_bytes"] == 0

        sub.undeclare()


@pytest.mark.anyio
async def test_startup_survives_ollama_being_unreachable(
    settings: Settings,
    mock_scheduler_client: AsyncMock,
    mock_zenoh_client: MagicMock,
) -> None:
    """A node whose Ollama is down must still register, with no models advertised.

    `start()` wraps model discovery in `except Exception` precisely so this is
    survivable, but the handler called `logger.warning(msg, error=...)`. stdlib
    Logger takes no `error` kwarg, so the handler raised TypeError and the node
    died on exactly the path meant to keep it alive. No test caught it because
    every mock Ollama client returned successfully.
    """
    failing_ollama = AsyncMock()
    failing_ollama.list_models.side_effect = ConnectionError("ollama is not running")
    mock_zenoh_client.session = None

    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=failing_ollama,
        zenoh_client=mock_zenoh_client,
    )

    await runtime.start()
    assert runtime.registration_status == "registered"
    await runtime.stop()

    registered = mock_scheduler_client.register.call_args.args[0]
    assert registered.available_models == []
