"""Tests for host node control, telemetry, and sandbox log monitoring APIs."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from node.core.runtime import WorktreeManager, sandbox_log_buffer
from node.main import app


@pytest.fixture(autouse=True)
def clear_sandbox_logs() -> None:
    """Clear sandbox log buffer before each test."""
    sandbox_log_buffer.clear()


@pytest.fixture
def mock_runtime() -> AsyncMock:
    """Fixture to provide a mocked Runtime instance for FastAPI lifespan."""
    rt = AsyncMock()
    rt.is_running = True
    rt.settings.node_id = "test-node-01"
    rt.zenoh_client = MagicMock()
    rt.zenoh_client.is_connected.return_value = True
    rt.start = AsyncMock()
    rt.stop = AsyncMock()
    return rt


def test_get_node_telemetry_success(mock_runtime: AsyncMock) -> None:
    """Verify telemetry endpoint returns hardware metrics and P2P state."""
    mock_metrics = {
        "cpu_utilization": 25.5,
        "ram_total_bytes": 16000000000,
        "ram_available_bytes": 8000000000,
        "ram_used_bytes": 8000000000,
        "gpu_name": "NVIDIA RTX 4090",
        "gpu_utilization": 12.0,
        "vram_total_bytes": 24000000000,
        "vram_available_bytes": 18000000000,
        "vram_used_bytes": 6000000000,
    }

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        patch("node.api.control.TelemetryCollector.collect", return_value=mock_metrics),
        TestClient(app) as client,
    ):
        response = client.get("/api/v1/node/telemetry")
        assert response.status_code == 200
        data = response.json()
        assert data["node_id"] == "test-node-01"
        assert data["cpu_utilization"] == 25.5
        assert data["ram_used_bytes"] == 8000000000
        assert data["ram_total_bytes"] == 16000000000
        assert data["gpu_utilization"] == 12.0
        assert data["vram_used_bytes"] == 6000000000
        assert data["vram_total_bytes"] == 24000000000
        assert data["wan_connected"] is True
        assert data["status"] == "ready"


def test_post_node_control_start_and_stop(mock_runtime: AsyncMock) -> None:
    """Verify POST /api/v1/node/control handles start and stop actions."""
    mock_runtime.is_running = False

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
        # 1. Test action: start
        response_start = client.post("/api/v1/node/control", json={"action": "start"})
        assert response_start.status_code == 200
        data_start = response_start.json()
        assert data_start["status"] == "ok"
        assert data_start["action"] == "start"
        assert data_start["runtime_running"] is True

        # 2. Test action: stop
        response_stop = client.post("/api/v1/node/control", json={"action": "stop"})
        assert response_stop.status_code == 200
        data_stop = response_stop.json()
        assert data_stop["status"] == "ok"
        assert data_stop["action"] == "stop"
        assert data_stop["runtime_running"] is False

        # 3. Test invalid action
        response_invalid = client.post("/api/v1/node/control", json={"action": "pause"})
        assert response_invalid.status_code == 400
        assert "Invalid action" in response_invalid.json()["detail"]


def test_get_sandbox_logs(mock_runtime: AsyncMock) -> None:
    """Verify GET /api/v1/sandbox/logs returns recent log buffer entries."""
    sandbox_log_buffer.add_log(
        "Container init completed", stream="stdout", branch="feature/test"
    )
    sandbox_log_buffer.add_log(
        "Execution warning message", stream="stderr", branch="feature/test"
    )

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        response = client.get("/api/v1/sandbox/logs")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "entries" in data
        assert len(data["logs"]) == 2
        assert "Container init completed" in data["logs"][0]
        assert "Execution warning message" in data["logs"][1]


def test_stream_sandbox_logs(mock_runtime: AsyncMock) -> None:
    """Verify GET /api/v1/sandbox/logs/stream streams real-time SSE log events."""
    sandbox_log_buffer.add_log("Stream log test line", stream="stdout", branch="main")

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
        client.stream("GET", "/api/v1/sandbox/logs/stream?max_events=1") as response,
    ):
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        lines = list(response.iter_lines())
        assert any("Stream log test line" in line for line in lines)


@pytest.mark.anyio
async def test_worktree_manager_captures_sandbox_logs() -> None:
    """Verify execute_in_sandbox records process output into ring buffer."""
    wm = WorktreeManager()
    wm._worktrees["test_branch"] = "/tmp/fake_worktree"

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (
        b"Standard container output line\n",
        b"Standard container error line\n",
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        cmd = ["python", "-c", "print('hi')"]
        res = await wm.execute_in_sandbox("test_branch", cmd)
        assert res.returncode == 0

        logs = wm.log_buffer.get_logs()
        assert len(logs) == 2
        assert logs[0]["message"] == "Standard container output line"
        assert logs[0]["stream"] == "stdout"
        assert logs[1]["message"] == "Standard container error line"
        assert logs[1]["stream"] == "stderr"
