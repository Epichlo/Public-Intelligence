"""Main entrypoint for the Public Intelligence Node."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from node.api import control_router, router
from node.core.configuration import get_settings
from node.core.logging import setup_logging
from node.runtime import Runtime

settings = get_settings()
setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan manager for the FastAPI application.

    Handles startup and shutdown events for the application.
    """
    runtime = Runtime(settings)
    app.state.runtime = runtime
    app.state.ollama_client = runtime.ollama_client
    app.state.scheduler_client = runtime.scheduler_client

    await runtime.start()
    yield
    await runtime.stop()


def create_app(cors_origins: list[str] | None = None) -> FastAPI:
    """Build the Node's FastAPI application.

    Args:
        cors_origins: Browser origins allowed to read this Node's responses
            cross-origin. `None` or empty installs no CORS middleware at all.
            Injected rather than read from settings here, so a value in a host's
            `.env` cannot change what the test suite exercises.

    Extracted from module scope by ROADMAP 2.3. What was here before was
    `allow_origins=["*"]` with `allow_credentials=True`, which does NOT send a
    wildcard -- Starlette reflects the caller's own Origin back and sets
    allow-credentials. A Node runs on a host's own machine, usually on localhost,
    so that made it readable from any page that host visited in a browser.
    See specs/close-the-open-http-surface.md.
    """
    application = FastAPI(
        title="Public Intelligence Node",
        description="Compute worker for the Public Intelligence network.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Not installed at all when there are no origins -- see the Scheduler's
    # create_app for why that is different from installing it with an empty list.
    if cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Network-Auth-Token"],
        )

    application.include_router(router)
    application.include_router(control_router)
    return application


app = create_app(cors_origins=settings.cors_allow_origins)


def cli_main() -> None:
    """CLI entrypoint for running the Public Intelligence Node."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Public Intelligence Node runner")
    parser.add_argument("--host", type=str, default=settings.host, help="Host interface to bind")
    parser.add_argument("--port", type=int, default=settings.port, help="Port to listen on")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    uvicorn.run(
        "node.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    cli_main()
