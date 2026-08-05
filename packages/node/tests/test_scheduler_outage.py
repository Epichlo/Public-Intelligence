"""A node survives the Scheduler being unreachable (roadmap 1.6).

`runtime.start()` registered with the Scheduler and let `SchedulerError` propagate.
Nothing above it caught, so it left the FastAPI lifespan and uvicorn reported
"Application startup failed. Exiting." A host booting while the Scheduler was
briefly down -- a Render cold start, a network blip -- got no node process at all,
with no retry.

The same assumption broke after boot and more often: `/heartbeat` 404s for a node
the registry does not know, and the Scheduler's registry is an in-memory dict, so
*every* Scheduler restart made *every* node heartbeat into a 404 forever with no
way back. Both are covered here; see specs/scheduler-outage-resilience.md.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from node.clients import SchedulerError
from node.core.configuration import Settings
from node.models import ModelInfo
from node.models.gpu_info import cpu_only_gpu
from node.runtime import Runtime


@pytest.fixture
def settings() -> Settings:
    """Settings with intervals short enough that a loop tick is observable."""
    return Settings(
        node_id="test-node",
        hostname="localhost",
        region="local",
        heartbeat_interval_seconds=1,
        model_refresh_interval_seconds=1,
        registration_retry_max_seconds=5.0,
    )


@pytest.fixture
def scheduler_client() -> AsyncMock:
    """A Scheduler client that cannot be reached."""
    client = AsyncMock()
    client.register.side_effect = SchedulerError("Scheduler request POST /nodes/register failed")
    return client


@pytest.fixture
def ollama_client() -> AsyncMock:
    """An Ollama client hosting one model."""
    client = AsyncMock()
    client.list_models.return_value = [
        ModelInfo(name="llama3-8b", size_gb=4.7, family="llama", context_length=8192)
    ]
    return client


def build_runtime(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> Runtime:
    """Build a Runtime with every outbound dependency mocked."""
    return Runtime(
        settings=settings,
        scheduler_client=scheduler_client,
        ollama_client=ollama_client,
        zenoh_client=MagicMock(),
    )


# --- degraded start ----------------------------------------------------------


@pytest.mark.anyio
async def test_start_survives_an_unreachable_scheduler(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """The node comes up rather than killing the process."""
    runtime = build_runtime(settings, scheduler_client, ollama_client)

    with patch("node.runtime.detect_gpu", AsyncMock(return_value=cpu_only_gpu())):
        try:
            await runtime.start()

            assert runtime.is_running is True
            assert runtime.registration_status == "pending"
            assert runtime.registration_retry_task is not None
        finally:
            await runtime.stop()


@pytest.mark.anyio
async def test_start_still_fails_on_a_real_bug(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """Only SchedulerError is survivable; anything else still aborts startup.

    The distinction is the point. "The Scheduler is down" is an expected state of
    the world. A TypeError in a probe, or a ValidationError building NodeInfo, is a
    bug in this node -- starting degraded would hide it behind a status field
    nobody reads.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    scheduler_client.register.side_effect = ValueError("node_id is malformed")

    with (
        patch("node.runtime.detect_gpu", AsyncMock(return_value=cpu_only_gpu())),
        pytest.raises(ValueError, match="node_id is malformed"),
    ):
        await runtime.start()

    assert runtime.is_running is False
    assert runtime.registration_status == "failed"
    assert runtime.registration_retry_task is None


@pytest.mark.anyio
async def test_degraded_start_still_runs_everything_local(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """Nothing after registration depends on the Scheduler existing.

    The Zenoh session, the mesh inference server, and the worker loop are what let
    the node be useful at all -- and joining the mesh is how the Scheduler observes
    this node as reachable once registration does land.
    """
    zenoh = MagicMock()
    runtime = Runtime(
        settings=settings,
        scheduler_client=scheduler_client,
        ollama_client=ollama_client,
        zenoh_client=zenoh,
    )

    with patch("node.runtime.detect_gpu", AsyncMock(return_value=cpu_only_gpu())):
        try:
            await runtime.start()

            zenoh.start.assert_called_once()
            assert runtime.mesh_inference_server is not None
            assert runtime.worker_task is not None
            assert runtime.heartbeat_task is not None
            assert runtime.model_refresh_task is not None
        finally:
            await runtime.stop()


@pytest.mark.anyio
async def test_stop_cancels_the_retry_task(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A node stopped mid-outage is exactly when the retry task is still sleeping."""
    runtime = build_runtime(settings, scheduler_client, ollama_client)

    with patch("node.runtime.detect_gpu", AsyncMock(return_value=cpu_only_gpu())):
        await runtime.start()
        assert runtime.registration_retry_task is not None
        await runtime.stop()

    assert runtime.registration_retry_task is None


# --- the retry loop ----------------------------------------------------------


@pytest.mark.anyio
async def test_retry_registers_once_the_scheduler_returns(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """The loop keeps trying and exits as soon as registration lands."""
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.is_running = True
    runtime.node_info = MagicMock(available_models=[])
    runtime.registration_status = "pending"

    scheduler_client.register.side_effect = [
        SchedulerError("connection refused"),
        SchedulerError("connection refused"),
        True,
    ]

    with patch("node.runtime.async_sleep", AsyncMock()):
        await asyncio.wait_for(runtime._registration_retry_loop(), timeout=5.0)

    assert runtime.registration_status == "registered"
    assert scheduler_client.register.await_count == 3


@pytest.mark.anyio
async def test_retry_backoff_grows_and_is_capped(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """Waits double up to `registration_retry_max_seconds` and stop there.

    Without a cap a node unlucky enough to retry through a long outage would end up
    sleeping for hours and miss the Scheduler's return entirely.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.is_running = True
    runtime.node_info = MagicMock(available_models=[])
    runtime.registration_status = "pending"

    scheduler_client.register.side_effect = [SchedulerError("down")] * 4 + [True]

    delays: list[float] = []

    async def record(seconds: float) -> None:
        delays.append(seconds)

    # `uniform(0, n) -> n` makes the jittered sleep report its own upper bound, so
    # the growth and the ceiling are both observable. The jitter itself is asserted
    # separately below.
    with (
        patch("node.runtime.async_sleep", record),
        patch("node.runtime.random.uniform", lambda _low, high: high),
    ):
        await asyncio.wait_for(runtime._registration_retry_loop(), timeout=5.0)

    assert delays == [1.0, 2.0, 4.0, 5.0, 5.0]
    assert max(delays) <= settings.registration_retry_max_seconds


@pytest.mark.anyio
async def test_retry_sleep_is_jittered(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """The wait is a random point in [0, interval], not the interval itself.

    The scenario that triggers this is a Scheduler that was down and came back,
    which means every node retries at the same moment. Plain exponential backoff
    keeps them synchronised and lands the whole fleet on a service that has only
    just started.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.is_running = True
    runtime.node_info = MagicMock(available_models=[])
    runtime.registration_status = "pending"
    scheduler_client.register.side_effect = [SchedulerError("down")] * 6 + [True]

    bounds: list[tuple[float, float]] = []

    def spy(low: float, high: float) -> float:
        bounds.append((low, high))
        return low

    with (
        patch("node.runtime.async_sleep", AsyncMock()),
        patch("node.runtime.random.uniform", spy),
    ):
        await asyncio.wait_for(runtime._registration_retry_loop(), timeout=5.0)

    assert all(low == 0.0 for low, _ in bounds), "jitter must be able to fire immediately"
    assert [high for _, high in bounds] == [1.0, 2.0, 4.0, 5.0, 5.0, 5.0, 5.0]


@pytest.mark.anyio
async def test_late_registration_reconciles_the_catalogue(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A registration that lands late leaves the same state as one that lands on time.

    Specifically the 409 branch: the Scheduler already holds a record from an
    earlier process, so this node's real catalogue has to be pushed. Losing that on
    the retry path would mean an outage silently reintroduced roadmap 1.4's bug.
    """
    models = [ModelInfo(name="llama3-8b", size_gb=4.7, family="llama", context_length=8192)]
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.is_running = True
    runtime.node_info = MagicMock(available_models=models)
    runtime.registration_status = "pending"

    scheduler_client.register.side_effect = [SchedulerError("down"), False]

    with patch("node.runtime.async_sleep", AsyncMock()):
        await asyncio.wait_for(runtime._registration_retry_loop(), timeout=5.0)

    assert runtime.registration_status == "registered"
    scheduler_client.update_models.assert_awaited_once()
    _, pushed = scheduler_client.update_models.await_args.args
    assert [m.name for m in pushed] == ["llama3-8b"]


# --- recovery after the Scheduler forgets the node ---------------------------


@pytest.mark.anyio
async def test_a_404_heartbeat_re_registers(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A Scheduler that lost its registry gets this node back without a restart.

    The registry is an in-memory dict, so this fires on every Scheduler restart.
    Before, the node logged a failed heartbeat every interval forever and was never
    matchmade again.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.is_running = True
    runtime.registration_status = "registered"
    runtime.node_info = MagicMock(available_models=[])
    scheduler_client.heartbeat.side_effect = SchedulerError("not found", status_code=404)

    with (
        patch("node.runtime.detect_host_metrics", AsyncMock()) as metrics,
        patch("node.runtime.async_sleep", AsyncMock(side_effect=asyncio.CancelledError)),
    ):
        metrics.return_value.cpu_utilization = 1.0
        metrics.return_value.ram_available_gb = 1.0
        metrics.return_value.gpu_utilization = 1.0
        metrics.return_value.vram_available_gb = 1.0
        await runtime._heartbeat_loop()

    assert runtime.registration_status == "pending"
    assert runtime.registration_retry_task is not None
    runtime.registration_retry_task.cancel()


@pytest.mark.anyio
async def test_a_500_heartbeat_does_not_re_register(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A Scheduler having a bad minute is not a Scheduler that forgot this node.

    Re-registering on any failure would answer a transient 500 by tearing down and
    rebuilding perfectly good registration state.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.is_running = True
    runtime.registration_status = "registered"
    runtime.node_info = MagicMock(available_models=[])
    scheduler_client.heartbeat.side_effect = SchedulerError("boom", status_code=500)

    with (
        patch("node.runtime.detect_host_metrics", AsyncMock()) as metrics,
        patch("node.runtime.async_sleep", AsyncMock(side_effect=asyncio.CancelledError)),
    ):
        metrics.return_value.cpu_utilization = 1.0
        metrics.return_value.ram_available_gb = 1.0
        metrics.return_value.gpu_utilization = 1.0
        metrics.return_value.vram_available_gb = 1.0
        await runtime._heartbeat_loop()

    assert runtime.registration_status == "registered"
    assert runtime.registration_retry_task is None
    assert runtime.last_heartbeat_ok is False


# --- silence while unregistered ----------------------------------------------


@pytest.mark.anyio
async def test_nothing_is_sent_while_registration_is_outstanding(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """Both periodic loops stay quiet until there is a Scheduler that knows us.

    `/heartbeat` and `PUT /nodes/{id}/models` both 404 for an unknown node, so
    running them while pending would log an error every interval and say nothing
    the retry loop is not already handling.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.is_running = True
    runtime.registration_status = "pending"

    with patch("node.runtime.async_sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])):
        await runtime._heartbeat_loop()

    with patch("node.runtime.async_sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])):
        await runtime._model_refresh_loop()

    scheduler_client.heartbeat.assert_not_awaited()
    scheduler_client.update_models.assert_not_awaited()


# --- what the API reports during a degraded start ----------------------------


def _degraded_runtime() -> AsyncMock:
    """A runtime that came up but has not registered yet."""
    rt = AsyncMock()
    rt.is_running = True
    rt.registration_status = "pending"
    rt.settings.node_id = "test-node"
    rt.zenoh_client = MagicMock()
    rt.zenoh_client.is_connected.return_value = True
    rt.last_heartbeat_at = None
    rt.last_heartbeat_ok = False
    rt.last_heartbeat_error = None
    rt.ollama_client = AsyncMock()
    rt.ollama_client.health.return_value = True
    rt.start = AsyncMock()
    rt.stop = AsyncMock()
    return rt


def test_readiness_reports_degraded_while_unregistered() -> None:
    """`/health/ready` already described this state; the process just never reached it.

    503 with `scheduler_registered: false` is the correct answer for a node that is
    alive and serving locally but is not yet part of the network. Before this
    change the endpoint could not return it, because a node in that state was a
    process that had exited.
    """
    from fastapi.testclient import TestClient

    from node.main import app

    runtime = _degraded_runtime()

    with patch("node.main.Runtime", return_value=runtime), TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["runtime"] is True
    assert body["scheduler_registered"] is False
    assert body["inference_ready"] is False


def test_readiness_recovers_once_registration_lands() -> None:
    """The same node reports ready after the retry loop succeeds."""
    from fastapi.testclient import TestClient

    from node.main import app

    runtime = _degraded_runtime()
    runtime.registration_status = "registered"

    with patch("node.main.Runtime", return_value=runtime), TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["scheduler_registered"] is True


def test_local_api_still_serves_while_unregistered() -> None:
    """The node is useful to its own host even with no Scheduler in the picture.

    This is what "starts degraded" has to mean to be worth anything. Before, there
    was no process to ask.
    """
    from fastapi.testclient import TestClient

    from node.main import app

    runtime = _degraded_runtime()
    runtime.ollama_client.list_models.return_value = [
        ModelInfo(name="llama3-8b", size_gb=4.7, family="llama", context_length=8192)
    ]

    with patch("node.main.Runtime", return_value=runtime), TestClient(app) as client:
        health = client.get("/health")
        models = client.get("/models")

    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert models.status_code == 200
    assert [m["name"] for m in models.json()] == ["llama3-8b"]
