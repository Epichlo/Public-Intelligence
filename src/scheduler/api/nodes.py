"""Node registration and discovery endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from scheduler.api.auth import verify_auth_token
from scheduler.models.node import Node
from scheduler.registry.node_registry import NodeRegistry

router = APIRouter(tags=["nodes"])


def get_registry(request: Request) -> NodeRegistry:
    """Retrieve the NodeRegistry from application state."""
    registry: NodeRegistry = request.app.state.registry
    return registry


RegistryDep = Annotated[NodeRegistry, Depends(get_registry)]


@router.post(
    "/nodes/register",
    response_model=Node,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_auth_token)],
)
async def register_node(
    node: Node,
    registry: RegistryDep,
    x_network_auth_token: Annotated[str | None, Header(alias="X-Network-Auth-Token")] = None,
) -> Node:
    """Register a compute node with the scheduler.

    The credential the node presents here is retained so the Scheduler can
    authenticate to that node's control API when dispatching work to it. The
    node's `/infer` fails closed, so without this the Scheduler cannot reach it.

    It is stored outside the `Node` model and so is never echoed back in this
    response or listed by `GET /nodes`.

    The credential is recorded before registration is attempted, so a node whose
    token has rotated refreshes it even when the record already exists and the
    call returns 409. Recording it only on success left the Scheduler holding a
    stale token and silently 401ing every dispatch to that node.
    """
    registry.set_node_token(node.node_id, x_network_auth_token)

    try:
        await registry.register(node)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Node already registered: {node.node_id}",
        ) from None

    return node


@router.get("/nodes", response_model=list[Node])
async def list_nodes(
    registry: RegistryDep,
) -> list[Node]:
    """List all registered compute nodes."""
    return await registry.list()


@router.get("/nodes/{node_id}", response_model=Node)
async def get_node(
    node_id: str,
    registry: RegistryDep,
) -> Node:
    """Get a specific node by ID."""
    node = await registry.get(node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node not found: {node_id}",
        )
    return node


@router.delete(
    "/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_auth_token)],
)
async def unregister_node(
    node_id: str,
    registry: RegistryDep,
) -> None:
    """Unregister a compute node during graceful shutdown."""
    try:
        await registry.unregister(node_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node not found: {node_id}",
        ) from None
