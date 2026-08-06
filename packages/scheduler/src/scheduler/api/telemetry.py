"""Node hardware telemetry REST endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from scheduler.api.auth import verify_auth_token
from scheduler.registry.node_registry import NodeRegistry

# Every route here returns decrypted per-node metrics. ROADMAP 2.7 authenticated
# the mesh so only a node can report its own; serving the same data to anyone over
# HTTP would have made that half a fix. Guarded at the router level so a route
# added later inherits it. See specs/authenticate-the-read-surface.md.
router = APIRouter(tags=["telemetry"], dependencies=[Depends(verify_auth_token)])


def get_registry(request: Request) -> NodeRegistry:
    """Retrieve NodeRegistry from application state."""
    registry: NodeRegistry = request.app.state.registry
    return registry


RegistryDep = Annotated[NodeRegistry, Depends(get_registry)]


@router.get("/nodes/telemetry", response_model=dict[str, Any])
async def list_all_telemetry(
    registry: RegistryDep,
) -> dict[str, Any]:
    """Expose decrypted hardware health metrics for all active compute nodes."""
    telemetry = getattr(registry, "_telemetry", {})
    return cast("dict[str, Any]", telemetry)


@router.get("/nodes/{node_id}/telemetry", response_model=dict[str, Any])
async def get_node_telemetry(
    node_id: str,
    registry: RegistryDep,
) -> dict[str, Any]:
    """Expose decrypted hardware health metrics for a specific compute node."""
    telemetry = getattr(registry, "_telemetry", {})
    if node_id not in telemetry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Telemetry not found for node: {node_id}",
        )
    return cast("dict[str, Any]", telemetry[node_id])
