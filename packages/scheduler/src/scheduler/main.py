"""FastAPI application factory and lifespan management."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
import zenoh
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scheduler import __version__
from scheduler.api.batch import router as batch_router
from scheduler.api.health import router as health_router
from scheduler.api.heartbeat import router as heartbeat_router
from scheduler.api.ingress import router as ingress_router
from scheduler.api.nodes import router as nodes_router
from scheduler.api.openai import router as openai_router
from scheduler.api.schedule import router as schedule_router
from scheduler.api.telemetry import router as telemetry_router
from scheduler.core.config import get_settings
from scheduler.core.credit_ledger import CreditLedger
from scheduler.core.logging import setup_logging
from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.core.zenoh_router import ZenohRouter
from scheduler.persistence import SchedulerStore, SQLiteStore
from scheduler.registry.node_registry import NodeRegistry

logger = structlog.stdlib.get_logger()


def build_store() -> SchedulerStore | None:
    """Build the durable store the deployed Scheduler runs with, if configured.

    This is the **only** place settings decide whether persistence is on.
    `create_app()` deliberately does not consult them, so a `SCHEDULER_DATABASE_PATH`
    sitting in a developer's `.env` cannot silently point the whole test suite at
    one shared database. Tests that want persistence pass a store explicitly.
    """
    settings = get_settings()
    if not settings.database_path:
        return None
    return SQLiteStore(settings.database_path)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    settings = get_settings()
    setup_logging(settings.log_level)

    # Before anything can be served, and before the mesh is joined: a node that
    # arrives on the mesh must find a registry that already knows the fleet, or the
    # first heartbeat would 404 and send a node that never went away round the
    # re-registration loop.
    store = app.state.store
    await app.state.registry.load()
    await app.state.ledger.load()

    logger.info(
        "scheduler_started",
        version=__version__,
        environment=settings.environment.value,
        persistence_enabled=store is not None,
        # The resolved path, in the logs, because prose about where state lives goes
        # stale and a log line from this boot cannot.
        persistence_path=str(getattr(store, "path", "")) or None,
    )

    # Initialize and start ZenohRouter
    zenoh_config = zenoh.Config()
    if settings.zenoh_listen_endpoints:
        zenoh_config.insert_json5("listen/endpoints", json.dumps(settings.zenoh_listen_endpoints))
        zenoh_config.insert_json5("mode", '"router"')
    if settings.zenoh_peer_endpoints:
        zenoh_config.insert_json5("connect/endpoints", json.dumps(settings.zenoh_peer_endpoints))
    if not settings.zenoh_multicast_scouting:
        zenoh_config.insert_json5("scouting/multicast/enabled", "false")

    zenoh_router = ZenohRouter(app.state.registry, config=zenoh_config)
    zenoh_router.start()
    app.state.zenoh_router = zenoh_router

    yield

    # Stop ZenohRouter on shutdown
    if hasattr(app.state, "zenoh_router"):
        app.state.zenoh_router.stop()

    if store is not None:
        await store.close()

    logger.info("scheduler_stopped")


def create_app(store: SchedulerStore | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        store: Durable state backend. `None` -- the default -- means in-memory
            only, and is what every existing test gets. The deployed app is built
            at the bottom of this module with `build_store()`; see its docstring
            for why the settings lookup lives there and not here.
    """
    app = FastAPI(
        title="Public Intelligence Scheduler",
        description="Control plane for distributed AI infrastructure",
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.store = store
    app.state.registry = NodeRegistry(store=store)
    # Instantiated so its balances are durable and are loaded at startup. Nothing
    # credits it yet -- accrual on real usage is ROADMAP 3.2/3.3. A durable ledger
    # of zeroes is still the thing 3.2 needs to already exist before it can write.
    app.state.ledger = CreditLedger(store=store)
    app.state.rate_limiter = TokenBucketLimiter()

    from scheduler.core.engine import SchedulingEngine
    from scheduler.core.matchmaker import CapabilityMatchmaker

    strategy = CapabilityMatchmaker(app.state.registry)
    app.state.scheduling_engine = SchedulingEngine(app.state.registry, strategy)

    app.include_router(health_router)
    app.include_router(telemetry_router)
    app.include_router(nodes_router)
    app.include_router(heartbeat_router)
    app.include_router(schedule_router)
    app.include_router(ingress_router)
    app.include_router(openai_router)
    app.include_router(batch_router)

    return app


app = create_app(store=build_store())
