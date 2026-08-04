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


app = FastAPI(
    title="Public Intelligence Node",
    description="Compute worker for the Public Intelligence network.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the routes
app.include_router(router)
app.include_router(control_router)


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
