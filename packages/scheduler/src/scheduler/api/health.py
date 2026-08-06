"""Health and readiness probe endpoints."""

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from scheduler.registry.node_registry import NodeRegistry

from fastapi import APIRouter, Depends, Request

from scheduler import __version__
from scheduler.api.auth import verify_auth_token
from scheduler.core.config import Settings, get_settings
from scheduler.models.health import HealthResponse, ReadinessResponse
from scheduler.models.node import NodeStatus
from scheduler.models.status import NetworkStatus, NodeStatusSnapshot, SchedulerStatusResponse

router = APIRouter(tags=["health"])

_start_time: float = time.monotonic()


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Liveness probe. Returns 200 if the process is running."""
    return HealthResponse(
        status="healthy",
        version=__version__,
        environment=settings.environment.value,
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadinessResponse:
    """Readiness probe. Returns 200 when the service can accept traffic."""
    return ReadinessResponse(
        status="ready",
        version=__version__,
        environment=settings.environment.value,
        uptime_seconds=time.monotonic() - _start_time,
        timestamp=datetime.now(tz=UTC),
    )


@router.get(
    "/status",
    response_model=SchedulerStatusResponse,
    # Per-node snapshots: hostname, region, queue depth, CPU, GPU, VRAM. `/health`
    # and `/health/ready` above stay public on purpose -- they are probes, and a
    # health check that needs a secret reports unhealthy when the secret is wrong.
    dependencies=[Depends(verify_auth_token)],
)
async def operational_status(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SchedulerStatusResponse:
    """Return Scheduler transport state and the latest state of registered nodes."""
    registry: NodeRegistry = request.app.state.registry
    snapshots = await registry.snapshot()
    router = getattr(request.app.state, "zenoh_router", None)
    network_connected = router is not None and router.session is not None
    mode = "router" if settings.zenoh_listen_endpoints else "peer"

    nodes = [
        NodeStatusSnapshot(
            node_id=node.node_id,
            hostname=node.hostname,
            region=node.region,
            status=heartbeat.status
            if heartbeat is not None and isinstance(heartbeat.status, NodeStatus)
            else NodeStatus.UNKNOWN,
            heartbeat_at=heartbeat.timestamp if heartbeat is not None else None,
            queue_length=heartbeat.queue_length if heartbeat is not None else None,
            cpu_utilization=heartbeat.cpu_utilization if heartbeat is not None else None,
            gpu_utilization=heartbeat.gpu_utilization if heartbeat is not None else None,
            vram_available_gb=heartbeat.vram_available_gb if heartbeat is not None else None,
        )
        for node, heartbeat in snapshots
    ]

    return SchedulerStatusResponse(
        status="healthy",
        version=__version__,
        environment=settings.environment.value,
        uptime_seconds=time.monotonic() - _start_time,
        timestamp=datetime.now(tz=UTC),
        network=NetworkStatus(connected=network_connected, mode=mode),
        nodes=nodes,
    )
