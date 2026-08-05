"""The advertised model catalogue tracks what Ollama actually has (roadmap 1.4).

Before this, `list_models()` had exactly one caller -- `Runtime.start()` -- so the
catalogue the Scheduler held was frozen at node startup. `ollama pull` produced a
model the fleet could not route to; `ollama rm` left the Scheduler advertising and
dispatching to a model that was gone. Restarting the node did not fix either,
because re-registration answers 409 and heartbeats carry no model list.

These cover the node half: when a push happens, when it deliberately does not, and
what happens when Ollama or the Scheduler is unreachable at the moment we look.
`packages/scheduler/tests/api/test_model_catalogue_update.py` covers the endpoint,
and `tests/test_wire_contract.py` covers the payload between them.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from node.core.configuration import Settings
from node.models import ModelInfo
from node.models.gpu_info import cpu_only_gpu
from node.runtime import Runtime


def model(name: str, size_gb: float = 4.7) -> ModelInfo:
    """Build a ModelInfo; only `name` is load-bearing for the catalogue."""
    return ModelInfo(name=name, size_gb=size_gb, family="llama", context_length=8192)


@pytest.fixture
def settings() -> Settings:
    """Settings with intervals short enough that a loop tick is observable."""
    return Settings(
        node_id="test-node",
        hostname="localhost",
        region="local",
        heartbeat_interval_seconds=1,
        model_refresh_interval_seconds=1,
    )


@pytest.fixture
def scheduler_client() -> AsyncMock:
    """A Scheduler client whose `register` reports a freshly created record."""
    client = AsyncMock()
    client.register.return_value = True
    return client


@pytest.fixture
def ollama_client() -> AsyncMock:
    """An Ollama client hosting one model."""
    client = AsyncMock()
    client.list_models.return_value = [model("llama3-8b")]
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


# --- change detection ------------------------------------------------------


@pytest.mark.anyio
async def test_a_pulled_model_is_pushed(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A model appearing in Ollama reaches the Scheduler on the next refresh."""
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.advertised_models = [model("llama3-8b")]
    runtime.catalogue_synced = True

    ollama_client.list_models.return_value = [model("llama3-8b"), model("mistral-7b")]
    await runtime._refresh_model_catalogue()

    scheduler_client.update_models.assert_awaited_once()
    node_id, pushed = scheduler_client.update_models.await_args.args
    assert node_id == "test-node"
    assert sorted(m.name for m in pushed) == ["llama3-8b", "mistral-7b"]
    assert runtime.advertised_models == pushed


@pytest.mark.anyio
async def test_a_removed_model_is_pushed(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A model disappearing from Ollama is withdrawn from the Scheduler.

    This is the direction that produced failed requests: the Scheduler kept
    advertising the model in `GET /v1/models` and kept selecting this node for it,
    and the node's own Ollama then answered 404.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.advertised_models = [model("llama3-8b"), model("mistral-7b")]
    runtime.catalogue_synced = True

    ollama_client.list_models.return_value = [model("llama3-8b")]
    await runtime._refresh_model_catalogue()

    _, pushed = scheduler_client.update_models.await_args.args
    assert [m.name for m in pushed] == ["llama3-8b"]


@pytest.mark.anyio
async def test_an_unchanged_catalogue_sends_nothing(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """Refreshing repeatedly with no change puts nothing on the wire.

    The catalogue is near-constant. At a 60s interval, re-sending it every tick
    would be ~1,440 requests per node per day to communicate nothing.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.advertised_models = [model("llama3-8b")]
    runtime.catalogue_synced = True

    await runtime._refresh_model_catalogue()
    await runtime._refresh_model_catalogue()
    await runtime._refresh_model_catalogue()

    scheduler_client.update_models.assert_not_awaited()


@pytest.mark.anyio
async def test_reordering_is_not_a_change(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """The same models in a different order is not a catalogue change.

    Ollama does not promise an order, and the Scheduler does membership tests and
    sorts for `/v1/models`, so a reorder is invisible to everything downstream.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.advertised_models = [model("llama3-8b"), model("mistral-7b")]
    runtime.catalogue_synced = True

    ollama_client.list_models.return_value = [model("mistral-7b"), model("llama3-8b")]
    await runtime._refresh_model_catalogue()

    scheduler_client.update_models.assert_not_awaited()


@pytest.mark.anyio
async def test_metadata_only_change_is_not_a_change(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A changed size with the same names sends nothing.

    `available_models` on the Scheduler is `list[str]`; size, family, and context
    length have never reached it, so a change to them cannot affect any decision
    it makes.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.advertised_models = [model("llama3-8b", size_gb=4.7)]
    runtime.catalogue_synced = True

    ollama_client.list_models.return_value = [model("llama3-8b", size_gb=5.2)]
    await runtime._refresh_model_catalogue()

    scheduler_client.update_models.assert_not_awaited()


# --- failure handling ------------------------------------------------------


@pytest.mark.anyio
async def test_ollama_failure_keeps_the_advertised_catalogue(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """An unreachable Ollama does not unadvertise the node's models.

    "I cannot reach Ollama right now" is not "I have no models". Treating it as
    such would drop the node out of matchmaking on a transient blip and re-add it
    seconds later, flapping the fleet catalogue.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    advertised = [model("llama3-8b")]
    runtime.advertised_models = advertised
    runtime.catalogue_synced = True

    ollama_client.list_models.side_effect = ConnectionError("ollama is down")
    await runtime._refresh_model_catalogue()

    scheduler_client.update_models.assert_not_awaited()
    assert runtime.advertised_models == advertised
    assert runtime.catalogue_synced is True


@pytest.mark.anyio
async def test_a_failed_push_is_retried_on_the_next_refresh(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A push that does not land is not recorded as advertised.

    Recording it would make the node believe the Scheduler agrees, and it would
    never retry -- one dropped request would leave the fleet catalogue wrong for
    the life of the process. Because `advertised_models` still holds the old list,
    the next refresh sees a difference again and pushes again on its own.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    runtime.advertised_models = [model("llama3-8b")]
    runtime.catalogue_synced = True

    ollama_client.list_models.return_value = [model("llama3-8b"), model("mistral-7b")]
    scheduler_client.update_models.side_effect = ConnectionError("scheduler unreachable")
    await runtime._refresh_model_catalogue()

    assert [m.name for m in runtime.advertised_models] == ["llama3-8b"]

    scheduler_client.update_models.side_effect = None
    await runtime._refresh_model_catalogue()

    assert sorted(m.name for m in runtime.advertised_models) == ["llama3-8b", "mistral-7b"]
    assert runtime.catalogue_synced is True
    assert scheduler_client.update_models.await_count == 2


# --- startup -----------------------------------------------------------------


@pytest.mark.anyio
async def test_fresh_registration_does_not_push(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """When the Scheduler creates the record, the catalogue rode along with it."""
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    scheduler_client.register.return_value = True

    with patch("node.runtime.detect_gpu", AsyncMock(return_value=cpu_only_gpu())):
        try:
            await runtime.start()
            scheduler_client.update_models.assert_not_awaited()
            assert runtime.catalogue_synced is True
        finally:
            await runtime.stop()


@pytest.mark.anyio
async def test_registration_conflict_pushes_the_current_catalogue(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A 409 means the Scheduler holds an earlier process's catalogue; correct it.

    This is the restart case. `SchedulerClient.register` swallows the 409, so
    without this push the node would run normally while the Scheduler advertised
    whatever the previous process had pulled.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    scheduler_client.register.return_value = False
    ollama_client.list_models.return_value = [model("llama3-8b"), model("qwen2-7b")]

    with patch("node.runtime.detect_gpu", AsyncMock(return_value=cpu_only_gpu())):
        try:
            await runtime.start()
            scheduler_client.update_models.assert_awaited_once()
            _, pushed = scheduler_client.update_models.await_args.args
            assert sorted(m.name for m in pushed) == ["llama3-8b", "qwen2-7b"]
        finally:
            await runtime.stop()


@pytest.mark.anyio
async def test_conflict_with_no_local_models_still_corrects_the_scheduler(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """A node that has removed every model can still say so after a restart.

    This is why `catalogue_synced` exists rather than relying on list comparison
    alone: both sides of the comparison would be empty here, so a pure
    "is it different from what I advertised" check would never push, and the
    Scheduler would keep offering models this node no longer has.
    """
    runtime = build_runtime(settings, scheduler_client, ollama_client)
    scheduler_client.register.return_value = False
    ollama_client.list_models.return_value = []

    with patch("node.runtime.detect_gpu", AsyncMock(return_value=cpu_only_gpu())):
        try:
            await runtime.start()
            scheduler_client.update_models.assert_awaited_once()
            _, pushed = scheduler_client.update_models.await_args.args
            assert pushed == []
        finally:
            await runtime.stop()


# --- loop wiring -------------------------------------------------------------


@pytest.mark.anyio
async def test_refresh_task_runs_and_is_cancelled_on_stop(
    settings: Settings, scheduler_client: AsyncMock, ollama_client: AsyncMock
) -> None:
    """The refresh loop is a real background task with a real interval sleep.

    Asserting the loop is wired at all, separately from what a refresh decides:
    the change-detection tests above drive `_refresh_model_catalogue` directly and
    would all still pass if nothing ever called it.
    """
    # Keyed off a second `list_models` call rather than off the patched sleep: the
    # heartbeat loop shares `async_sleep`, so a sleep-triggered event would fire
    # without the refresh loop having run at all.
    refreshed = asyncio.Event()
    calls = 0

    async def counting_list_models() -> list[ModelInfo]:
        nonlocal calls
        calls += 1
        if calls >= 2:
            refreshed.set()
        return [model("llama3-8b")]

    async def instant_sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    ollama_client.list_models.side_effect = counting_list_models
    runtime = build_runtime(settings, scheduler_client, ollama_client)

    with (
        patch("node.runtime.detect_gpu", AsyncMock(return_value=cpu_only_gpu())),
        patch("node.runtime.async_sleep", instant_sleep),
    ):
        try:
            await runtime.start()
            assert runtime.model_refresh_task is not None
            # Once from `start()`, then at least once more from the loop having got
            # past its interval sleep.
            await asyncio.wait_for(refreshed.wait(), timeout=5.0)
        finally:
            await runtime.stop()

    assert runtime.model_refresh_task is None
