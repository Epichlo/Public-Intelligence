"""Main entrypoint for the Public Intelligence Node."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from node.core.configuration import get_settings
from node.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan manager for the FastAPI application.

    Handles startup and shutdown events for the application.
    """
    yield


app = FastAPI(
    title="Public Intelligence Node",
    description="Compute worker for the Public Intelligence network.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Check health status of the Node.

    Returns:
        dict[str, str]: A dictionary indicating the health status.
    """
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "node.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
