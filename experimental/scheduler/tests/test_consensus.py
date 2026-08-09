"""Integration tests for the Raft-based consensus state replication."""

import asyncio
from unittest.mock import AsyncMock

import pytest
import zenoh
from scheduler.models.node import GPUInfo, Node
from scheduler.registry.node_registry import NodeRegistry

from experimental.scheduler.consensus import RaftConsensusEngine


@pytest.fixture()
def test_node() -> Node:
    """Fixture providing a mock Node."""
    return Node(
        node_id="test-node-consensus",
        hostname="test-host",
        ip_address="127.0.0.1",
        region="local",
        gpu=GPUInfo(name="unknown", vram_total_gb=16.0, vram_available_gb=16.0),
        cpu_cores=4,
        ram_total_gb=16.0,
        available_models=["llama2"],
    )


@pytest.fixture()
def test_node_partition() -> Node:
    """Fixture providing a second mock Node for partition testing."""
    return Node(
        node_id="partition-node-consensus",
        hostname="partition-host",
        ip_address="127.0.0.1",
        region="local",
        gpu=GPUInfo(name="unknown", vram_total_gb=16.0, vram_available_gb=16.0),
        cpu_cores=4,
        ram_total_gb=16.0,
        available_models=["llama2"],
    )


@pytest.mark.asyncio
async def test_consensus_leader_election_and_replication(
    test_node: Node, test_node_partition: Node
) -> None:
    """Test leader election, log replication, and minority partition blocking."""
    # 1. Initialize registries and consensus engines
    r1 = NodeRegistry()
    r2 = NodeRegistry()
    r3 = NodeRegistry()

    # Configure Zenoh to connect locally without wide-area mesh scouting to be fast
    config = zenoh.Config()

    c1 = RaftConsensusEngine("sched-1", r1, config)
    c2 = RaftConsensusEngine("sched-2", r2, config)
    c3 = RaftConsensusEngine("sched-3", r3, config)

    # 2. Start the consensus cluster
    await c1.start()
    await c2.start()
    await c3.start()

    try:
        # Wait up to 5 seconds for leader election to complete
        leader_engine = None
        for _ in range(50):
            if c1.state == "LEADER":
                leader_engine = c1
                break
            if c2.state == "LEADER":
                leader_engine = c2
                break
            if c3.state == "LEADER":
                leader_engine = c3
                break
            await asyncio.sleep(0.1)

        assert leader_engine is not None, "Consensus leader was not elected"

        # 3. Propose node registration on the leader
        await leader_engine.propose("register", test_node.model_dump())

        # Wait a short moment for logs to replicate and commit
        await asyncio.sleep(0.5)

        # Assert node is registered in all three registries (atomic replication)
        assert await r1.exists(test_node.node_id) is True
        assert await r2.exists(test_node.node_id) is True
        assert await r3.exists(test_node.node_id) is True

        # 4. Simulate a minority network partition: stop c3
        await c3.stop()

        # Wait for a new leader to be elected between c1 and c2 (failover election)
        new_leader = None
        for _ in range(30):
            if c1.state == "LEADER":
                new_leader = c1
                break
            if c2.state == "LEADER":
                new_leader = c2
                break
            await asyncio.sleep(0.1)

        assert new_leader is not None, "Failover leader was not elected"

        # Propose another registration (should still succeed since 2/3 is a majority quorum)
        await new_leader.propose("register", test_node_partition.model_dump())

        await asyncio.sleep(0.5)
        assert await r1.exists(test_node_partition.node_id) is True
        assert await r2.exists(test_node_partition.node_id) is True

        # 5. Simulate loss of quorum: stop c2
        await c2.stop()

        # Propose registration on c1 (should fail/timeout since only 1/3 is active)
        failed_node = Node(
            node_id="failed-node-consensus",
            hostname="failed-host",
            ip_address="127.0.0.1",
            region="local",
            gpu=GPUInfo(name="unknown", vram_total_gb=16.0, vram_available_gb=16.0),
            cpu_cores=4,
            ram_total_gb=16.0,
            available_models=["llama2"],
        )

        with pytest.raises((TimeoutError, RuntimeError)):
            await c1.propose("register", failed_node.model_dump())

    finally:
        # Cleanup
        await c1.stop()
        await c2.stop()
        await c3.stop()


@pytest.mark.asyncio
async def test_single_node_proposal_is_applied_to_registry(test_node: Node) -> None:
    """A no-peer cluster must apply its own proposals -- it is its own majority.

    Regression guard. `propose` only set `event_to_wait` when peers existed, while
    the immediate-commit branch required `required_quorum <= 1`, which is only true
    when peers is empty. The two conditions were mutually exclusive, so the apply
    call was unreachable: entries were appended to the log and never applied, and
    both `register` and `unregister_node` route through this path.

    This stranded every state change on a single-instance deployment while the
    caller saw success. It surfaced only on Windows CI, where the consensus engine
    could bind an already-listening port and so became active where POSIX fell
    back to direct local mutation -- the platform merely selected the branch.
    """
    registry = NodeRegistry()
    engine = RaftConsensusEngine("scheduler-single", registry)

    # Simulate a live single-instance deployment: active, elected, and peerless.
    engine._is_active = True
    engine.peers = set()
    engine._send_heartbeats = AsyncMock()

    # Proposed DIRECTLY on the engine rather than through `registry.register`.
    #
    # The registry used to route its writes through `consensus_engine.propose` when
    # one was attached, and this test drove that seam. ROADMAP C2 removed the
    # integration -- the engine's only inbound channel was an unauthenticated
    # wildcard Zenoh subscriber that could evict and inject nodes -- so the registry
    # now always mutates locally and there is no seam left to drive.
    #
    # The bug this guards is the engine's own, and is still worth guarding while the
    # module is kept for a possible v2: `propose` only set `event_to_wait` when peers
    # existed, while the immediate-commit branch required `required_quorum <= 1`,
    # true only when peers is EMPTY. The two were mutually exclusive, so the apply
    # call was unreachable and entries were appended and never applied.
    await engine.propose("register", test_node.model_dump())
    assert await registry.exists(test_node.node_id) is True, (
        "the proposal was appended to the log and never applied"
    )
    assert engine.commit_index == 0, "commit index did not advance past the append"

    await engine.propose("unregister_node", {"node_id": test_node.node_id})
    assert await registry.exists(test_node.node_id) is False, (
        "the unregister proposal was appended to the log and never applied"
    )
    assert engine.commit_index == 1, "commit index did not advance past the append"
