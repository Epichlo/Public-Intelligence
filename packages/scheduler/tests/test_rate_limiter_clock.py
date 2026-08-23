"""The limiter must measure elapsed time with a clock that cannot step backwards.

`TokenBucketLimiter.acquire` refills on `elapsed * rate`, so its clock only needs
one property: differences between two readings must be meaningful. `time.time()`
is a wall clock, and NTP corrections and resume-from-sleep move it in BOTH
directions -- a step backwards makes `elapsed` negative, `refilled` negative with
it, and the tenant's bucket SHRINKS by however far the clock jumped. The same
hazard was called out for request metering in `api/openai.py`: only differences
of a monotonic clock mean anything, and this class takes nothing else.
"""

import time
from unittest.mock import patch

from scheduler.core.rate_limiter import TokenBucketLimiter


async def test_a_wall_clock_step_backwards_cannot_shrink_a_bucket() -> None:
    """Exhaust a bucket, step the wall clock back an hour, acquire again.

    With the wall clock driving refill, the negative elapsed refills NEGATIVE
    tokens: the stored balance drops below zero, and the tenant cannot earn it
    back until the clock catches up with the debt the step invented. An NTP
    correction must never cost a tenant capacity it already had.
    """
    limiter = TokenBucketLimiter(capacity=2, refill_rate=1.0)

    assert await limiter.acquire("tenant") is True
    assert await limiter.acquire("tenant") is True
    assert await limiter.acquire("tenant") is False

    stepped_back = time.time() - 3600.0
    with patch("time.time", return_value=stepped_back):
        await limiter.acquire("tenant")

    assert limiter.buckets["tenant"] >= 0.0, (
        "a backwards wall-clock step drove the bucket below zero "
        f"(balance: {limiter.buckets['tenant']})"
    )


async def test_elapsed_monotonic_time_still_refills_the_bucket() -> None:
    """Positive control: the clock the limiter reads must actually refill.

    Drives `time.monotonic()` through a fixed sequence and asserts a depleted
    bucket refills from elapsed time alone. This is what pins the clock CHOICE,
    not just the failure mode above: against the wall-clock implementation the
    patched sequence is never consulted and the third acquire finds nothing.
    """
    limiter = TokenBucketLimiter(capacity=2, refill_rate=1.0)

    with patch("time.monotonic", side_effect=[100.0, 100.0, 102.5]):
        assert await limiter.acquire("tenant") is True
        assert await limiter.acquire("tenant") is True
        assert await limiter.acquire("tenant") is True, (
            "2.5 seconds of monotonic elapsed time must refill the spent token"
        )
