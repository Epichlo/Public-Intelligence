"""Asynchronous Batch Processing REST endpoints (/v1/batch)."""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from scheduler.api.ingress import verify_jwt

logger = structlog.stdlib.get_logger()

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
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
async def submit_batch_job(
    payload: BatchRequest,
    jwt_claims: Annotated[dict[str, Any], Depends(verify_jwt)],
) -> None:
    """Refuse batch submission. Nothing here dispatches, so nothing may claim to.

    This returned **HTTP 202** with a `BatchResponse` whose every item carried
    `status_code: 200` and the text "[Batch Response for '<your prompt>...'] Completed
    asynchronously via WAN pipeline", with `completed_items == total_items`. No node
    was contacted. The "completion" was a list comprehension over the request.

    That is ROADMAP N1's defect in a second endpoint: a well-formed request answered
    with invented text in the shape a client parses as model output. N1's resolution
    applies unchanged --

      * **501, not 400.** The server understands the request perfectly; it has no
        implementation. A 400 would blame the caller for asking correctly.
      * **501, not 202-with-a-placeholder.** Telling a caller the work is queued when
        nothing is queued is the specific harm.
      * **Deleted, not guarded.** N1's lesson was that dead code behind a disabled
        flag is exactly how the original survived for weeks.

    This also supersedes ROADMAP C9 ("batch jobs are still not persisted"):
    persisting a fabrication makes it durable, not true. A stub whose output survives
    a restart is worse than one whose output does not.

    ROADMAP 2.4's work is preserved. The JWT dependency stays -- a 501 that answers
    anyone is a smaller bug than a 200, not no bug -- and so does `_require_tenant`,
    because when this is implemented the tenant scoping is the part that must not be
    rebuilt from scratch.

    See tests/test_batch_is_refused_not_faked.py.
    """
    _require_tenant(jwt_claims)
    logger.info(
        "batch_submission_refused",
        item_count=len(payload.requests),
        reason="not_implemented",
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Batch processing is not implemented. This endpoint previously returned "
            "fabricated results; it now refuses rather than inventing an answer. "
            "Use POST /v1/chat/completions."
        ),
    )


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
    # Nothing can be submitted since the POST above began refusing, so this is
    # always None today. The lookup and the tenant comparison are kept rather than
    # short-circuited to a bare 404: they are ROADMAP 2.4's fix, they are correct,
    # and re-deriving "must a batch be scoped to its submitter" later is how that
    # kind of check gets rebuilt wrong.
    record = get_batch_jobs(request).get(batch_id)

    if record is None or record["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch job {batch_id} not found",
        )
    return BatchResponse(**record["response"])
