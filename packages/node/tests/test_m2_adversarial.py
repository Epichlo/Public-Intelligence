"""Adversarial and stress test suite for Node Local Telemetry & Control APIs.

Focuses on concurrency race conditions, memory leaks, payload stress,
and state transitions.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from node.core.runtime import SandboxLogBuffer, sandbox_log_buffer
from node.main import app


@pytest.fixture(autouse=True)
def clear_sandbox_logs() -> None:
    """Clear sandbox log buffer before each test."""
    sandbox_log_buffer.clear()


@pytest.fixture
def mock_runtime() -> AsyncMock:
    """Fixture providing a mocked Runtime instance."""
    rt = AsyncMock()
    rt.is_running = False
    rt.settings.node_id = "test-node-adversarial"
    rt.zenoh_client = MagicMock()
    rt.zenoh_client.is_connected.return_value = True
    rt.start = AsyncMock()
    rt.stop = AsyncMock()
    return rt


# ============================================================================
# 1. SandboxLogBuffer Concurrency & Stress Tests
# ============================================================================


def test_sandbox_log_buffer_concurrent_threads() -> None:
    """Stress test: 10 threads writing 500 logs while buffer caps at 1000."""
    buffer = SandboxLogBuffer(maxlen=1000)
    num_threads = 10
    logs_per_thread = 500

    def worker(thread_idx: int) -> None:
        for i in range(logs_per_thread):
            buffer.add_log(
                message=f"Log thread={thread_idx} seq={i}",
                stream="stdout" if i % 2 == 0 else "stderr",
                branch="test-branch",
            )

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, t) for t in range(num_threads)]
        for f in futures:
            f.result()

    logs = buffer.get_logs()
    # Buffer must never exceed maxlen
    assert len(logs) == 1000
    # Buffer contains valid entries
    assert all("timestamp" in e and "message" in e for e in logs)


@pytest.mark.anyio
async def test_sandbox_log_buffer_concurrent_subscribers_and_publishers() -> None:
    """Stress test: High-frequency log additions while subscribers read concurrently."""
    buffer = SandboxLogBuffer(maxlen=1000)
    num_subscribers = 5
    num_logs = 1000
    received_counts = [0] * num_subscribers

    queues = [buffer.subscribe() for _ in range(num_subscribers)]

    async def consumer(idx: int, q: asyncio.Queue[dict[str, Any]]) -> None:
        while True:
            try:
                await asyncio.wait_for(q.get(), timeout=0.05)
                received_counts[idx] += 1
            except TimeoutError:
                break

    # Spawn consumers
    consumer_tasks = [asyncio.create_task(consumer(i, q)) for i, q in enumerate(queues)]

    # Publish logs concurrently from a separate thread
    def publisher() -> None:
        for i in range(num_logs):
            buffer.add_log(f"Stress log message {i}", stream="stdout")

    await asyncio.to_thread(publisher)
    await asyncio.gather(*consumer_tasks)

    # Clean up subscriptions
    for q in queues:
        buffer.unsubscribe(q)

    assert len(buffer._subscribers) == 0
    # Ring buffer is capped at maxlen=1000
    assert len(buffer.get_logs()) == 1000


def test_sandbox_log_buffer_memory_leak_and_cleanup() -> None:
    """Verify that buffer clears properly and subscriber lists do not leak."""
    buffer = SandboxLogBuffer(maxlen=500)

    # 1. Add 5,000 logs
    for i in range(5000):
        buffer.add_log(f"Memory test line {i}")

    assert len(buffer.get_logs()) == 500
    assert len(buffer.get_logs(limit=100)) == 100

    # 2. Add & unsubscribe 20 queues
    queues = [buffer.subscribe() for _ in range(20)]
    assert len(buffer._subscribers) == 20

    for q in queues:
        buffer.unsubscribe(q)

    assert len(buffer._subscribers) == 0

    # 3. Clear buffer
    buffer.clear()
    assert len(buffer.get_logs()) == 0


# ============================================================================
# 2. Control API Adversarial Payload & State Transition Tests
# ============================================================================


@pytest.mark.parametrize(
    "raw_action, expected_action",
    [
        ("start", "start"),
        ("stop", "stop"),
        ("  START  ", "start"),
        ("  StOp \n\t ", "stop"),
    ],
)
def test_post_node_control_valid_case_and_whitespace_handling(
    mock_runtime: AsyncMock,
    raw_action: str,
    expected_action: str,
) -> None:
    """Verify whitespace trimming and case-insensitive handling of valid
    start/stop actions.
    """

    async def mock_start() -> None:
        mock_runtime.is_running = True

    async def mock_stop() -> None:
        mock_runtime.is_running = False

    mock_runtime.start.side_effect = mock_start
    mock_runtime.stop.side_effect = mock_stop

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        if expected_action == "start":
            mock_runtime.is_running = False
        else:
            mock_runtime.is_running = True

        response = client.post("/api/v1/node/control", json={"action": raw_action})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["action"] == expected_action
        assert data["runtime_running"] is (expected_action == "start")


@pytest.mark.parametrize(
    "invalid_action",
    [
        "restart",
        "pause",
        "kill",
        "status",
        "",
        "   ",
        "123",
        "true",
        "false",
        "start_node",
        "!@#$%^&*",
    ],
)
def test_post_node_control_invalid_actions_return_400(
    mock_runtime: AsyncMock, invalid_action: str
) -> None:
    """Verify invalid action strings trigger HTTP 400 Bad Request."""
    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        response = client.post("/api/v1/node/control", json={"action": invalid_action})
        assert response.status_code == 400
        data = response.json()
        assert "Invalid action" in data["detail"]


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"action": 123},
        {"action": True},
        {"action": False},
        {"action": None},
        {"action": ["start"]},
        {"action": {"nested": "start"}},
        {},
        {"wrong_field": "start"},
    ],
)
def test_post_node_control_malformed_payloads_return_422(
    mock_runtime: AsyncMock, bad_payload: dict[str, Any]
) -> None:
    """Verify malformed/missing action payloads trigger HTTP 422 error."""
    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        response = client.post("/api/v1/node/control", json=bad_payload)
        assert response.status_code == 422


def test_post_node_control_extra_unrecognized_fields_handled_gracefully(
    mock_runtime: AsyncMock,
) -> None:
    """Verify extra unrecognized JSON payload fields do not break the
    control endpoint.
    """

    async def mock_start() -> None:
        mock_runtime.is_running = True

    mock_runtime.start.side_effect = mock_start

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        mock_runtime.is_running = False
        payload = {
            "action": "start",
            "extra_field": "ignored_value",
            "admin_mode": True,
            "timeout_seconds": 999,
        }
        response = client.post("/api/v1/node/control", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["action"] == "start"
        assert data["runtime_running"] is True


def test_post_node_control_idempotence(mock_runtime: AsyncMock) -> None:
    """Verify triggering start when running or stop when stopped is idempotent."""
    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        # 1. Test start when already running
        mock_runtime.is_running = True
        mock_runtime.start.reset_mock()
        mock_runtime.stop.reset_mock()

        res1 = client.post("/api/v1/node/control", json={"action": "start"})
        assert res1.status_code == 200
        assert res1.json()["runtime_running"] is True
        mock_runtime.start.assert_not_called()

        # 2. Test stop when already stopped
        mock_runtime.is_running = False
        res2 = client.post("/api/v1/node/control", json={"action": "stop"})
        assert res2.status_code == 200
        assert res2.json()["runtime_running"] is False
        mock_runtime.stop.assert_not_called()


# ============================================================================
# 3. Sandbox Logs API Limit & Stream Boundary Edge Cases
# ============================================================================


def test_get_sandbox_logs_limits_and_empty(mock_runtime: AsyncMock) -> None:
    """Verify GET /api/v1/sandbox/logs handles various limit query parameters
    and empty state.
    """
    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        # Empty buffer
        res_empty = client.get("/api/v1/sandbox/logs")
        assert res_empty.status_code == 200
        assert res_empty.json() == {"logs": [], "entries": []}

        # Populate buffer with 20 logs
        for i in range(20):
            sandbox_log_buffer.add_log(f"Test line {i}")

        # Limit=5
        res_limit5 = client.get("/api/v1/sandbox/logs?limit=5")
        assert res_limit5.status_code == 200
        data5 = res_limit5.json()
        assert len(data5["logs"]) == 5
        assert "Test line 19" in data5["logs"][-1]

        # Limit=10000 (larger than count)
        res_large = client.get("/api/v1/sandbox/logs?limit=10000")
        assert res_large.status_code == 200
        assert len(res_large.json()["logs"]) == 20
