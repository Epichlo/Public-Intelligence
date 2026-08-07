"""Tests for durable Scheduler state (ROADMAP 2.1).

Every test here that claims something "survives a restart" proves it the only way
that means anything: it builds a **second, independent** `NodeRegistry` (or
`CreditLedger`, or FastAPI app) over the same database file and reads from that.
Reading back from the object that did the write would pass against a pure
in-memory implementation and prove nothing.

See specs/scheduler-persistence.md.
"""

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from scheduler.core.config import get_settings
from scheduler.core.credit_ledger import CreditLedger
from scheduler.main import build_store, create_app, lifespan
from scheduler.models.heartbeat import Heartbeat
from scheduler.models.node import GPUInfo, Node
from scheduler.persistence import SQLiteStore
from scheduler.registry.node_registry import NodeRegistry


def make_node(node_id: str = "node-1", models: list[str] | None = None) -> Node:
    """Build a node with real-looking hardware, not the 16 GB fiction 1.2 removed."""
    return Node(
        node_id=node_id,
        hostname=f"{node_id}.local",
        ip_address="127.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="NVIDIA GeForce RTX 3090", vram_total_gb=24.0, vram_available_gb=22.5),
        cpu_cores=8,
        ram_total_gb=32.0,
        available_models=models if models is not None else ["llama3:8b", "qwen2:7b"],
    )


async def reopen(db: Path) -> NodeRegistry:
    """Return a fresh registry loaded from `db` -- the "after the restart" object."""
    registry = NodeRegistry(store=SQLiteStore(db))
    await registry.load()
    return registry


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """A database path unique to this test."""
    return tmp_path / "scheduler.db"


# --- opt-in, and off by default --------------------------------------------


def test_an_app_built_with_no_store_persists_nothing() -> None:
    """`create_app()` must not consult settings for a store.

    If it read `SCHEDULER_DATABASE_PATH` itself, a developer with that set in their
    `.env` would silently turn persistence on underneath the whole test suite, and
    227 tests would start sharing one database file.
    """
    app = create_app()
    assert app.state.registry._store is None
    assert app.state.ledger._store is None


@pytest.mark.anyio
async def test_a_registry_with_no_store_still_works() -> None:
    """The storeless path is the existing class, unchanged. Everything still runs."""
    registry = NodeRegistry()
    await registry.register(make_node())
    assert await registry.count() == 1
    await registry.set_available_models("node-1", ["phi3"])
    await registry.unregister("node-1")
    assert await registry.count() == 0


# --- the fleet survives -----------------------------------------------------


@pytest.mark.anyio
async def test_a_registered_node_is_reconstructed_after_a_restart(db: Path) -> None:
    """The whole point: a second process over the same file knows the fleet."""
    first = NodeRegistry(store=SQLiteStore(db))
    await first.register(make_node())

    second = await reopen(db)

    restored = await second.get("node-1")
    assert restored is not None
    assert restored.hostname == "node-1.local"
    assert restored.gpu.name == "NVIDIA GeForce RTX 3090"
    assert restored.gpu.vram_total_gb == 24.0
    assert restored.available_models == ["llama3:8b", "qwen2:7b"]
    assert restored.cpu_cores == 8
    assert restored.ram_total_gb == 32.0


@pytest.mark.anyio
async def test_the_per_node_token_survives_a_restart(db: Path) -> None:
    """A restored node the Scheduler cannot authenticate to is not a restored node.

    The node's `/infer` fails closed (0.1), so losing the token means the Scheduler
    dispatches to a fleet that 401s it -- worse than not knowing the fleet at all,
    because matchmaking would still select those nodes.
    """
    first = NodeRegistry(store=SQLiteStore(db))
    await first.set_node_token("node-1", "tok-abc")
    await first.register(make_node())

    second = await reopen(db)

    assert second.get_node_token("node-1") == "tok-abc"


@pytest.mark.anyio
async def test_a_rotated_token_is_the_one_that_survives(db: Path) -> None:
    """Registration records the token before it attempts the create, on purpose.

    That ordering exists so a node whose token rotated refreshes it even when
    re-registration answers 409 (`api/nodes.py` docstring). If the rotation only
    reached memory, a restart would resurrect the stale token and every dispatch to
    that node would 401 -- reintroducing the exact bug the ordering was for.
    """
    store = SQLiteStore(db)
    first = NodeRegistry(store=store)
    await first.set_node_token("node-1", "tok-old")
    await first.register(make_node())

    # The 409 path: token set, register raises, nothing else happens.
    await first.set_node_token("node-1", "tok-new")
    with pytest.raises(ValueError, match="already registered"):
        await first.register(make_node())

    second = await reopen(db)

    assert second.get_node_token("node-1") == "tok-new"


@pytest.mark.anyio
async def test_a_whole_node_update_survives_a_restart(db: Path) -> None:
    """`update()` replaces the record wholesale; the stored copy must follow it."""
    first = NodeRegistry(store=SQLiteStore(db))
    await first.register(make_node())
    await first.update(
        make_node().model_copy(update={"hostname": "renamed.local", "region": "eu-west"})
    )

    second = await reopen(db)

    restored = await second.get("node-1")
    assert restored is not None
    assert restored.hostname == "renamed.local"
    assert restored.region == "eu-west"


@pytest.mark.anyio
async def test_clearing_a_token_removes_it_from_the_database(db: Path) -> None:
    """A node that presents no credential falls back to the fleet-wide token.

    If the clear reached memory only, a restart would resurrect a per-node token
    the node had stopped presenting, and the fallback path would stop being
    reachable for that node.
    """
    first = NodeRegistry(store=SQLiteStore(db))
    await first.register(make_node())
    await first.set_node_token("node-1", "tok-abc")
    await first.set_node_token("node-1", None)

    second = await reopen(db)

    assert second.get_node_token("node-1") is None


@pytest.mark.anyio
async def test_a_catalogue_refresh_survives_a_restart(db: Path) -> None:
    """1.4 made the catalogue track `ollama pull`/`rm`. A restart must not undo it."""
    first = NodeRegistry(store=SQLiteStore(db))
    await first.register(make_node(models=["llama3:8b"]))
    await first.set_available_models("node-1", ["llama3:8b", "mistral:7b"])

    second = await reopen(db)

    restored = await second.get("node-1")
    assert restored is not None
    assert restored.available_models == ["llama3:8b", "mistral:7b"]


# --- observations are deliberately not restored -----------------------------


@pytest.mark.anyio
async def test_live_observations_are_not_restored(db: Path) -> None:
    """Persist facts, not observations. See the table in the spec.

    `_mesh_nodes` is evidence of a live Zenoh session that died with the process;
    restoring it makes dispatch prefer a mesh queryable that no longer exists, so
    every request eats the 5s first-reply timeout before falling back to HTTP.
    A heartbeat is a reading from a moment that has passed.
    """
    first = NodeRegistry(store=SQLiteStore(db))
    await first.register(make_node())
    first.mark_mesh_reachable("node-1")
    await first.update_heartbeat(
        Heartbeat(
            node_id="node-1",
            timestamp=datetime.now(tz=UTC),
            status="online",
            queue_length=7,
            cpu_utilization=91.0,
            ram_available_gb=2.0,
            gpu_utilization=88.0,
            vram_available_gb=0.5,
        )
    )
    await first.increment_dampener("node-1")

    second = await reopen(db)

    assert await second.get("node-1") is not None, "the node itself is a fact and must return"
    assert second.is_mesh_reachable("node-1") is False
    assert await second.get_heartbeat("node-1") is None
    assert await second.get_dampener("node-1") == 0.0


@pytest.mark.anyio
async def test_a_restored_node_is_matchable_on_its_registered_vram(db: Path) -> None:
    """Dropping the heartbeat must not make the node unschedulable.

    `matchmaker.py` prefers the heartbeat's `vram_available_gb` and falls back to
    the node's registered figure. That fallback is what makes "do not restore
    heartbeats" safe rather than a repeat of the 1.3 bug, where every node was
    excluded from any task carrying `min_vram_gb`. Asserted here because the safety
    of one decision depends on code in another file.
    """
    from scheduler.core.matchmaker import CapabilityMatchmaker

    first = NodeRegistry(store=SQLiteStore(db))
    await first.register(make_node())

    second = await reopen(db)
    matchmaker = CapabilityMatchmaker(second)

    eligible = matchmaker.filter_nodes({"min_vram_gb": 20.0}, await second.list())
    assert [n.node_id for n in eligible] == ["node-1"]


# --- removal is durable too -------------------------------------------------


@pytest.mark.anyio
async def test_unregister_removes_the_node_and_its_token(db: Path) -> None:
    """A node that unregistered must not be resurrected by the next start."""
    first = NodeRegistry(store=SQLiteStore(db))
    await first.set_node_token("node-1", "tok-abc")
    await first.register(make_node())
    await first.unregister("node-1")

    second = await reopen(db)

    assert await second.count() == 0
    assert second.get_node_token("node-1") is None


@pytest.mark.anyio
async def test_stale_eviction_removes_the_node_durably(db: Path) -> None:
    """`unregister_node` is the path stale eviction and deathrattles take.

    It is a separate method from `unregister` (it tolerates an absent node), so it
    needs its own coverage or eviction would be undone by every restart.
    """
    first = NodeRegistry(store=SQLiteStore(db))
    await first.register(make_node())
    await first.unregister_node("node-1")

    second = await reopen(db)

    assert await second.count() == 0


@pytest.mark.anyio
async def test_clear_empties_the_database(db: Path) -> None:
    """`clear()` must not leave rows that a reload would resurrect."""
    first = NodeRegistry(store=SQLiteStore(db))
    await first.set_node_token("node-1", "tok-abc")
    await first.register(make_node())
    await first.clear()

    second = await reopen(db)

    assert await second.count() == 0
    assert second.get_node_token("node-1") is None


# --- isolation and damage tolerance -----------------------------------------


@pytest.mark.anyio
async def test_two_databases_do_not_see_each_other(tmp_path: Path) -> None:
    """Guards against a module-level or class-level connection being shared."""
    a = NodeRegistry(store=SQLiteStore(tmp_path / "a.db"))
    b = NodeRegistry(store=SQLiteStore(tmp_path / "b.db"))
    await a.register(make_node("node-a"))
    await b.register(make_node("node-b"))

    reopened_a = await reopen(tmp_path / "a.db")
    reopened_b = await reopen(tmp_path / "b.db")

    assert [n.node_id for n in await reopened_a.list()] == ["node-a"]
    assert [n.node_id for n in await reopened_b.list()] == ["node-b"]


@pytest.mark.anyio
async def test_a_row_that_no_longer_validates_costs_one_node_not_the_scheduler(
    db: Path,
) -> None:
    """Refusing to start over one bad row turns schema drift into a total outage.

    The node that row belonged to would have re-registered within
    `registration_retry_max_seconds` anyway (1.6), so skipping it costs one recovery
    window. Refusing to start costs the whole fleet.
    """
    first = NodeRegistry(store=SQLiteStore(db))
    await first.register(make_node("node-good"))

    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO nodes (node_id, payload) VALUES (?, ?)",
        ("node-bad", '{"node_id": "node-bad", "cpu_cores": "not a number"}'),
    )
    conn.commit()
    conn.close()

    second = await reopen(db)

    assert [n.node_id for n in await second.list()] == ["node-good"]


@pytest.mark.anyio
async def test_a_file_written_by_a_future_schema_is_reported_not_silently_coerced(
    db: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """There is no migration machinery, so a version mismatch has to be loud.

    Silently accepting it would mean rows quietly failing to validate one at a time
    with no statement of the cause. The stored version is left as it was, so the
    evidence of what wrote the file survives for whoever writes the migration.
    """
    # `load_nodes()` rather than bare construction: since ROADMAP C3 the store
    # connects lazily, because building the ASGI app at module scope would otherwise
    # create a database file merely by importing scheduler.main.
    store = SQLiteStore(db)
    await store.load_nodes()
    await store.close()

    conn = sqlite3.connect(db)
    conn.execute("UPDATE schema_meta SET value = '99' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    with caplog.at_level("ERROR"):
        store = SQLiteStore(db)
        # The check runs on first connect rather than in __init__, since C3 made
        # construction side-effect-free. It must still fire, and still not be fatal.
        loaded = await store.load_nodes()

    assert "persistence_schema_mismatch" in caplog.text
    assert loaded == [], "a mismatch must not be fatal"

    conn = sqlite3.connect(db)
    stored = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
    conn.close()
    assert stored == "99", "the version that was there must not be overwritten"


@pytest.mark.anyio
async def test_the_database_is_readable_again_after_close(db: Path) -> None:
    """The lifespan closes the store on shutdown; the next boot must still read it."""
    first = NodeRegistry(store=SQLiteStore(db))
    await first.register(make_node())
    assert first._store is not None
    await first._store.close()

    second = await reopen(db)

    assert await second.count() == 1


@pytest.mark.anyio
async def test_loading_an_absent_database_is_not_an_error(tmp_path: Path) -> None:
    """First boot has no file. It must create one rather than crash."""
    registry = await reopen(tmp_path / "does-not-exist-yet.db")
    assert await registry.count() == 0


@pytest.mark.anyio
async def test_a_nested_database_directory_is_created(tmp_path: Path) -> None:
    """`SCHEDULER_DATABASE_PATH=./data/scheduler.db` is what .env.example suggests.

    A container whose `./data` does not exist yet must not fail startup on it.
    """
    registry = NodeRegistry(store=SQLiteStore(tmp_path / "data" / "nested" / "scheduler.db"))
    await registry.load()
    await registry.register(make_node())

    assert await (await reopen(tmp_path / "data" / "nested" / "scheduler.db")).count() == 1


# --- the ledger -------------------------------------------------------------


@pytest.mark.anyio
async def test_the_ledger_reloads_earned_and_consumed_balances(db: Path) -> None:
    """The only state here that no one else can re-tell the Scheduler.

    A node can re-register and restate its hardware. Nothing can restate a balance,
    because the node never knew it. This is the unrecoverable half of 2.1.
    """
    first = CreditLedger(store=SQLiteStore(db))
    await first.record_host_contribution(node_id="node-1", vram_gb=24.0, duration_seconds=3600.0)
    await first.deduct_usage(account_id="node-1", amount=500.0)

    second = CreditLedger(store=SQLiteStore(db))
    await second.load()

    account = second.get_or_create_account("node-1")
    assert account.earned_credits == 2400.0
    assert account.consumed_credits == 500.0
    assert account.net_balance == 1900.0


@pytest.mark.anyio
async def test_a_balance_round_trips_without_being_rounded(db: Path) -> None:
    """Money must not lose precision to the storage format.

    A fractional accrual (17 seconds of a 24 GB card) is not representable in any
    fixed number of decimal places, so a column that stringified it would silently
    shave credits off every host on every restart.
    """
    first = CreditLedger(store=SQLiteStore(db))
    account = await first.record_host_contribution(
        node_id="node-1", vram_gb=24.0, duration_seconds=17.0
    )
    exact = account.earned_credits

    second = CreditLedger(store=SQLiteStore(db))
    await second.load()

    assert second.get_or_create_account("node-1").earned_credits == exact


@pytest.mark.anyio
async def test_an_account_that_never_earned_is_not_written(db: Path) -> None:
    """`get_or_create_account` is a read helper; a zeroed account is not a fact.

    Persisting it would let any caller that merely *asked* about an account grow the
    database, which matters once account ids come from requester credentials (3.1).
    """
    first = CreditLedger(store=SQLiteStore(db))
    first.get_or_create_account("never-earned-anything")

    second = CreditLedger(store=SQLiteStore(db))
    await second.load()

    assert second.balances() == {}


@pytest.mark.anyio
async def test_a_ledger_with_no_store_still_works() -> None:
    """Storeless is the existing class. `test_phase4_9_batch_credit` covers the maths."""
    ledger = CreditLedger()
    account = await ledger.record_host_contribution(
        node_id="node-1", vram_gb=1.0, duration_seconds=3600.0
    )
    assert account.earned_credits == 100.0


# --- the wiring -------------------------------------------------------------


def test_persistence_is_on_by_default_and_off_is_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """REVERSED by ROADMAP C3, and the original reasoning is worth keeping.

    This test used to assert the opposite -- `build_store() is None` with nothing
    configured -- on the argument that a default path on an ephemeral filesystem
    (Render's free tier, any plain container) survives a process restart and is
    wiped by every redeploy, which is durability that looks like it works.

    That argument was correct about that deployment.
    `docs/decisions/D6-is-there-a-network.md` then decided not to have it: this is a
    self-hosted product, the operator has a real disk, and the measured consequence
    of "off by default" was that **no deployment set it, so nothing persisted
    anywhere**. Losing every credit balance on every restart is the worse failure,
    because the ledger is the half nothing can reconstruct -- a node re-registers
    itself after a 404 heartbeat (ROADMAP 1.6); no one but this process ever knew a
    balance.

    So: on by default, and off is an explicit empty string that logs a warning.
    """
    monkeypatch.delenv("SCHEDULER_DATABASE_PATH", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    # The default is relative to the working directory, so this test would otherwise
    # drop a database file in whatever directory pytest happened to start in.
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    try:
        assert build_store() is not None, "persistence must be on with no configuration"
    finally:
        get_settings.cache_clear()

    monkeypatch.setenv("SCHEDULER_DATABASE_PATH", "")
    get_settings.cache_clear()
    try:
        assert build_store() is None, "an explicit empty path must still disable it"
    finally:
        get_settings.cache_clear()


def test_the_configured_database_path_is_what_gets_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`SCHEDULER_DATABASE_PATH` has to actually reach the store that is built."""
    target = tmp_path / "configured.db"
    monkeypatch.setenv("SCHEDULER_DATABASE_PATH", str(target))
    get_settings.cache_clear()
    try:
        store = build_store()
        assert isinstance(store, SQLiteStore)
        assert store.path == target
        # The file appears on first use, not on construction (ROADMAP C3): the ASGI
        # app is built at module scope, so an eager connect meant importing
        # scheduler.main created a database wherever the process was running.
        assert not target.exists(), "constructing a store must not touch the disk"

        asyncio.run(store.load_nodes())
        assert target.exists(), "the file is opened where it was configured"
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_the_lifespan_loads_persisted_state(db: Path) -> None:
    """The load has to be wired into startup, not just be a method that exists.

    ZenohRouter is patched out because opening a real session is not what this test
    is about; `zenoh.Config()` is left real since it is pure and cheap.
    """
    seed = NodeRegistry(store=SQLiteStore(db))
    await seed.register(make_node())

    app = create_app(store=SQLiteStore(db))
    with patch("scheduler.main.ZenohRouter"):
        async with lifespan(app):
            assert await app.state.registry.count() == 1


def test_a_node_registered_over_http_is_there_after_a_restart(db: Path) -> None:
    """End to end through the API, which is where the token ordering actually lives.

    `TestClient` as a context manager is what runs the lifespan, and so the load.
    """
    with patch("scheduler.main.ZenohRouter"):
        first_app = create_app(store=SQLiteStore(db))
        with TestClient(first_app) as client:
            response = client.post(
                "/nodes/register",
                json=make_node().model_dump(),
                headers={"X-Network-Auth-Token": "tok-from-the-wire"},
            )
            assert response.status_code == 201

        second_app = create_app(store=SQLiteStore(db))
        with TestClient(second_app) as client:
            listed = client.get(f"/nodes/{'node-1'}")
            assert listed.status_code == 200
            assert listed.json()["gpu"]["vram_total_gb"] == 24.0
            # Restored, but not claimed to be on the mesh -- that session is gone.
            assert listed.json()["reachability"] == "http"
            assert second_app.state.registry.get_node_token("node-1") == "tok-from-the-wire"
