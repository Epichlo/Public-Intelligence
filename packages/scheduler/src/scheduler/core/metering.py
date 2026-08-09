"""Usage metering: what each request consumed and which node served it (ROADMAP 3.2).

**This module deliberately cannot record prompt or completion text.** That is the
single design decision keeping the data-protection exposure small
(`docs/decisions/D3-terms-and-liability.md`), and it is enforced by construction
rather than by intention: `UsageRecord` is a closed pydantic model with
`extra="forbid"` and no free-text field, so adding somewhere to put a prompt means
editing this file, and `tests/test_metering_privacy.py` fails when a field that could
carry one appears.

The Scheduler proxies request bodies to nodes, so prompts pass *through* it either
way. What it must never do is keep them.

**Metering is not billing.** `docs/decisions/D2-economics.md` found the economics do
not close for a marketplace, so credits are an accounting unit and there is no payout
path. These records exist for the three things that survive that decision: a host
seeing what their machine actually did, an operator investigating abuse, and fair
quota. They were never *only* for money.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Sequence

    from scheduler.persistence import SchedulerStore

logger = logging.getLogger(__name__)

# Field names that would carry request content. Kept here, next to the model, so the
# privacy test and the model cannot drift apart -- the test imports this tuple rather
# than restating it.
FORBIDDEN_CONTENT_FIELDS = (
    "prompt",
    "prompt_text",
    "messages",
    "completion",
    "completion_text",
    "response",
    "response_text",
    "content",
    "generated_text",
    "output",
    "input",
    "text",
    "body",
)


class UsageRecord(BaseModel):
    """One served request, in counts only.

    `extra="forbid"` is load-bearing, not tidiness: without it a caller could pass
    `prompt="..."` and pydantic would silently carry it into the record and into the
    database. With it, that is a validation error at the call site.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(description="The completion id this usage belongs to")
    tenant_id: str = Field(description="Requester tenant from the verified JWT claim")
    node_id: str = Field(description="Node that served it -- the evidence half of D1")
    model: str = Field(description="Model name requested")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    # `False` for a request that failed after a node was selected. Recorded rather
    # than dropped: "which node keeps failing" is a question this table should be
    # able to answer, and it is the cheapest input D1's canary work can build on.
    succeeded: bool = Field(default=True)
    recorded_at: float = Field(default_factory=time.time)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class UsageMeter:
    """Records usage, and credits the serving node (ROADMAP 3.2 + 3.3).

    Holds a bounded in-memory tail for the dashboard and writes through to the store
    for durability, the same shape `NodeRegistry` and `CreditLedger` use.
    """

    # Bounded, because this grows per request rather than per node. An unbounded list
    # here would be the rate limiter's old bug with a faster clock -- see ROADMAP C5.
    # The store keeps the full history; this is only what the dashboard reads.
    MAX_RECENT = 500

    def __init__(self, store: SchedulerStore | None = None) -> None:
        self._recent: list[UsageRecord] = []
        self._store = store

    async def load(self) -> None:
        """Refill the recent tail from the store. Call once, at startup."""
        if self._store is None:
            return
        records = await self._store.load_usage(limit=self.MAX_RECENT)
        self._recent = list(records)[-self.MAX_RECENT :]
        logger.info("usage_meter_loaded: records=%d", len(self._recent))

    async def record(self, usage: UsageRecord) -> UsageRecord:
        """Persist one served request.

        Takes a built `UsageRecord` rather than keyword arguments so that the
        `extra="forbid"` guard runs at the caller's site, where the mistake would be
        made, instead of here where it would be too late to attribute.
        """
        self._recent.append(usage)
        if len(self._recent) > self.MAX_RECENT:
            del self._recent[: -self.MAX_RECENT]

        if self._store is not None:
            await self._store.save_usage(usage)

        logger.info(
            "usage_recorded: request_id=%s node_id=%s tenant=%s tokens=%d ok=%s",
            usage.request_id,
            usage.node_id,
            usage.tenant_id,
            usage.total_tokens,
            usage.succeeded,
        )
        return usage

    def recent(self, node_id: str | None = None, limit: int = 50) -> list[UsageRecord]:
        """Most recent records, newest first, optionally for one node."""
        records: Sequence[UsageRecord] = self._recent
        if node_id is not None:
            records = [r for r in records if r.node_id == node_id]
        return list(reversed(records[-limit:]))

    def totals_for_node(self, node_id: str) -> dict[str, float]:
        """What one host's machine has done, for their dashboard.

        Computed from the in-memory tail, so it covers the recent window rather than
        all time -- and the dashboard says so. Reporting a lifetime total from a
        bounded buffer would be the kind of quietly-wrong number this project keeps
        finding.
        """
        mine = [r for r in self._recent if r.node_id == node_id]
        return {
            "requests": float(len(mine)),
            "prompt_tokens": float(sum(r.prompt_tokens for r in mine)),
            "completion_tokens": float(sum(r.completion_tokens for r in mine)),
            "failed_requests": float(sum(1 for r in mine if not r.succeeded)),
        }
