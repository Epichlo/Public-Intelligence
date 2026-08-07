"""Unit and integration tests for Phase 4.9 Asynchronous Batch Processing and Credit Ledger."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.core.credit_ledger import CreditLedger
from scheduler.main import create_app


@pytest.mark.anyio
async def test_credit_ledger_accrual_and_deduction() -> None:
    """Verify CreditLedger host credit accrual (1 GB VRAM-Hour = 100 Credits) and deduction.

    Both mutators became async in ROADMAP 2.1 so they can write the new balance
    through to durable storage. The arithmetic is unchanged; this test is what pins
    that the store did not quietly alter it.
    """
    ledger = CreditLedger()

    # 1. Host compute accrual: 24 GB VRAM hosted for 1 hour (3600 seconds) -> 2400 credits
    account = await ledger.record_host_contribution(
        node_id="node-gpu-1", vram_gb=24.0, duration_seconds=3600.0
    )
    assert account.earned_credits == 2400.0
    assert account.net_balance == 2400.0

    # 2. Requester usage deduction: deduct 500 credits
    updated = await ledger.deduct_usage(account_id="node-gpu-1", amount=500.0)
    assert updated.consumed_credits == 500.0
    assert updated.net_balance == 1900.0


def test_batch_processing_api_endpoints() -> None:
    """Verify POST /v1/batch submission and GET /v1/batch/{batch_id} status lookup.

    **This test was pinning a fabrication as correct behaviour.** It asserted
    `status == "completed"` and `len(results) == 2` for a submission that contacted
    no node and ran no model -- the response text was a formatted string containing
    the caller's own prompt. Asserting the shape of invented output is worse than not
    testing it, because it converts the bug into a requirement.

    Rewritten under ROADMAP C9 to pin the refusal instead, and kept multi-item
    because that is what it uniquely covered: the refusal must not depend on batch
    size, and must not become a partial success for a longer list.

    Its earlier history is worth keeping too: both routes had no auth dependency when
    this was written, so it passed anonymously until ROADMAP 2.4.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    token = jwt.encode(
        {"tenant_id": "tenant-batch", "exp": datetime.now(UTC) + timedelta(hours=1)},
        private_key,
        algorithm="RS256",
    )
    auth = {"Authorization": f"Bearer {token}"}

    app = create_app()
    app.state.jwt_public_key = public_pem
    client = TestClient(app)

    payload = {
        "requests": [
            {
                "custom_id": "req-1",
                "model": "llama3",
                "prompt": "Summarize batch item 1",
                "max_tokens": 128,
            },
            {
                "custom_id": "req-2",
                "model": "llama3",
                "prompt": "Summarize batch item 2",
                "max_tokens": 128,
            },
        ],
        "priority": "batch",
    }

    # A two-item batch is refused exactly as a one-item batch is: 501, and nothing
    # in the body that a client could parse as either progress or model output.
    response = client.post("/v1/batch", json=payload, headers=auth)
    assert response.status_code == 501, response.text

    # Structure, not word-matching: the detail message legitimately mentions
    # "fabricated results" while explaining itself, and an earlier version of this
    # assertion failed on that. What must not happen is the body being READABLE as a
    # batch -- no id to poll, no counts, and none of the caller's prompts echoed back
    # in a field a client would render.
    body = response.json()
    assert set(body) == {"detail"}, f"the refusal carries batch-shaped fields: {sorted(body)}"
    assert "Summarize batch item" not in response.text, (
        "the refusal echoes the submitted prompts, which is how the fabricated "
        "version made its output look like a real completion"
    )

    # And nothing was recorded, so there is no id to look up afterwards.
    assert client.get("/v1/batch/batch_000000000000", headers=auth).status_code == 404
