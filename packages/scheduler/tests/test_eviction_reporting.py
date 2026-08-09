"""A node leaving the registry must be announced only if it left (ROADMAP 2.5).

`unregister_node` returned `None`, so `_evict_if_stale` logged
`zenoh_node_evicted_stale` after calling it regardless of outcome -- an
announcement that the *call was made*, dressed as a statement that the node was
evicted. On the consensus path the call does not touch the registry at all.

See specs/eviction-reports-what-it-did.md.
"""

import logging

import pytest
from structlog.testing import capture_logs

from scheduler.core.zenoh_router import ZenohRouter
from scheduler.models.node import GPUInfo, Node
from scheduler.registry.node_registry import NodeRegistry

NODE_ID = "node-1"


def make_node(node_id: str = NODE_ID) -> Node:
    return Node(
        node_id=node_id,
        hostname=f"{node_id}.local",
        ip_address="127.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3"],
    )


# --- the registry reports what it did ---------------------------------------


@pytest.mark.anyio
async def test_removing_a_present_node_reports_true() -> None:
    registry = NodeRegistry()
    await registry.register(make_node())

    assert await registry.local_unregister_node(NODE_ID) is True
    assert await registry.count() == 0


@pytest.mark.anyio
async def test_removing_an_absent_node_reports_false() -> None:
    """`local_unregister_node` is "safe if not present" -- it pops with defaults.

    That safety is correct; being unable to tell the two cases apart is not.
    """
    registry = NodeRegistry()

    assert await registry.local_unregister_node("never-registered") is False


@pytest.mark.anyio
async def test_unregister_reports_whether_the_node_is_actually_gone() -> None:
    """ROADMAP 2.5's property, on the only path that still exists.

    This used to drive a fake consensus engine that dropped proposals, because on
    that path `unregister_node` could not know whether the removal had applied and
    so reported whether the node was absent *afterwards* -- a weaker claim, and the
    true one. The consensus path is gone (ROADMAP C2), so the weaker phrasing is no
    longer needed and the property is asserted directly: the return value tracks
    what happened, not what was attempted.
    """
    registry = NodeRegistry()
    await registry.register(make_node())

    assert await registry.unregister_node(NODE_ID) is True
    assert not await registry.exists(NODE_ID)

    # And again, when there is nothing left to remove.
    assert await registry.unregister_node(NODE_ID) is False


# --- the router logs what happened ------------------------------------------
#
# `structlog.testing.capture_logs` rather than pytest's `caplog`: the router logs
# through structlog, which by default renders to stdout instead of routing into
# stdlib logging, so `caplog` captures NOTHING from it. Two of these tests were
# written with `caplog` first and failed; a third PASSED, because it asserted a
# string was absent and every string is absent from an empty capture. Asserting on
# nothing looks identical to asserting successfully.


@pytest.mark.anyio
async def test_a_real_eviction_is_logged_as_one() -> None:
    registry = NodeRegistry()
    await registry.register(make_node())
    router = ZenohRouter(registry)
    router.node_stale_after_seconds = 0.0

    with capture_logs() as logs:
        evicted = await router._evict_if_stale(NODE_ID)

    events = [entry["event"] for entry in logs]
    assert evicted is True
    assert "zenoh_node_evicted_stale" in events


@pytest.mark.anyio
async def test_an_eviction_that_removed_nothing_is_not_logged_as_a_success() -> None:
    """The exact defect ROADMAP 2.5 named.

    The old code announced `zenoh_node_evicted_stale` on the strength of having
    *asked*, so a removal that changed nothing was logged as a success and "where
    did node X go" was answered wrongly.
    """

    # A registry that reports the node present and then removes nothing.
    #
    # This used to be induced with a fake consensus engine that dropped proposals.
    # That path is gone (ROADMAP C2), and with it the easy way to reach this state
    # -- but not the state itself: `_evict_if_stale` checks `exists()` and then
    # calls `unregister_node`, and another task can remove the node in between. The
    # router's contract is what is under test, so the registry is the double.
    class RemovesNothing(NodeRegistry):
        async def exists(self, node_id: str) -> bool:
            return True

        async def unregister_node(self, node_id: str) -> bool:
            return False

    registry = RemovesNothing()
    router = ZenohRouter(registry)
    router.node_stale_after_seconds = 0.0

    with capture_logs() as logs:
        evicted = await router._evict_if_stale(NODE_ID)

    events = [entry["event"] for entry in logs]
    assert evicted is False
    assert "zenoh_node_evicted_stale" not in events
    assert "zenoh_node_eviction_had_no_effect" in events


@pytest.mark.anyio
async def test_a_fresh_node_is_neither_evicted_nor_reported() -> None:
    """Declining to evict is not a failure and must not read like one."""
    import time

    registry = NodeRegistry()
    await registry.register(make_node())
    router = ZenohRouter(registry)
    router.node_stale_after_seconds = 300.0
    router._last_verified_heartbeat[NODE_ID] = time.monotonic()

    with capture_logs() as logs:
        evicted = await router._evict_if_stale(NODE_ID)

    events = [entry["event"] for entry in logs]
    assert evicted is False
    assert "zenoh_node_evicted_stale" not in events
    assert "zenoh_node_eviction_had_no_effect" not in events
    # Proves the capture is live, so the two absences above mean something.
    assert events, "captured no log events at all -- the assertions above are vacuous"
    assert "zenoh_node_still_fresh" in events


# --- the graceful path says something too -----------------------------------


@pytest.mark.anyio
async def test_a_graceful_unregister_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """The two ways a node can leave were asymmetric: one over-reported, one silent.

    "Where did node X go" should be answerable by one grep, not inferred from a
    node's absence from a later listing.
    """
    registry = NodeRegistry()
    await registry.register(make_node())

    with caplog.at_level(logging.INFO):
        await registry.unregister(NODE_ID)

    assert "node_departed" in caplog.text
    assert NODE_ID in caplog.text
