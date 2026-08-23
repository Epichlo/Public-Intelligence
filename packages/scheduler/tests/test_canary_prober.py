"""The canary quarantine is wired to live dispatch (decision D1).

`CanaryVerifier.record` used to be reachable only from tests: no background task,
route or script ever scored a node's reply against a canary, so `is_quarantined`
-- which the matchmaker reads -- could structurally never become True while
docs/PREMISES.md P4 cited the module as an implemented integrity mechanism.

These tests pin the dispatch half: the prober sends real canaries down the
ordinary inference path, records what comes back, survives its own failures, and
stops cleanly at shutdown. The exclusion half (a quarantined node is skipped by
`Scheduler.select_node`) is pinned beside the matchmaker's in
test_canary_verification.py.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scheduler.core.canary import CANARIES, CanaryProber, CanaryVerifier
from scheduler.core.config import Settings
from scheduler.core.node_dispatch import NodeDispatchError
from scheduler.core.zenoh_router import ZenohRouter
from scheduler.main import create_app
from scheduler.models.node import GPUInfo, Node
from scheduler.registry.node_registry import NodeRegistry
from scheduler.scheduler.algorithm import Scheduler

CAPITAL = CANARIES[0]


def _node(node_id: str) -> Node:
    return Node(
        node_id=node_id,
        hostname=f"{node_id}.local",
        ip_address="10.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=8,
        ram_total_gb=32.0,
        available_models=["llama3"],
    )


async def _register_heartbeats(registry: NodeRegistry, nodes: list[Node]) -> None:
    from datetime import UTC, datetime

    from scheduler.models.heartbeat import Heartbeat

    for node in nodes:
        await registry.local_register(node)
        await registry.update_heartbeat(
            Heartbeat(
                node_id=node.node_id,
                timestamp=datetime.now(tz=UTC),
                status="online",
                queue_length=0,
                cpu_utilization=0.0,
                ram_available_gb=16.0,
                gpu_utilization=0.0,
                vram_available_gb=20.0,
            )
        )


def _prober(
    registry: NodeRegistry, verifier: CanaryVerifier, interval: float = 3600.0
) -> CanaryProber:
    return CanaryProber(
        registry,
        verifier,
        settings=Settings(network_auth_token="t"),
        mesh_client=None,
        interval=interval,
    )


# --- a failing canary leads to quarantine and exclusion ----------------------


@pytest.mark.asyncio
async def test_a_failing_canary_reply_quarantines_the_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = NodeRegistry()
    await _register_heartbeats(registry, [_node("liar"), _node("good")])

    async def fake_infer(**kwargs: Any) -> dict[str, str]:
        return {"model": kwargs["model"], "response": "token_556"}

    monkeypatch.setattr("scheduler.core.canary.infer_once", fake_infer)

    verifier = CanaryVerifier(failures_before_quarantine=1)
    prober = _prober(registry, verifier)

    assert await prober.check_one_node() is False
    assert verifier.is_quarantined("liar") is True


@pytest.mark.asyncio
async def test_a_quarantined_node_is_excluded_from_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = NodeRegistry()
    nodes = [_node("liar"), _node("good")]
    await _register_heartbeats(registry, nodes)

    async def fake_infer(**kwargs: Any) -> dict[str, str]:
        return {"model": kwargs["model"], "response": "token_556"}

    monkeypatch.setattr("scheduler.core.canary.infer_once", fake_infer)

    verifier = CanaryVerifier(failures_before_quarantine=1)
    prober = _prober(registry, verifier)
    await prober.check_one_node()  # probes "liar" (insertion order)

    scheduler = Scheduler(registry, canary=verifier)
    assert (await scheduler.select_node("llama3")).node_id == "good"


@pytest.mark.asyncio
async def test_a_passing_reply_is_recorded_as_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = NodeRegistry()
    await _register_heartbeats(registry, [_node("honest")])

    async def fake_infer(**kwargs: Any) -> dict[str, str]:
        return {"model": kwargs["model"], "response": "Paris"}

    monkeypatch.setattr("scheduler.core.canary.infer_once", fake_infer)

    verifier = CanaryVerifier()
    prober = _prober(registry, verifier)

    assert await prober.check_one_node() is True
    assert verifier.is_quarantined("honest") is False
    assert verifier.state_for("honest").passes == 1


# --- dispatch failures are not evidence --------------------------------------


@pytest.mark.asyncio
async def test_a_dispatch_failure_is_not_canary_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A node that cannot be reached is the staleness sweep's problem.

    Quarantining on transport errors would evict nodes for being offline --
    the availability surface degrading -- rather than for lying about answers.
    """

    async def fake_infer(**kwargs: Any) -> dict[str, str]:
        raise NodeDispatchError("connection refused", status=502)

    monkeypatch.setattr("scheduler.core.canary.infer_once", fake_infer)

    registry = NodeRegistry()
    await _register_heartbeats(registry, [_node("offline")])

    verifier = CanaryVerifier(failures_before_quarantine=1)
    prober = _prober(registry, verifier)

    for _ in range(5):
        assert await prober.check_one_node() is False

    assert verifier.is_quarantined("offline") is False
    assert verifier.state_for("offline").failures == 0


# --- the loop survives its own failures --------------------------------------


@pytest.mark.asyncio
async def test_an_unexpected_exception_does_not_kill_the_loop(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Canary infrastructure must never take dispatch down with it.

    The fake dispatch fails twice with an exception no one expects, then
    recovers. The loop must log, keep running, and record the eventual pass.
    """
    calls = {"n": 0}

    async def fake_infer(**kwargs: Any) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("exploded")
        return {"model": kwargs["model"], "response": "Paris"}

    monkeypatch.setattr("scheduler.core.canary.infer_once", fake_infer)

    registry = NodeRegistry()
    await _register_heartbeats(registry, [_node("n1")])

    verifier = CanaryVerifier()
    prober = _prober(registry, verifier, interval=0.01)
    with caplog.at_level(logging.ERROR):
        prober.start()
        for _ in range(200):
            await asyncio.sleep(0.01)
            if verifier.state_for("n1").passes > 0:
                break
        await prober.stop()

    assert verifier.state_for("n1").passes == 1
    assert not prober._task or prober._task.cancelled()
    assert "canary_probe_failed_unexpectedly" in caplog.text


# --- rotation and no-op ticks ------------------------------------------------


@pytest.mark.asyncio
async def test_probes_rotate_over_the_whole_fleet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probed: list[str] = []

    async def fake_infer(**kwargs: Any) -> dict[str, str]:
        probed.append(kwargs["node_id"])
        return {"model": kwargs["model"], "response": "Paris"}

    monkeypatch.setattr("scheduler.core.canary.infer_once", fake_infer)

    registry = NodeRegistry()
    await _register_heartbeats(registry, [_node("a"), _node("b")])

    prober = _prober(registry, CanaryVerifier())
    for _ in range(4):
        await prober.check_one_node()

    assert probed == ["a", "b", "a", "b"]


@pytest.mark.asyncio
async def test_an_empty_fleet_is_a_no_op() -> None:
    prober = _prober(NodeRegistry(), CanaryVerifier())
    assert await prober.check_one_node() is False


@pytest.mark.asyncio
async def test_a_node_with_no_models_is_skipped_without_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_infer(**kwargs: Any) -> dict[str, str]:
        raise AssertionError("dispatch must not be attempted for a model-less node")

    monkeypatch.setattr("scheduler.core.canary.infer_once", fake_infer)

    registry = NodeRegistry()
    bare = _node("bare")
    bare = bare.model_copy(update={"available_models": []})
    await registry.local_register(bare)

    verifier = CanaryVerifier()
    prober = _prober(registry, verifier)

    assert await prober.check_one_node() is False
    assert verifier.state_for("bare").last_checked_at == 0.0


# --- lifecycle ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_stop_is_clean_and_idempotent() -> None:
    registry = NodeRegistry()
    await registry.local_register(_node("n1"))
    prober = _prober(registry, CanaryVerifier(), interval=60.0)

    prober.start()
    task = prober._task
    assert task is not None
    prober.start()  # second start must not spawn a second loop
    assert prober._task is task

    await prober.stop()
    assert task.cancelled()
    assert prober._task is None

    await prober.stop()  # idempotent


@pytest.mark.asyncio
async def test_a_non_positive_interval_disables_the_prober() -> None:
    registry = NodeRegistry()
    await registry.local_register(_node("n1"))
    prober = _prober(registry, CanaryVerifier(), interval=0.0)

    prober.start()
    assert prober._task is None


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_the_prober(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring itself: the task the app runs is the one shutdown cancels.

    `ZenohRouter.start` is stubbed so the lifespan never opens a real Zenoh
    session; the prober is what is under test here, and with no session it
    simply dispatches over HTTP like any other mesh-less caller would.
    """
    monkeypatch.setattr(ZenohRouter, "start", lambda self: None)
    lifespan_settings = Settings(network_auth_token="t", canary_check_interval_seconds=3600.0)
    monkeypatch.setattr("scheduler.main.get_settings", lambda: lifespan_settings)

    app = create_app()
    with TestClient(app) as client:
        prober: CanaryProber = client.app.state.canary_prober
        task = prober._task
        assert task is not None
        assert not task.done()

    assert prober._task is None
    assert task.cancelled()
