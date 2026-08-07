"""Persistence is on by default, and the rate limiter says what it is (C3, C5).

**C3.** `SCHEDULER_DATABASE_PATH` was unset by default and no deployment set it, so
nothing persisted anywhere. The original reasoning was sound at the time: a default
path on an ephemeral filesystem (Render's free tier) survives a process restart and
is wiped by every redeploy, which is durability that looks like it works.

[D6](../../../docs/decisions/D6-is-there-a-network.md) removed that deployment. This
is a self-hosted product now, so the operator has a real disk, and the balance
flips: the ledger is the unrecoverable half of the state (a node re-registers itself
after a 404 heartbeat since ROADMAP 1.6; nothing but the Scheduler ever knew a
balance), so losing it silently on every restart is the worse default.

Persistence is therefore **on**, at a predictable path, and turning it off is an
explicit `SCHEDULER_DATABASE_PATH=""` that logs a warning naming what is lost.

**C5.** The token bucket is in-memory and per-instance, and [D5](../../../docs/decisions/D5-decentralisation-claim.md)
decided the deployment *is* a single instance -- so it is adequate and the honest
description is "abuse dampener", not "quota". Two things did need fixing: it was
configured by constructor defaults no operator could reach, and `buckets` grew
without bound, one entry per tenant, forever.
"""

from __future__ import annotations

import asyncio

import pytest

from scheduler.core.config import Settings
from scheduler.core.rate_limiter import TokenBucketLimiter

# --- C3: persistence -------------------------------------------------------


def test_persistence_is_on_by_default() -> None:
    """A Scheduler started with no configuration keeps its ledger across restarts."""
    assert Settings(network_auth_token="t" * 64).database_path, (
        "database_path is empty by default, so nothing persists and every restart "
        "silently loses every credit balance."
    )


def test_persistence_can_still_be_turned_off_explicitly() -> None:
    """Off must remain reachable -- some deployments genuinely want ephemeral state."""
    settings = Settings(network_auth_token="t" * 64, database_path="")
    assert not settings.database_path


def test_create_app_still_does_not_read_the_setting() -> None:
    """The isolation property that made the old default safe must survive the change.

    `create_app()` never consults settings for the store, so an ambient
    `SCHEDULER_DATABASE_PATH` in a developer's `.env` cannot point the whole test
    suite at one shared database. Turning the default ON makes this MORE important,
    not less: without it, every test in this repo would now share a file.
    """
    import inspect

    from scheduler.main import create_app

    source = inspect.getsource(create_app)
    assert "database_path" not in source, (
        "create_app now reads database_path. Every test would share one database "
        "file, and test order would start deciding outcomes."
    )


def test_build_store_is_the_only_reader() -> None:
    import inspect

    from scheduler.main import build_store

    assert "database_path" in inspect.getsource(build_store)


# --- C5: rate limiting -----------------------------------------------------


def test_rate_limit_is_configurable_by_an_operator() -> None:
    """Capacity and refill were constructor defaults nothing exposed.

    An operator could not change the limit without editing source, which makes
    "capacity 5, refill 0.5/s" a property of the code rather than of the deployment.
    """
    settings = Settings(
        network_auth_token="t" * 64,
        rate_limit_capacity=42,
        rate_limit_refill_per_second=7.5,
    )
    assert settings.rate_limit_capacity == 42
    assert settings.rate_limit_refill_per_second == 7.5


async def test_idle_tenants_are_evicted_so_the_bucket_map_stays_bounded() -> None:
    """`buckets` grew one entry per tenant and never shrank.

    On a single instance with a handful of tenants that is invisible; it is still an
    unbounded map keyed by a value that arrives from outside the process, and the
    fix is cheap. A bucket that has refilled to capacity carries no information --
    evicting it is indistinguishable from keeping it.
    """
    limiter = TokenBucketLimiter(capacity=2, refill_rate=1000.0, idle_eviction_seconds=0.05)

    for i in range(200):
        assert await limiter.acquire(f"tenant-{i}")

    # The sweep is amortised over acquisitions rather than run on a timer, so it
    # takes traffic to trigger -- which is the point: growth pays for its own sweep.
    await asyncio.sleep(0.1)
    for i in range(60):
        await limiter.acquire(f"sweeper-{i}")

    assert len(limiter.buckets) < 200, (
        f"{len(limiter.buckets)} buckets retained; idle tenants are never evicted, "
        f"so the map grows without bound for the lifetime of the process."
    )
    assert limiter.buckets.keys() == limiter.last_updated.keys(), (
        "buckets and last_updated disagree -- eviction must clear both or the "
        "second map becomes the leak the first one stopped being."
    )


async def test_eviction_never_hands_out_free_capacity() -> None:
    """A tenant at zero tokens must not be reset by being evicted.

    This is the way an eviction policy turns into a rate-limit bypass: evict an
    exhausted bucket, and the next request re-creates it at full capacity. Only
    buckets that have refilled to capacity may be dropped.
    """
    limiter = TokenBucketLimiter(capacity=2, refill_rate=0.0, idle_eviction_seconds=0.0)

    assert await limiter.acquire("greedy")
    assert await limiter.acquire("greedy")
    assert not await limiter.acquire("greedy"), "bucket should be exhausted"

    # Drive several eviction sweeps with unrelated traffic. `idle_eviction_seconds=0`
    # means every full bucket is immediately eligible, which is the most aggressive
    # setting the policy allows -- if the bypass exists, this finds it.
    for i in range(600):
        await limiter.acquire(f"other-{i}")

    assert not await limiter.acquire("greedy"), (
        "an exhausted tenant regained capacity by being evicted -- eviction is a rate-limit bypass."
    )


@pytest.mark.parametrize("field", ["rate_limit_capacity", "rate_limit_refill_per_second"])
def test_the_limiter_settings_are_documented_as_per_instance(field: str) -> None:
    """The description must not imply a quota it cannot enforce.

    In-memory and per-process: it resets on restart and would not hold across
    replicas. Under D5 the deployment is one instance, so this is adequate -- but
    calling it a quota would be a claim about a guarantee that does not exist.
    """
    description = Settings.model_fields[field].description or ""
    assert "per-instance" in description.lower() or "per instance" in description.lower(), (
        f"{field} does not say it is per-instance: {description!r}"
    )
