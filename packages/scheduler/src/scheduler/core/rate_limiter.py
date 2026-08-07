"""Token Bucket Rate-Limiter implementation for multi-tenant isolation.

**This is an abuse dampener, not a quota.** It is in-memory and per-process: it
resets on restart and would not hold across replicas. ROADMAP C5 flagged that, and
`docs/decisions/D5-decentralisation-claim.md` settled it -- the deployment *is* a
single instance, so a per-instance limiter is adequate. Calling it a quota would be
a claim about a guarantee that does not exist, so nothing here does.

What C5 did require fixing: the limits were constructor defaults no operator could
reach, and `buckets` grew one entry per tenant and never shrank.
"""

import asyncio
import time

# How long a tenant's bucket may sit untouched before a sweep may drop it. Only
# buckets that have refilled to full capacity are ever dropped -- see `_evict_idle`.
DEFAULT_IDLE_EVICTION_SECONDS = 600.0

# Sweep every N acquisitions rather than on a timer: no background task to own, no
# shutdown hook to forget, and the cost is amortised over the traffic that caused
# the growth in the first place.
_SWEEP_INTERVAL_ACQUISITIONS = 256


class TokenBucketLimiter:
    """Asynchronous Token Bucket rate-limiter using an in-memory lock."""

    def __init__(
        self,
        capacity: int = 5,
        refill_rate: float = 0.5,
        idle_eviction_seconds: float = DEFAULT_IDLE_EVICTION_SECONDS,
    ) -> None:
        """Initialize the TokenBucketLimiter.

        Args:
            capacity: Max number of tokens (burst capacity). Defaults to 5.
            refill_rate: Refill rate in tokens per second. Defaults to 0.5 (1 token every 2s).
            idle_eviction_seconds: Drop a full, untouched bucket after this long.
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.idle_eviction_seconds = idle_eviction_seconds
        self.buckets: dict[str, float] = {}
        self.last_updated: dict[str, float] = {}
        self.lock = asyncio.Lock()
        self._acquisitions_since_sweep = 0

    def _evict_idle(self, now: float) -> None:
        """Drop buckets that are full and untouched. Never drop a depleted one.

        The "full" condition is what keeps eviction from becoming a rate-limit
        bypass: dropping an exhausted bucket would let the next request re-create it
        at full capacity, so a tenant could reset their own limit by waiting for a
        sweep. A bucket already at capacity carries no information, so removing it is
        indistinguishable from keeping it.

        Pinned by `test_eviction_never_hands_out_free_capacity`.
        """
        stale = []
        for tenant, tokens in self.buckets.items():
            idle_for = now - self.last_updated.get(tenant, now)
            if idle_for < self.idle_eviction_seconds:
                continue
            # Refill is computed here rather than read from `tokens`, because the
            # stored value is only updated when THAT tenant calls acquire(). Reading
            # it directly makes the sweep far too conservative: a bucket that has
            # long since refilled to capacity still shows its last depleted value,
            # so it is never eligible and the map never shrinks -- which is the bug
            # this method exists to fix, reintroduced inside the fix.
            projected = min(float(self.capacity), tokens + idle_for * self.refill_rate)
            if projected >= self.capacity:
                stale.append(tenant)
        for tenant in stale:
            # Both maps, or the one left behind becomes the leak the other stopped
            # being -- they are keyed identically and were both unbounded.
            del self.buckets[tenant]
            self.last_updated.pop(tenant, None)

    async def acquire(self, tenant_id: str) -> bool:
        """Attempt to acquire 1 token for a given tenant.

        Refills the tenant's bucket dynamically based on elapsed time.

        Args:
            tenant_id: Unique identifier for the tenant.

        Returns:
            True if a token was successfully acquired, False otherwise.
        """
        async with self.lock:
            now = time.time()

            self._acquisitions_since_sweep += 1
            if self._acquisitions_since_sweep >= _SWEEP_INTERVAL_ACQUISITIONS:
                self._acquisitions_since_sweep = 0
                self._evict_idle(now)

            if tenant_id not in self.buckets:
                self.buckets[tenant_id] = float(self.capacity)
                self.last_updated[tenant_id] = now

            # Calculate refilled tokens based on elapsed time
            elapsed = now - self.last_updated[tenant_id]
            refilled = elapsed * self.refill_rate
            self.buckets[tenant_id] = min(float(self.capacity), self.buckets[tenant_id] + refilled)
            self.last_updated[tenant_id] = now

            if self.buckets[tenant_id] >= 1.0:
                self.buckets[tenant_id] -= 1.0
                return True
            return False
