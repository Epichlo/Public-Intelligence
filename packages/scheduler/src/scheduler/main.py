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


def create_app(
    store: SchedulerStore | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        store: Durable state backend. `None` -- the default -- means in-memory
            only, and is what every existing test gets. The deployed app is built
            at the bottom of this module with `build_store()`; see its docstring
            for why the settings lookup lives there and not here.
        cors_origins: Browser origins allowed to read this service's responses
            cross-origin. `None` or empty installs no CORS middleware at all.
            Injected for the same reason `store` is: middleware is constructed
            here, at app-construction time, so a `dependency_overrides` entry would
            arrive too late to affect it and reading the environment here would let
            an ambient `.env` change what the test suite exercises.
    """
    app = FastAPI(
        title="Public Intelligence Scheduler",
        description="Control plane for distributed AI infrastructure",
        version=__version__,
        lifespan=lifespan,
    )

    # No origins means the middleware is NOT installed, rather than installed with
    # an empty list. No CORS headers at all is the honest expression of "no
    # cross-origin access"; an empty allow_origins still answers preflights and
    # invites a reader to think something is configured.
    #
    # What was here before was `allow_origins=["*"]` with `allow_credentials=True`,
    # which does NOT send a wildcard -- Starlette reflects the caller's own Origin
    # and sets allow-credentials, so every origin on the internet could read these
    # responses. See specs/close-the-open-http-surface.md.
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            # Named rather than `*`: with an exact origin list a wildcard is far
            # less dangerous, but it leaves the next reader unable to tell which
            # was reasoned about. These are the three headers the API accepts.
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Network-Auth-Token"],
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


app = create_app(store=build_store(), cors_origins=get_settings().cors_allow_origins)
