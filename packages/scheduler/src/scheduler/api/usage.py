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


@router.get("/metrics")
async def metrics(request: Request, meter: MeterDep) -> dict[str, Any]:
    """Aggregate counters for an operator or a scrape (ROADMAP 4.2).

    4.2 says: "Structured logs exist; no aggregation, no alerting. You currently
    learn something broke by reading CI." This is the aggregation half. Alerting is
    not here and is not pretended: something outside this process has to poll and
    decide, and shipping a half-built alerter would be worse than shipping none.

    **JSON rather than Prometheus text format.** A Prometheus exposition endpoint
    implies a scrape contract -- metric naming, label cardinality, HELP/TYPE lines --
    and getting that subtly wrong is harder to notice than not having it. This is a
    small, honest surface that says what it counts. Adopting Prometheus later is a
    serialiser change, not a redesign.

    Windowed over the meter's in-memory tail, which the response states rather than
    implies. Same reasoning as `/usage`: a counter presented as all-time that silently
    resets when a buffer wraps is worse than no counter.
    """
    records = meter.recent(limit=meter.MAX_RECENT)
    registry = request.app.state.registry
    nodes = await registry.list()

    failed = sum(1 for r in records if not r.succeeded)
    by_node: dict[str, int] = {}
    for record in records:
        by_node[record.node_id] = by_node.get(record.node_id, 0) + 1

    return {
        "window": "recent",
        "window_size": meter.MAX_RECENT,
        "nodes_registered": len(nodes),
        "requests_in_window": len(records),
        "requests_failed_in_window": failed,
        # The number an operator actually watches. Reported as a fraction of the
        # window rather than as a rate per second: the window is a request count,
        # not a time interval, so a per-second figure would be invented.
        "failure_ratio_in_window": (failed / len(records)) if records else 0.0,
        "prompt_tokens_in_window": sum(r.prompt_tokens for r in records),
        "completion_tokens_in_window": sum(r.completion_tokens for r in records),
        "requests_by_node_in_window": by_node,
        # Named so nobody reads the block above as lifetime totals.
        "note": (
            "All counters are over the most recent window_size requests held in "
            "memory, not since process start. The store holds full history."
        ),
    }
