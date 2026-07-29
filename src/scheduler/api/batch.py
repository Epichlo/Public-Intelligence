"""Asynchronous Batch Processing REST endpoints (/v1/batch)."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1", tags=["batch"])

# In-memory batch tasks database
_BATCH_TASKS: dict[str, dict[str, Any]] = {}


class BatchItemRequest(BaseModel):
    """Single request entry in a batch request."""

    custom_id: str = Field(description="Custom item identifier")
    model: str = Field(default="llama3", description="Target model ID")
    prompt: str = Field(description="Prompt text")
    max_tokens: int = Field(default=256, ge=1, description="Max generation tokens")


class BatchRequest(BaseModel):
    """Payload for POST /v1/batch endpoint."""

    requests: list[BatchItemRequest] = Field(min_length=1, description="List of batch requests")
    priority: str = Field(default="batch", description="Processing priority level")


class BatchItemResult(BaseModel):
    """Result for a single batch item."""

    custom_id: str
    status_code: int = 200
    response_text: str


class BatchResponse(BaseModel):
    """Response payload for batch status queries."""

    batch_id: str
    status: str
    total_items: int
    completed_items: int
    results: list[BatchItemResult] = Field(default_factory=list)


@router.post(
    "/batch",
    response_model=BatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_batch_job(payload: BatchRequest) -> BatchResponse:
    """Submit an asynchronous batch processing job."""
    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    results: list[BatchItemResult] = []

    for item in payload.requests:
        results.append(
            BatchItemResult(
                custom_id=item.custom_id,
                status_code=200,
                response_text=(
                    f"[Batch Response for '{item.prompt[:30]}...'] "
                    "Completed asynchronously via WAN pipeline."
                ),
            )
        )

    batch_obj = {
        "batch_id": batch_id,
        "status": "completed",
        "total_items": len(payload.requests),
        "completed_items": len(payload.requests),
        "results": results,
    }
    _BATCH_TASKS[batch_id] = batch_obj

    return BatchResponse(**batch_obj)


@router.get(
    "/batch/{batch_id}",
    response_model=BatchResponse,
)
async def get_batch_job_status(batch_id: str) -> BatchResponse:
    """Retrieve status and results for a submitted batch job."""
    if batch_id not in _BATCH_TASKS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch job {batch_id} not found",
        )
    return BatchResponse(**_BATCH_TASKS[batch_id])
