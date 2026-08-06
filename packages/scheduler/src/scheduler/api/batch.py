"""Asynchronous Batch Processing REST endpoints (/v1/batch)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from scheduler.api.ingress import verify_jwt

router = APIRouter(prefix="/v1", tags=["batch"])


def get_batch_jobs(request: Request) -> dict[str, dict[str, Any]]:
    """Return this app's batch store.

    Lives on `app.state`, not at module scope. It used to be a module-level dict,
    so every `create_app()` in one process shared it -- a correctness bug on its
    own, and the specific reason `specs/scheduler-persistence.md` deferred batch
    persistence out of ROADMAP 2.1.

    Created lazily so an app built before this existed still works.
    """
    jobs: dict[str, dict[str, Any]] | None = getattr(request.app.state, "batch_jobs", None)
    if jobs is None:
        jobs = {}
        request.app.state.batch_jobs = jobs
    return jobs


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
    """Response payload for batch status queries.

    Carries no owner field. The submitting tenant is recorded alongside the record
    in the store, deliberately outside this model, so it is never serialised back
    to a caller -- the same reason the registry holds per-node tokens outside the
    `Node` model.
    """

    batch_id: str
    status: str
    total_items: int
    completed_items: int
    results: list[BatchItemResult] = Field(default_factory=list)


def _require_tenant(jwt_claims: dict[str, Any]) -> str:
    """Pull the tenant this request acts as, matching `/v1/chat/completions`.

    `tenant_id` rather than `sub`, because that is the claim `verify_jwt` already
    enforces and the one the gateway already scopes on. Batch does not get to
    invent a second notion of identity.
    """
    tenant_id = jwt_claims.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid claims: Missing 'tenant_id' in token payload.",
        )
    return str(tenant_id)


@router.post(
    "/batch",
    response_model=BatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_batch_job(
    request: Request,
    payload: BatchRequest,
    jwt_claims: Annotated[dict[str, Any], Depends(verify_jwt)],
) -> BatchResponse:
    """Submit an asynchronous batch processing job.

    NOTE: this fabricates its result strings and dispatches nothing. ROADMAP 2.4
    made it require a credential; it did not make it do work. Do not read
    "authenticated" as "implemented".
    """
    tenant_id = _require_tenant(jwt_claims)
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

    response = BatchResponse(
        batch_id=batch_id,
        status="completed",
        total_items=len(payload.requests),
        completed_items=len(payload.requests),
        results=results,
    )
    get_batch_jobs(request)[batch_id] = {
        "tenant_id": tenant_id,
        "response": response.model_dump(),
    }

    return response


@router.get(
    "/batch/{batch_id}",
    response_model=BatchResponse,
)
async def get_batch_job_status(
    request: Request,
    batch_id: str,
    jwt_claims: Annotated[dict[str, Any], Depends(verify_jwt)],
) -> BatchResponse:
    """Retrieve status and results for a batch this tenant submitted.

    A batch belonging to someone else answers 404, identically to one that does not
    exist -- body included. 403 would confirm the id is real, turning this into an
    oracle for enumerating other tenants' batch ids.
    """
    tenant_id = _require_tenant(jwt_claims)
    record = get_batch_jobs(request).get(batch_id)

    if record is None or record["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch job {batch_id} not found",
        )
    return BatchResponse(**record["response"])
