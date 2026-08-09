"""Ingress gateway API endpoint for client task submissions."""

from typing import Annotated, Any

import jwt
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/api/v1/tasks")

# There was a hardcoded RSA public key here, used whenever nothing else was
# configured. It is gone (ROADMAP C4), and the reason is worth stating because the
# risk was previously judged low on the wrong grounds.
#
# The argument for keeping it was that the matching PRIVATE key is not in this
# repository, so nobody could mint a token it accepts. That is true and beside the
# point: the key came from somewhere. It was a "standard dummy" PEM of the kind that
# circulates in tutorials and sample projects, and whoever generated it may still
# hold the private half. Trusting a key of unknown provenance is not "probably
# fine" -- it is an authentication decision nobody made.
#
# An unconfigured gateway now refuses everyone. See test_jwt_key_rotation.py.

# Key identifiers carried in the `kid` JWT header. Two keys are accepted at once so
# that rotation is a sequence rather than an outage: add the new key as secondary,
# start signing with it, and retire the old one once the last token minted under it
# has expired. Before this, replacing the key invalidated every live token at once.
KID_PRIMARY = "primary"
KID_SECONDARY = "secondary"


class TaskSubmission(BaseModel):
    """Pydantic model representing the task structure for client submission."""

    task_id: str = Field(..., description="Unique identifier for the task.")
    action: str = Field(..., description="State machine action/instruction payload.")
    data: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary task execution arguments."
    )


def _verification_keys(request: Request) -> dict[str, str]:
    """Active public keys by `kid`, most likely first.

    Read from `app.state` rather than from settings, matching how `store` and
    `rate_limiter` are injected: settings are resolved once where the deployed app is
    built, so an ambient `.env` cannot change what the test suite verifies against.
    """
    keys: dict[str, str] = {}
    primary = getattr(request.app.state, "jwt_public_key", None)
    secondary = getattr(request.app.state, "jwt_public_key_secondary", None)
    if primary:
        keys[KID_PRIMARY] = primary
    if secondary:
        keys[KID_SECONDARY] = secondary
    return keys


def _decode_with_any(token: str, candidates: dict[str, str]) -> dict[str, Any] | None:
    """Verify against the `kid`-named key, then against the rest. None means invalid.

    `kid` is a HINT for key selection and never an assertion of validity: an
    unrecognised one falls through to trying every active key, and a token that
    verifies under none of them is refused. It is not treated as "no key matched, so
    skip the check" -- that is the standard way a kid-aware verifier becomes a
    bypass, and `test_an_unknown_kid_does_not_bypass_verification` pins it.

    `algorithms=["RS256"]` is passed on every call, so an `alg: none` token has no
    path through here regardless of which key is tried.
    """
    try:
        named = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        named = None

    ordered = list(candidates.items())
    if named in candidates:
        ordered.sort(key=lambda item: item[0] != named)

    last_error: Exception | None = None
    for kid, key in ordered:
        try:
            payload: dict[str, Any] = jwt.decode(token, key, algorithms=["RS256"])
        except jwt.PyJWTError as e:
            last_error = e
            continue
        else:
            logger.debug("ingress_jwt_verified", kid=kid)
            return payload

    logger.warning("ingress_jwt_verification_failed", error=str(last_error))
    return None


def verify_jwt(request: Request, authorization: str | None = Header(None)) -> dict[str, Any]:
    """Dependency injection validator to check asymmetric JWT signature.

    Args:
        request: FastAPI Request instance to pull app state configuration.
        authorization: HTTP Authorization header containing Bearer token.

    Returns:
        The decoded JWT payload claims.

    Raises:
        HTTPException (401) on validation error.

    The header is optional *to FastAPI* and required by this function. With
    `Header(...)` FastAPI rejected a request carrying no `Authorization` before this
    ran, answering **422 Unprocessable Entity** -- a validation error -- for what is
    plainly an authentication failure. Every route depending on this was affected,
    including `/v1/chat/completions`. See specs/close-the-open-http-surface.md.
    """
    if authorization is None:
        raise HTTPException(
            status_code=401, detail="Missing Authorization header. Must be Bearer <JWT>."
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Invalid Authorization header format. Must be Bearer <JWT>."
        )

    token = authorization.split(" ")[1]

    candidates = _verification_keys(request)
    if not candidates:
        # Fail closed. Previously this fell back to a key literal in this file, so an
        # unconfigured gateway trusted whoever held that key's private half.
        logger.error("ingress_jwt_no_key_configured")
        raise HTTPException(
            status_code=401,
            detail="Gateway has no JWT verification key configured; refusing all requests.",
        )

    payload = _decode_with_any(token, candidates)
    if payload is None:
        raise HTTPException(status_code=401, detail="JWT signature verification failed.")

    if "tenant_id" not in payload:
        raise HTTPException(
            status_code=401, detail="Invalid claims: Missing 'tenant_id' in token payload."
        )

    return payload


@router.post("/submit")
async def submit_task(
    request: Request,
    task: TaskSubmission,
    payload: Annotated[dict[str, Any], Depends(verify_jwt)],
) -> dict[str, str]:
    """Dedicated ingress endpoint to submit tasks to the consensus log.

    Secured by JWT authentication, rate-limited, scheduled using two-stage Strategy,
    and committed to consensus log.

    Args:
        request: FastAPI Request context.
        task: Deserialized client task details.
        payload: Decoded JWT claims dict (via verify_jwt dependency).

    Returns:
        Status object signaling scheduled task tracking info.
    """
    tenant_id = payload["tenant_id"]

    # 1. Rate-Limiter Guard
    rate_limiter = getattr(request.app.state, "rate_limiter", None)
    if rate_limiter is not None:
        allowed = await rate_limiter.acquire(tenant_id)
        if not allowed:
            logger.warning("ingress_rate_limit_tripped", tenant_id=tenant_id)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Multi-tenant quota exhausted.",
            )

    # 2. Scheduling Engine Retrieval & Execution
    scheduling_engine = getattr(request.app.state, "scheduling_engine", None)
    if scheduling_engine is None:
        logger.error("ingress_scheduling_engine_uninitialized")
        raise HTTPException(status_code=500, detail="Scheduling engine is uninitialized.")

    task_data = {
        "task_id": task.task_id,
        "requirements": {
            "model_name": task.data.get("model_name") or task.data.get("model"),
            "min_vram_gb": task.data.get("min_vram_gb") or task.data.get("vram"),
            "backend_type": task.data.get("backend_type"),
        },
    }

    try:
        tx_hash, node_id = await scheduling_engine.schedule_task(task_data)
    except ValueError as e:
        logger.warning("ingress_scheduling_failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e

    # The consensus log-commitment block that sat here is gone (ROADMAP C2).
    # It proposed through an engine whose only inbound path was an
    # unauthenticated wildcard Zenoh subscriber; see zenoh_router.

    return {
        "status": "scheduled",
        "task_id": task.task_id,
        "node_id": node_id,
        "tx_hash": tx_hash,
    }
