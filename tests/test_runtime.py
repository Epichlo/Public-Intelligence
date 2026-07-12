"""Tests for the Runtime module."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from node.clients import SchedulerError
from node.core.configuration import Settings
from node.models import ModelInfo
from node.runtime import Runtime


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


@pytest.mark.anyio
async def test_runtime_successful_startup(
    settings: Settings,
    mock_scheduler_client: AsyncMock,
    mock_ollama_client: AsyncMock,
) -> None:
    """Verify that start registers the node and launches the heartbeat task."""
    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=mock_ollama_client,
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
) -> None:
    """Verify start propagates registration exceptions and resets running status."""
    mock_scheduler_client.register.side_effect = Exception("Registration rejected")

    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=mock_ollama_client,
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
) -> None:
    """Verify that stop cancels task, unregisters, and marks running as False."""
    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=mock_ollama_client,
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
) -> None:
    """Verify shutdown is still graceful when Scheduler unregister raises an error."""
    mock_scheduler_client.unregister.side_effect = SchedulerError(
        "Unregister connection failed"
    )

    runtime = Runtime(
        settings=settings,
        scheduler_client=mock_scheduler_client,
        ollama_client=mock_ollama_client,
    )

    await runtime.start()
    # Should not raise exception
    await runtime.stop()

    assert runtime.is_running is False
    mock_scheduler_client.unregister.assert_called_once()
