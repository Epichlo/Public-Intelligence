"""Requester credential issuance (`POST /v1/credentials`, ROADMAP 3.1).

The gateway has verified RS256 JWTs since long before this, and there was **no way
for anyone to obtain one**. `scripts/mint_token.py` is an operator tool that reads a
private key off the operator's own disk, so in practice there were no requesters --
only the person running the Scheduler. That is the gap 3.1 names, and it is the one
step of the v1 walkthrough ("a developer, with a credential they obtained themselves")
that nothing implemented.

## Who may issue

The operator, and nobody else. This route is guarded by `verify_auth_token` -- the
same fleet credential that guards node registration and the read surface -- not by a
JWT, because a JWT-guarded issuance endpoint would let any holder mint more tokens
for any tenant, which is privilege escalation dressed as a feature.

**This is deliberately not self-service.** Under
`docs/decisions/D1-execution-integrity.md` and `D4` this is an invite-only network,
and issuing a credential is exactly the human decision that admission control is
supposed to be. An open signup endpoint would undo D4 from the requester side, having
just closed it on the node side.

## What is not here

**Revocation.** There is none, and the honest reason is that JWTs are stateless: the
gateway verifies a signature and never asks this service anything, so a token cannot
be recalled without adding a lookup to every request. The mitigation is short
lifetimes -- `max_ttl_hours` is enforced here rather than trusted from the caller --
and key rotation (ROADMAP C4) as the blunt instrument for "invalidate everything".
`docs/ACCEPTABLE_USE.md` says this plainly rather than implying a revoke button
exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import structlog
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from scheduler.api.auth import verify_auth_token
from scheduler.api.ingress import KID_PRIMARY, KID_SECONDARY
from scheduler.core.config import get_settings

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/v1", tags=["credentials"], dependencies=[Depends(verify_auth_token)])


class CredentialRequest(BaseModel):
    """What an operator asks for when issuing a requester credential."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Tenant this credential acts as. Rate limiting, metering and batch "
            "ownership all key on it, so two developers who should not see each "
            "other's usage need different values."
        ),
    )
    subject: str = Field(
        default="requester",
        min_length=1,
        max_length=128,
        description="`sub` claim -- who inside the tenant this was issued to.",
    )
    ttl_hours: int = Field(
        default=720,
        ge=1,
        description=(
            "Lifetime in hours. Default 30 days. Capped by the Scheduler's "
            "`credential_max_ttl_hours`, because there is no revocation and an "
            "unbounded lifetime would make that permanent."
        ),
    )
    kid: str = Field(
        default=KID_PRIMARY,
        description=f"Signing key to use: {KID_PRIMARY!r} or {KID_SECONDARY!r}.",
    )


class CredentialResponse(BaseModel):
    """The issued credential. Shown once -- nothing stores it."""

    token: str = Field(description="RS256 JWT for the Authorization: Bearer header")
    tenant_id: str
    subject: str
    expires_at: str = Field(description="ISO-8601 UTC expiry")
    kid: str


def _signing_key(kid: str) -> Any:
    """Load the configured private key for `kid`, or explain why it cannot.

    The private key lives on the operator's disk and is referenced by path rather
    than by value: putting a PEM in an environment variable is how private keys end
    up in process listings, crash dumps and log aggregators.
    """
    settings = get_settings()
    path = (
        settings.jwt_private_key_path
        if kid == KID_PRIMARY
        else settings.jwt_private_key_path_secondary
    )
    if not path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"No signing key configured for kid '{kid}'. Set "
                f"SCHEDULER_JWT_PRIVATE_KEY_PATH (and _SECONDARY for rotation). "
                f"Generate one with: scripts/mint_token.py --generate-keypair"
            ),
        )

    try:
        with open(path, "rb") as handle:
            return serialization.load_pem_private_key(handle.read(), password=None)
    except (OSError, ValueError) as e:
        # The path and the reason, never the key material.
        logger.error("credential_signing_key_unreadable", kid=kid, path=path, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Signing key for kid '{kid}' could not be loaded.",
        ) from e


@router.post(
    "/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a requester credential (operator only)",
)
async def issue_credential(payload: CredentialRequest) -> CredentialResponse:
    """Mint an RS256 JWT a developer can use against `/v1/chat/completions`."""
    if payload.kid not in (KID_PRIMARY, KID_SECONDARY):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown kid '{payload.kid}'.",
        )

    settings = get_settings()
    # Capped rather than rejected: an operator asking for a year gets the maximum
    # and is told, which is friendlier than a 422 and cannot be argued into a
    # longer-lived token by a client that sends a bigger number.
    ttl_hours = min(payload.ttl_hours, settings.credential_max_ttl_hours)

    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=ttl_hours)

    token = jwt.encode(
        {
            "sub": payload.subject,
            # `tenant_id`, not `sub`, is what the gateway scopes on -- verify_jwt
            # refuses a token without it. Issuing one that the gateway would reject
            # is the failure this endpoint most obviously could have.
            "tenant_id": payload.tenant_id,
            "iat": now,
            "exp": expires_at,
        },
        _signing_key(payload.kid),
        algorithm="RS256",
        headers={"kid": payload.kid},
    )

    # The tenant and expiry, never the token. A credential in the logs is a
    # credential in whatever aggregates the logs.
    logger.info(
        "credential_issued",
        tenant_id=payload.tenant_id,
        subject=payload.subject,
        expires_at=expires_at.isoformat(),
        kid=payload.kid,
        ttl_hours=ttl_hours,
        ttl_was_capped=ttl_hours < payload.ttl_hours,
    )

    return CredentialResponse(
        token=token,
        tenant_id=payload.tenant_id,
        subject=payload.subject,
        expires_at=expires_at.isoformat(),
        kid=payload.kid,
    )
