"""Authentication dependency for the Node's local control and inference API.

The Node binds 0.0.0.0 by default (required inside containers), so its control
surface is reachable from the whole LAN. Unlike the Scheduler's OpenAI gateway,
this API has exactly one principal -- the machine's owner, acting through their
dashboard -- so it authenticates with a shared secret rather than a per-tenant
RS256 JWT. There is no tenant to attribute, nothing consumes a `tenant_id`
claim, and minting per-node tokens would mean running key distribution for a
single-user local control plane.

The credential is `Settings.network_auth_token`, sent in `X-Network-Auth-Token`.
That is the same header the Node already sends outbound to the Scheduler
(`node/clients/scheduler.py`) and the same one the Scheduler validates inbound
(`scheduler/api/auth.py`), so both services now use one scheme.

Deliberately different from `scheduler/api/auth.py` in one respect: this fails
CLOSED. That module returns successfully when no token is configured, which on a
0.0.0.0-bound control API means a default install is fully open -- the very
vulnerability this closes. A node with no token configured serves nothing.
"""

import hmac
from typing import Annotated

import structlog
from fastapi import Depends, Header, HTTPException, status

from node.core.configuration import Settings, get_settings

logger = structlog.stdlib.get_logger()


async def verify_node_auth(
    settings: Annotated[Settings, Depends(get_settings)],
    x_network_auth_token: Annotated[str | None, Header(alias="X-Network-Auth-Token")] = None,
) -> None:
    """Reject any request not carrying the node's configured auth token.

    Args:
        settings: Node settings supplying the expected token.
        x_network_auth_token: Credential supplied by the caller.

    Raises:
        HTTPException: 401 when no token is configured, or when the supplied
            credential is missing or incorrect.
    """
    expected = getattr(settings, "network_auth_token", None) if settings is not None else None

    if not expected:
        # Fail closed: an unconfigured node must not serve its control surface.
        logger.warning("node_auth_not_configured")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Node control API is not configured. Set NODE_NETWORK_AUTH_TOKEN in "
                "Node/.env (the installer generates one) and restart the node."
            ),
        )

    if not x_network_auth_token or not hmac.compare_digest(
        x_network_auth_token.encode("utf-8"), expected.encode("utf-8")
    ):
        logger.warning("node_auth_rejected")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized. Supply the node's X-Network-Auth-Token header.",
        )
