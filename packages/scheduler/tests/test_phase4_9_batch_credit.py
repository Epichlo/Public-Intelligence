"""Unit and integration tests for Phase 4.9 Asynchronous Batch Processing and Credit Ledger."""

import pytest
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
    """Verify POST /v1/batch submission and GET /v1/batch/{batch_id} status lookup."""
    app = create_app()
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

    # Submit batch job
    response = client.post("/v1/batch", json=payload)
    assert response.status_code == 202
    data = response.json()

    assert "batch_id" in data
    assert data["status"] == "completed"
    assert data["total_items"] == 2
    assert len(data["results"]) == 2
    batch_id = data["batch_id"]

    # Query status
    status_resp = client.get(f"/v1/batch/{batch_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()

    assert status_data["batch_id"] == batch_id
    assert status_data["completed_items"] == 2
