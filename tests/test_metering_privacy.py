"""Metering must never be able to record prompt or completion text (D3, ROADMAP 3.2).

`docs/decisions/D3-terms-and-liability.md` answered the data-protection question by
narrowing the product until the exposure is small, and this is the one piece of that
answer which is a property of the code rather than of the deployment: **the Scheduler
proxies prompts, and does not keep them.**

That claim is only worth making if something enforces it. This is that something. It
lives in the root `tests/` rather than in the scheduler package because it is a
cross-cutting guarantee the whole product rests on -- `docs/OPERATING.md` tells
operators it holds, and `docs/PREMISES.md` lists it as P6.

P6's falsifier is stated there and is worth repeating: this constrains **this
codebase**. An operator who adds request-body logging, or puts a proxy in front,
reintroduces the exposure and no test here can see it.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError
from scheduler.core.metering import FORBIDDEN_CONTENT_FIELDS, UsageMeter, UsageRecord


def _record(**overrides: object) -> UsageRecord:
    fields: dict[str, object] = {
        "request_id": "chatcmpl-1",
        "tenant_id": "tenant-a",
        "node_id": "node-1",
        "model": "llama3",
        "prompt_tokens": 12,
        "completion_tokens": 34,
    }
    fields.update(overrides)
    return UsageRecord(**fields)  # type: ignore[arg-type]


def test_the_record_has_no_field_that_could_carry_request_content() -> None:
    """The core assertion. Counts, ids and timings only.

    Checked against the model's declared fields rather than against an instance, so
    a field that is merely optional or defaulted to None still fails.
    """
    declared = set(UsageRecord.model_fields)
    offenders = sorted(declared & set(FORBIDDEN_CONTENT_FIELDS))
    assert not offenders, (
        f"UsageRecord declares {offenders}, which can hold prompt or completion "
        f"text. The Scheduler proxies prompts and must not keep them "
        f"(docs/decisions/D3-terms-and-liability.md)."
    )


def test_no_field_is_an_unconstrained_string_beyond_the_known_identifiers() -> None:
    """A field named `note` would pass the list above and defeat the guarantee.

    So the check is inverted: every string-typed field must be one of the
    identifiers this record is *supposed* to have. Adding a new one is then a
    deliberate edit to this list, with a reviewer looking at it.
    """
    allowed_string_fields = {"request_id", "tenant_id", "node_id", "model"}
    string_fields = {
        name
        for name, field in UsageRecord.model_fields.items()
        if field.annotation is str  # bool/int/float are not free text
    }
    unexpected = sorted(string_fields - allowed_string_fields)
    assert not unexpected, (
        f"UsageRecord gained free-text field(s) {unexpected}. If they are genuinely "
        f"identifiers, add them to allowed_string_fields deliberately."
    )


@pytest.mark.parametrize("field", FORBIDDEN_CONTENT_FIELDS)
def test_passing_content_to_the_record_is_a_validation_error(field: str) -> None:
    """`extra="forbid"` must be on, or a caller could smuggle text in silently.

    Without it pydantic would ignore the unknown key at construction and a later
    `model_dump()` would be clean -- but a future `extra="allow"` flipped by someone
    tidying config would carry it straight into the database. Fail at the call site.
    """
    with pytest.raises(ValidationError):
        _record(**{field: "What is the capital of France?"})


def test_a_recorded_usage_serialises_without_any_request_content() -> None:
    """End to end: what reaches the store contains none of the request."""
    dumped = _record().model_dump()
    assert set(dumped) & set(FORBIDDEN_CONTENT_FIELDS) == set()
    assert "France" not in str(dumped)


@pytest.mark.anyio
async def test_the_meter_persists_only_the_record_it_was_given(anyio_backend: str) -> None:
    """The meter must not enrich a record with anything on its way to the store."""
    saved: list[UsageRecord] = []

    class _Store:
        async def save_usage(self, usage: UsageRecord) -> None:
            saved.append(usage)

        async def load_usage(self, limit: int) -> list[UsageRecord]:
            return []

    meter = UsageMeter(store=_Store())  # type: ignore[arg-type]
    original = _record()
    await meter.record(original)

    assert saved == [original]


def test_the_meter_does_not_log_request_content() -> None:
    """Logging is the likeliest accidental leak, and it is not covered by the model.

    A log line interpolating a prompt would satisfy every assertion above. Checked by
    reading the source for the formatting arguments actually passed.
    """
    source = inspect.getsource(UsageMeter)
    for field in FORBIDDEN_CONTENT_FIELDS:
        assert f"usage.{field}" not in source, (
            f"UsageMeter references usage.{field} -- which cannot exist on the model, "
            f"so this is a leak being prepared for."
        )


def test_the_recent_buffer_is_bounded() -> None:
    """Unbounded growth keyed by request volume is ROADMAP C5's bug with a faster clock."""
    meter = UsageMeter()
    assert meter.MAX_RECENT > 0

    import asyncio

    async def fill() -> None:
        for i in range(meter.MAX_RECENT + 50):
            await meter.record(_record(request_id=f"chatcmpl-{i}"))

    asyncio.run(fill())
    assert len(meter._recent) == meter.MAX_RECENT
