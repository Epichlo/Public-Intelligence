"""Scheduler selection API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from scheduler.api.auth import verify_auth_token
from scheduler.api.nodes import get_mesh_client, get_registry
from scheduler.core.config import Settings, get_settings
from scheduler.core.mesh_inference_client import MeshInferenceClient
from scheduler.core.node_dispatch import NodeDispatchError, infer_once
from scheduler.models.inference import InferenceRequest, InferenceResponse
from scheduler.registry.node_registry import NodeRegistry
from scheduler.scheduler.algorithm import Scheduler

router = APIRouter(tags=["schedule"])


class InferenceProxyResponse(BaseModel):
    """Inference result returned with the selected node identity."""

    node_id: str
    result: InferenceResponse


class ScheduleRequest(BaseModel):
    """Inference request asking for a specific model."""

    model_name: str = Field(description="The name of the requested AI model")


class ScheduleResponse(BaseModel):
    """Response returning the selected compute node."""

    node_id: str = Field(description="Unique identifier of the selected node")
    hostname: str = Field(description="Hostname of the selected node")
    ip_address: str = Field(description="IP address of the selected node")
    region: str = Field(description="Geographic region of the selected node")


def get_scheduler(
    registry: Annotated[NodeRegistry, Depends(get_registry)],
) -> Scheduler:
    """Dependency provider for the Scheduler instance."""
    return Scheduler(registry)


SchedulerDep = Annotated[Scheduler, Depends(get_scheduler)]


@router.post(
    "/schedule",
    response_model=ScheduleResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_auth_token)],
)
async def schedule_request(
    request: ScheduleRequest,
    scheduler: SchedulerDep,
) -> ScheduleResponse:
    """Select the best compute node to run the requested model."""
    try:
        node = await scheduler.select_node(request.model_name)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from None

    return ScheduleResponse(
        node_id=node.node_id,
        hostname=node.hostname,
        ip_address=node.ip_address,
        region=node.region,
    )


@router.post(
    "/infer",
    response_model=InferenceProxyResponse,
    dependencies=[Depends(verify_auth_token)],
)
async def proxy_inference(
    request: InferenceRequest,
    registry: Annotated[NodeRegistry, Depends(get_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
    mesh_client: Annotated[MeshInferenceClient | None, Depends(get_mesh_client)],
) -> InferenceProxyResponse:
    """Select a node and forward one inference request to it.

    Routes over the Zenoh mesh when the node has been seen there, which is the only way to
    reach a node behind NAT, and dials its HTTP API otherwise. Transport selection and
    credentials live in `scheduler/core/node_dispatch.py`, shared with the OpenAI gateway --
    keeping the two in step is why it is not inlined here.
    """
    scheduler = Scheduler(registry)
    try:
        node = await scheduler.select_node(request.model)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        result = await infer_once(
            registry=registry,
            settings=settings,
            mesh_client=mesh_client,
            node_id=node.node_id,
            ip_address=node.ip_address,
            model=request.model,
            prompt=request.prompt,
        )
    except NodeDispatchError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    return InferenceProxyResponse(
        node_id=node.node_id,
        result=InferenceResponse.model_validate(result),
    )
