"""A served request is recorded, and the node that served it is credited (3.2, 3.3).

`CreditLedger` has existed and been unit-tested since long before this, with **no
caller anywhere in the running application** -- its own docstring said so, and
ROADMAP 3.3 was marked *partial* on exactly that basis. Hosts earned nothing because
nothing ever called `record_host_contribution`. These tests are what make 3.3 real:
they drive the gateway and then assert on the ledger and the meter, so a future
refactor that quietly unhooks the accrual fails here rather than being noticed months
later by a host asking why their balance is zero.

**Credits are an accounting unit, not a currency** -- see
`docs/decisions/D2-economics.md`. Nothing here is redeemable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.main import create_app
from scheduler.models.node import GPUInfo, Node

NODE_ID = "node-meter-1"


@pytest.fixture(scope="module")
def key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public_pem


@pytest.fixture
def client(key_pair: tuple[rsa.RSAPrivateKey, str]) -> TestClient:
    _, public_pem = key_pair
    app = create_app(
        jwt_public_key=public_pem,
        # The default bucket is capacity 5, refill 0.5/s, which several requests in
        # one test would trip.
        rate_limiter=TokenBucketLimiter(capacity=100, refill_rate=100.0),
    )
    app.state.registry._nodes[NODE_ID] = Node(
        node_id=NODE_ID,
        hostname="host-1",
        ip_address="10.0.0.5",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=16,
        ram_total_gb=64.0,
        available_models=["llama3"],
    )
    return TestClient(app)


@pytest.fixture
def auth(key_pair: tuple[rsa.RSAPrivateKey, str]) -> dict[str, str]:
    private, _ = key_pair
    token = jwt.encode(
        {
            "sub": "u",
            "tenant_id": "tenant-a",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        private,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _complete(client: TestClient, auth: dict[str, str], stream: bool = False) -> Any:
    return client.post(
        "/v1/chat/completions",
        headers=auth,
        json={
            "model": "llama3",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": stream,
        },
    )


def test_a_completed_request_is_metered(client: TestClient, auth: dict[str, str]) -> None:
    """The record exists, names the serving node, and carries token counts."""
    with patch(
        "scheduler.api.openai.infer_once",
        new=AsyncMock(return_value={"response": "Paris is the capital of France."}),
    ):
        assert _complete(client, auth).status_code == 200

    records = client.app.state.usage_meter.recent()
    assert len(records) == 1

    record = records[0]
    assert record.node_id == NODE_ID
    assert record.tenant_id == "tenant-a"
    assert record.model == "llama3"
    assert record.prompt_tokens > 0
    assert record.completion_tokens > 0
    assert record.succeeded is True


def test_the_serving_node_is_credited(client: TestClient, auth: dict[str, str]) -> None:
    """ROADMAP 3.3. The ledger had no caller in the app until now.

    Asserted as "greater than zero" rather than an exact figure: the accrual is
    VRAM-hours over a real elapsed duration, so pinning a value would pin the speed
    of the test machine.
    """
    ledger = client.app.state.ledger
    assert ledger.balances().get(NODE_ID, 0.0) == 0.0

    with patch(
        "scheduler.api.openai.infer_once",
        new=AsyncMock(return_value={"response": "Paris."}),
    ):
        assert _complete(client, auth).status_code == 200

    assert ledger.balances()[NODE_ID] > 0.0


def test_a_failed_dispatch_credits_nobody(client: TestClient, auth: dict[str, str]) -> None:
    """Crediting a failed request would pay a node for returning an error.

    That is precisely the incentive `docs/decisions/D1-execution-integrity.md` exists
    to avoid creating, so it gets its own test rather than being left implicit in the
    `succeeded` flag.
    """
    from scheduler.core.node_dispatch import NodeDispatchError

    with patch(
        "scheduler.api.openai.infer_once",
        new=AsyncMock(side_effect=NodeDispatchError(status=502, detail="node exploded")),
    ):
        assert _complete(client, auth).status_code == 502

    assert client.app.state.ledger.balances().get(NODE_ID, 0.0) == 0.0

    # The failure must also be RECORDED, not merely uncredited. Asserting only the
    # zero balance let a mutation removing the `and succeeded` guard survive, because
    # nothing was metered on this path at all -- the request raised before reaching
    # the meter, so `UsageRecord.succeeded=False` was documented but unreachable.
    records = client.app.state.usage_meter.recent()
    assert len(records) == 1, "a failed dispatch must still be metered"
    assert records[0].succeeded is False
    assert records[0].node_id == NODE_ID
    assert records[0].completion_tokens == 0


def test_a_streamed_request_is_metered_when_the_stream_ends(
    client: TestClient, auth: dict[str, str]
) -> None:
    """Streaming has no return statement to hang accounting on.

    The response has already started by the time anything is known, so the record is
    written in a `finally` around the generator. Without that, every streamed
    request -- the default for a chat UI -- would be invisible to metering and to
    the ledger.
    """

    async def _fake_stream() -> Any:
        for token in ("Paris", " is", " the", " capital"):
            yield token

    with patch(
        "scheduler.api.openai.open_inference_stream",
        new=AsyncMock(return_value=_fake_stream()),
    ):
        response = _complete(client, auth, stream=True)
        assert response.status_code == 200
        body = response.text

    assert "Paris" in body

    records = client.app.state.usage_meter.recent()
    assert len(records) == 1
    assert records[0].node_id == NODE_ID
    assert records[0].succeeded is True
    assert client.app.state.ledger.balances()[NODE_ID] > 0.0


def test_metering_failure_does_not_fail_the_request(
    client: TestClient, auth: dict[str, str]
) -> None:
    """A broken accounting system must not turn a good completion into a 500.

    The requester already has their tokens; the honest failure mode is a gap in the
    record, logged loudly. This is the behaviour that keeps a metering bug from
    becoming an outage.
    """
    client.app.state.usage_meter.record = AsyncMock(side_effect=RuntimeError("disk full"))

    with patch(
        "scheduler.api.openai.infer_once",
        new=AsyncMock(return_value={"response": "Paris."}),
    ):
        response = _complete(client, auth)

    assert response.status_code == 200
    assert "Paris" in response.text


def test_a_hosts_totals_are_reported_for_their_node_only(
    client: TestClient, auth: dict[str, str]
) -> None:
    """ROADMAP 3.4 reads this. A host must not see another host's numbers."""
    with patch(
        "scheduler.api.openai.infer_once",
        new=AsyncMock(return_value={"response": "Paris."}),
    ):
        _complete(client, auth)

    meter = client.app.state.usage_meter
    assert meter.totals_for_node(NODE_ID)["requests"] == 1.0
    assert meter.totals_for_node("some-other-node")["requests"] == 0.0
