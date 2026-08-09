"""What the gateway does when things are broken (ROADMAP 4.3).

The roadmap line reads: "Behaviour when no node has the model, when a node dies
mid-stream, when Ollama is down. Partly handled (503s), never tested end-to-end."
This is the end-to-end half.

The distinction these tests exist to hold is between **a failure the caller can act
on** and **a failure disguised as success**. That is the same distinction ROADMAP N1
and C9 were about: a 200 carrying invented text, and a 202 for a batch nothing ran.
The failure modes below are the remaining places where the easy implementation would
be to return something plausible.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.core.node_dispatch import NodeDispatchError
from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.main import create_app
from scheduler.models.node import GPUInfo, Node

NODE_ID = "node-degrade-1"


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


def _app(key_pair: tuple[rsa.RSAPrivateKey, str], with_node: bool = True) -> TestClient:
    _, public_pem = key_pair
    app = create_app(
        jwt_public_key=public_pem,
        rate_limiter=TokenBucketLimiter(capacity=100, refill_rate=100.0),
    )
    if with_node:
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


def _complete(client: TestClient, auth: dict[str, str], model: str = "llama3", **kw: Any) -> Any:
    return client.post(
        "/v1/chat/completions",
        headers=auth,
        json={"model": model, "messages": [{"role": "user", "content": "hi"}], **kw},
    )


# --- no capacity -----------------------------------------------------------


def test_an_empty_fleet_answers_503_not_an_empty_completion(
    key_pair: tuple[rsa.RSAPrivateKey, str], auth: dict[str, str]
) -> None:
    """503 says "try later". A 200 with empty content would say "the model said nothing"."""
    response = _complete(_app(key_pair, with_node=False), auth)

    assert response.status_code == 503
    assert "choices" not in response.json()


def test_a_model_no_node_has_answers_503_rather_than_silently_substituting(
    key_pair: tuple[rsa.RSAPrivateKey, str], auth: dict[str, str]
) -> None:
    """Serving a different model than asked for is the worst available failure.

    The caller gets a plausible answer from the wrong weights and has no way to
    tell. Everything else here is recoverable; this one is silent.
    """
    response = _complete(_app(key_pair), auth, model="a-model-nobody-hosts")

    assert response.status_code == 503
    body = response.json()
    assert "choices" not in body
    assert "llama3" not in json.dumps(body), "the refusal must not name a substitute"


# --- the node fails --------------------------------------------------------


def test_a_node_that_refuses_the_request_propagates_its_status(
    key_pair: tuple[rsa.RSAPrivateKey, str], auth: dict[str, str]
) -> None:
    """A node's 404 for an unpulled model must not become a 500.

    "The model is not there" is actionable; "internal server error" is not.
    """
    client = _app(key_pair)
    with patch(
        "scheduler.api.openai.infer_once",
        new=AsyncMock(side_effect=NodeDispatchError(status=404, detail="model not found")),
    ):
        assert _complete(client, auth).status_code == 404


def test_ollama_being_down_surfaces_as_502_not_as_a_completion(
    key_pair: tuple[rsa.RSAPrivateKey, str], auth: dict[str, str]
) -> None:
    """The backend behind the node is unreachable. Nothing may be invented."""
    client = _app(key_pair)
    with patch(
        "scheduler.api.openai.infer_once",
        new=AsyncMock(side_effect=NodeDispatchError(status=502, detail="ollama unreachable")),
    ):
        response = _complete(client, auth)

    assert response.status_code == 502
    assert "choices" not in response.json()


# --- the node dies mid-stream ---------------------------------------------


def test_a_node_dying_mid_stream_is_reported_inside_the_stream(
    key_pair: tuple[rsa.RSAPrivateKey, str], auth: dict[str, str]
) -> None:
    """Too late for a status code, so the caller is told in-band -- and not with [DONE].

    A stream that stops early and terminates normally is indistinguishable from a
    complete answer, which is the streaming version of returning invented text. The
    error has to be visible in the body.
    """
    client = _app(key_pair)

    async def _dying_stream() -> AsyncGenerator[str, None]:
        yield "Paris"
        raise NodeDispatchError(status=502, detail="node vanished")

    with patch(
        "scheduler.api.openai.open_inference_stream",
        new=AsyncMock(return_value=_dying_stream()),
    ):
        response = _complete(client, auth, stream=True)
        body = response.text

    assert response.status_code == 200, "headers were already sent; the status cannot change"
    assert "Paris" in body, "tokens produced before the failure are still the caller's"
    assert "error" in body.lower(), f"the failure is not visible in the stream: {body!r}"


def test_a_partial_stream_is_still_metered(
    key_pair: tuple[rsa.RSAPrivateKey, str], auth: dict[str, str]
) -> None:
    """The node spent real time before it failed, and the record must say so.

    Dropping the record would make a node that fails halfway through every request
    look, in the usage table, like a node that serves no traffic at all.
    """
    client = _app(key_pair)

    async def _dying_stream() -> AsyncGenerator[str, None]:
        yield "Paris"
        raise NodeDispatchError(status=502, detail="node vanished")

    with patch(
        "scheduler.api.openai.open_inference_stream",
        new=AsyncMock(return_value=_dying_stream()),
    ):
        _complete(client, auth, stream=True)

    records = client.app.state.usage_meter.recent()
    assert len(records) == 1
    assert records[0].node_id == NODE_ID


# --- overload --------------------------------------------------------------


def test_the_rate_limit_answers_429_with_a_reason(
    key_pair: tuple[rsa.RSAPrivateKey, str], auth: dict[str, str]
) -> None:
    """429, not 503: the caller is being throttled, not told the fleet is empty.

    Confusing the two sends a client into the wrong retry strategy -- back off
    versus fail over.
    """
    _, public_pem = key_pair
    app = create_app(
        jwt_public_key=public_pem,
        rate_limiter=TokenBucketLimiter(capacity=1, refill_rate=0.0),
    )
    client = TestClient(app)

    first = _complete(client, auth)
    second = _complete(client, auth)

    assert first.status_code != 429, "the first request must get through"
    assert second.status_code == 429


def test_a_node_dying_mid_stream_is_recorded_as_a_failure_and_credits_nobody(
    key_pair: tuple[rsa.RSAPrivateKey, str], auth: dict[str, str]
) -> None:
    """The stream ends "cleanly" from the wrapper's point of view, and must not count.

    `sse_generator` catches `NodeDispatchError` itself, emits an error chunk and
    returns normally -- so the metering wrapper around it sees an ordinary
    completion. Recording that as a success would credit a node for returning an
    error, which is exactly the incentive
    `docs/decisions/D1-execution-integrity.md` exists to avoid creating.

    `test_a_partial_stream_is_still_metered` above asserts the record EXISTS; this
    asserts what it says. The first version of that test checked only existence and
    passed while the flag was wrong.
    """
    client = _app(key_pair)

    async def _dying_stream() -> AsyncGenerator[str, None]:
        yield "Paris"
        raise NodeDispatchError(status=502, detail="node vanished")

    with patch(
        "scheduler.api.openai.open_inference_stream",
        new=AsyncMock(return_value=_dying_stream()),
    ):
        _complete(client, auth, stream=True)

    record = client.app.state.usage_meter.recent()[0]
    assert record.succeeded is False, "a stream that failed mid-flight was recorded as a success"
    assert client.app.state.ledger.balances().get(NODE_ID, 0.0) == 0.0, (
        "the node was credited for a request that failed"
    )
