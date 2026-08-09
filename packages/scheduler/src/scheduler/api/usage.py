"""What a host's machine actually did (`/usage`, ROADMAP 3.4).

The dashboard showed live telemetry only -- CPU and VRAM gauges, a picture of a
moment. A host could see that their GPU was busy and had no way to learn what it had
served or what it had contributed. This is the read side of the metering added in 3.2.

**Language matters here and is not decoration.** These endpoints report credits
*contributed*, never *earned*. `docs/decisions/D2-economics.md` found the economics do
not close on consumer hardware, so credits are an accounting unit with no redemption
path -- and that is a decision, not a missing feature. A dashboard saying "earned"
would be making a promise the project has explicitly declined to make.

Guarded at the router level with the same fleet credential as the rest of the read
surface (ROADMAP 2.6). Usage records name tenants and nodes, so this is not public.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Request

from scheduler.api.auth import verify_auth_token

if TYPE_CHECKING:
    from scheduler.core.credit_ledger import CreditLedger
    from scheduler.core.metering import UsageMeter

router = APIRouter(tags=["usage"], dependencies=[Depends(verify_auth_token)])


def get_meter(request: Request) -> UsageMeter:
    """Retrieve the UsageMeter from application state."""
    meter: UsageMeter = request.app.state.usage_meter
    return meter


def get_ledger(request: Request) -> CreditLedger:
    """Retrieve the CreditLedger from application state."""
    ledger: CreditLedger = request.app.state.ledger
    return ledger


MeterDep = Annotated["UsageMeter", Depends(get_meter)]
LedgerDep = Annotated["CreditLedger", Depends(get_ledger)]


@router.get("/usage")
async def list_recent_usage(meter: MeterDep, limit: int = 50) -> dict[str, Any]:
    """Recent served requests across the fleet, newest first.

    `window` is reported alongside the records because the in-memory tail is bounded
    (`UsageMeter.MAX_RECENT`). A caller that assumed this was all-time would draw a
    graph that silently flattens once the buffer wraps -- the store keeps the full
    history, this endpoint serves the tail, and the response says which it is.
    """
    limit = max(1, min(limit, meter.MAX_RECENT))
    records = meter.recent(limit=limit)
    return {
        "window": "recent",
        "window_size": meter.MAX_RECENT,
        "count": len(records),
        "records": [r.model_dump() for r in records],
    }


@router.get("/nodes/{node_id}/usage")
async def node_usage(node_id: str, meter: MeterDep, ledger: LedgerDep) -> dict[str, Any]:
    """One host's own numbers: what their machine served, and what it contributed.

    The account balance is exact and all-time -- it comes from the ledger, which is
    persisted per event. The request totals are windowed, for the reason above. Both
    are returned together and labelled, rather than blended into one figure that
    would be right about one half and wrong about the other.
    """
    totals = meter.totals_for_node(node_id)
    account = ledger.get_or_create_account(node_id)

    return {
        "node_id": node_id,
        # "contributed", not "earned". See the module docstring and D2.
        "credits_contributed": account.earned_credits,
        "credits_are_redeemable": False,
        "totals_window": "recent",
        "totals_window_size": meter.MAX_RECENT,
        "totals": totals,
        "recent": [r.model_dump() for r in meter.recent(node_id=node_id, limit=25)],
    }
