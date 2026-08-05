"""Node registration and discovery endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from scheduler.api.auth import verify_auth_token
from scheduler.core.config import get_settings
from scheduler.core.mesh_inference_client import MeshInferenceClient
from scheduler.models.node import ModelCatalogueUpdate, Node, NodeView
from scheduler.registry.node_registry import NodeRegistry

router = APIRouter(tags=["nodes"])


def get_registry(request: Request) -> NodeRegistry:
    """Retrieve the NodeRegistry from application state."""
    registry: NodeRegistry = request.app.state.registry
    return registry


def get_mesh_client(request: Request) -> MeshInferenceClient | None:
    """Build a mesh inference client over the Scheduler's Zenoh session.

    Returns None when the Scheduler has no session -- `ZenohRouter.start` swallows a
    failed `zenoh.open`, so this is a normal state, and dispatch falls back to HTTP.

    `app.state.mesh_client`, if set, wins. That is the seam tests use to drive dispatch
    without standing up a router.
    """
    override = getattr(request.app.state, "mesh_client", None)
    if override is not None:
        return override  # type: ignore[no-any-return]

    zenoh_router = getattr(request.app.state, "zenoh_router", None)
    session = getattr(zenoh_router, "session", None) if zenoh_router is not None else None
    if session is None:
        return None

    settings = get_settings()
    return MeshInferenceClient(
        session,
        timeout=settings.mesh_inference_timeout_seconds,
        first_reply_timeout=settings.mesh_inference_first_reply_timeout_seconds,
    )


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


@router.get("/nodes", response_model=list[NodeView])
async def list_nodes(
    registry: RegistryDep,
) -> list[NodeView]:
    """List all registered compute nodes and how each is reachable."""
    return [
        NodeView.from_node(node, mesh_reachable=registry.is_mesh_reachable(node.node_id))
        for node in await registry.list()
    ]


@router.get("/nodes/{node_id}", response_model=NodeView)
async def get_node(
    node_id: str,
    registry: RegistryDep,
) -> NodeView:
    """Get a specific node by ID, with how it is reachable."""
    node = await registry.get(node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node not found: {node_id}",
        )
    return NodeView.from_node(node, mesh_reachable=registry.is_mesh_reachable(node_id))


@router.put(
    "/nodes/{node_id}/models",
    response_model=NodeView,
    dependencies=[Depends(verify_auth_token)],
)
async def update_node_models(
    node_id: str,
    update: ModelCatalogueUpdate,
    registry: RegistryDep,
) -> NodeView:
    """Replace what a node advertises it can serve.

    Registration captures the catalogue once, at node startup. Without this a host
    that runs `ollama pull` stays unroutable for the new model, and a host that
    runs `ollama rm` keeps being sent requests for a model it no longer has --
    neither of which a node restart fixes, because re-registration answers 409 and
    heartbeats carry no model list. See specs/truthful-model-catalogue.md.

    Separate from registration rather than an upsert on it so that `POST
    /nodes/register` keeps meaning "create", and so the only thing a node can
    restate at runtime is the one thing that actually varies at runtime.
    """
    try:
        await registry.set_available_models(node_id, update.available_models)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node not found: {node_id}",
        ) from None

    node = await registry.get(node_id)
    if node is None:  # pragma: no cover - unregistered between the write and the read
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node not found: {node_id}",
        )
    return NodeView.from_node(node, mesh_reachable=registry.is_mesh_reachable(node_id))


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
