"""Authentication and authorization dependencies for the API."""

import hmac
import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from scheduler.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def warn_if_auth_disabled(settings: Settings) -> None:
    """Say loudly, at startup, that the fleet token is unset -- and refusing everyone.

    `verify_auth_token` used to enforce NOTHING in that state: an unset token was
    read as "auth is off" while the server bound 0.0.0.0 by default, so a fresh
    deployment served every guarded route to the internet until an operator
    happened to configure one. It now fails closed, mirroring the JWT gateway's
    unconfigured-key refusal (`api/ingress.py`), which makes this warning part of
    the feature rather than a nicety -- a check that refuses everything is only
    acceptable if being in that state is impossible to miss, exactly like
    `InviteRegistry.warn_if_open`.
    """
    if settings.network_auth_token is None:
        logger.warning(
            "network_auth_disabled: SCHEDULER_NETWORK_AUTH_TOKEN is not set, so every "
            "route guarded by the fleet token -- node registration, heartbeats, "
            "scheduling, telemetry, the model catalogue -- answers 401 until a token "
            "is configured. Set it on this Scheduler AND on every node that talks to it."
        )


async def verify_auth_token(
    x_network_auth_token: Annotated[str | None, Header(alias="X-Network-Auth-Token")] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> None:
    """Validate that the incoming request includes the configured security token.

    Fails CLOSED when no token is configured: there is no "off" switch here,
    because with the default bind address an auth check that defaults off is an
    unauthenticated public API. The refusal says what to do about it, and
    `warn_if_auth_disabled` has already shouted about it at startup.

    The comparison is constant-time (`hmac.compare_digest`, the in-repo standard
    per `pi_shared.mesh_protocol`): a plain `!=` leaks timing on the shared fleet
    secret byte by byte.
    """
    expected = settings.network_auth_token if settings is not None else None
    if expected is None:
        logger.error("network_auth_not_configured")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Network authentication is not configured on this Scheduler; "
                "refusing all requests. Set SCHEDULER_NETWORK_AUTH_TOKEN."
            ),
        )

    presented = x_network_auth_token or ""
    if not hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
