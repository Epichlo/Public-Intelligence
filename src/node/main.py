"""Main entrypoint for the Public Intelligence Node."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from node.api import router
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

# Mount the routes
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "node.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
