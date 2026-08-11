"""A host that did work must not be recorded as having done none.

Found on 2026-08-11, on the machine that closed the first clause of ROADMAP 1.5. It
served a real request over the mesh, and the ledger recorded:

    credit_accrued: node_id=node-local earned=0.00 new_balance=0.00

Not a rounding artefact. `earned = vram_gb * hours * CREDITS_PER_GB_VRAM_HOUR`, and a
CPU-only node reports `vram_total_gb: 0.0`, so the product is exactly zero for any
duration. **A CPU-only host could contribute forever and always be recorded as having
contributed nothing.**

Two roadmap decisions were in direct contradiction and neither noticed. ROADMAP 1.2
deliberately made CPU-only nodes representable and dispatchable -- it relaxed the
VRAM floor from `gt=0` to `ge=0` precisely so such a node could exist and be matched
to tasks with no VRAM requirement. ROADMAP 3.3 then measured contribution purely in
VRAM-hours. The first says these hosts are first-class; the second says their work
does not count.

This is the "never render uncertainty as zero" defect in a new costume: real work
rendered as no work.

See specs/what-two-machines-found.md.
"""

import pytest

from scheduler.core.credit_ledger import CreditLedger


@pytest.mark.asyncio
async def test_a_cpu_only_host_accrues_credit_for_real_work() -> None:
    """The regression. Fails against the VRAM-only formula, which returns 0.0."""
    ledger = CreditLedger()

    account = await ledger.record_host_contribution(
        node_id="cpu-host",
        vram_gb=0.0,
        duration_seconds=120.0,
        ram_gb=23.29,
    )

    assert account.earned_credits > 0.0, (
        "a CPU-only host served a request and accrued nothing; ROADMAP 1.2 made "
        "these nodes dispatchable, so 3.3 must be able to measure what they give"
    )


@pytest.mark.asyncio
async def test_a_gpu_host_is_priced_exactly_as_before() -> None:
    """Additive, not a repricing.

    The VRAM term is untouched, so an existing host's balance does not move because
    of this change. If it did, this would be a silent economic change dressed as a
    bug fix -- and D2 already settled that credits are an accounting unit, which is
    an argument for keeping the accounting stable.
    """
    ledger = CreditLedger()
    hours = 0.5

    account = await ledger.record_host_contribution(
        node_id="gpu-host",
        vram_gb=24.0,
        duration_seconds=hours * 3600.0,
        ram_gb=0.0,
    )

    assert account.earned_credits == pytest.approx(
        24.0 * hours * CreditLedger.CREDITS_PER_GB_VRAM_HOUR
    )


@pytest.mark.asyncio
async def test_ram_is_not_counted_twice_on_a_gpu_host() -> None:
    """A GPU host also has RAM. Crediting both would quietly reprice every GPU node.

    The RAM term is a FALLBACK for hosts with no GPU, not an additional revenue
    stream -- otherwise this "fix" raises what every existing host earns, which is a
    product decision nobody made.
    """
    ledger = CreditLedger()
    hours = 0.5
    seconds = hours * 3600.0

    with_ram = await ledger.record_host_contribution(
        node_id="gpu-with-ram", vram_gb=24.0, duration_seconds=seconds, ram_gb=64.0
    )
    without_ram = await CreditLedger().record_host_contribution(
        node_id="gpu-no-ram", vram_gb=24.0, duration_seconds=seconds, ram_gb=0.0
    )

    assert with_ram.earned_credits == pytest.approx(without_ram.earned_credits), (
        "declaring RAM changed a GPU host's credit, so this is a repricing rather "
        "than a fix for hosts that could not accrue at all"
    )


@pytest.mark.asyncio
async def test_ram_hours_are_worth_less_than_vram_hours() -> None:
    """The ratio is a guess, but its DIRECTION is not.

    A GPU-hour is the scarce thing this network exists to share. If CPU work were
    credited at parity, the cheapest way to earn would be to contribute no GPU at
    all, which inverts the incentive the ledger exists to create.
    """
    assert CreditLedger.CREDITS_PER_GB_RAM_HOUR < CreditLedger.CREDITS_PER_GB_VRAM_HOUR


@pytest.mark.asyncio
async def test_a_host_that_did_nothing_still_accrues_nothing() -> None:
    """Zero duration is genuinely zero contribution. The fix must not invent work."""
    ledger = CreditLedger()

    account = await ledger.record_host_contribution(
        node_id="idle-host", vram_gb=0.0, duration_seconds=0.0, ram_gb=23.29
    )

    assert account.earned_credits == 0.0


@pytest.mark.asyncio
async def test_ram_defaults_to_zero_so_existing_callers_are_unchanged() -> None:
    """`ram_gb` is optional. A caller that does not pass it gets the old behaviour."""
    ledger = CreditLedger()

    account = await ledger.record_host_contribution(
        node_id="legacy-caller", vram_gb=8.0, duration_seconds=3600.0
    )

    assert account.earned_credits == pytest.approx(8.0 * CreditLedger.CREDITS_PER_GB_VRAM_HOUR)
