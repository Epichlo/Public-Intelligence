"""`/v1/batch` must not answer 200 with text no model produced (supersedes C9).

ROADMAP C9 says "batch jobs are still not persisted, now unblocked by 2.4". Doing it
meant reading `submit_batch_job` closely, and the persistence gap is not the problem
with this endpoint.

**It fabricates its results.** Every item comes back with

    [Batch Response for '<the first 30 chars of your prompt>...'] Completed
    asynchronously via WAN pipeline.

at `status_code: 200`, `status: "completed"`, in the shape a client parses as model
output. Nothing is dispatched. No node is contacted. `completed_items` equals
`total_items` because the loop that "completed" them is a list comprehension over the
request.

This is the same defect as ROADMAP N1, in a different endpoint. There, a valid JWT
plus `x-split-inference: true` returned HTTP 200 with `content: 'token_556'` from a
seeded random-matrix simulation, and every OpenAI-compatible client would have shown
it to a user as the model's answer. The fix was 501 and **deletion of the execution
block**, on the reasoning that the server understands the request and has no
implementation -- a 400 would blame the caller, and quietly serving something else
would tell them they got what they asked for.

The same reasoning applies here, and C9 is superseded by it: **persisting a
fabrication makes it durable, not true.** A stub whose output survives a restart is
worse than one whose output does not.

The `2.4` work on this endpoint is preserved -- authentication and tenant scoping
were real fixes to a real hole, and they still apply. What is removed is the part
that invents an answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.main import create_app

FABRICATION_MARKERS = ("Completed asynchronously", "WAN pipeline", "Batch Response for")


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
    app = create_app(jwt_public_key=public_pem)
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


def _submit(client: TestClient, auth: dict[str, str]) -> Any:
    return client.post(
        "/v1/batch",
        headers=auth,
        json={"requests": [{"custom_id": "a", "prompt": "What is the capital of France?"}]},
    )


def test_submitting_a_batch_is_refused_with_501(client: TestClient, auth: dict[str, str]) -> None:
    """501, matching ROADMAP N1: understood, not implemented.

    Not 400 -- that blames the caller for a well-formed request. Not 200 with a
    placeholder -- that is the bug.
    """
    response = _submit(client, auth)
    assert response.status_code == 501, response.text


def test_no_response_body_can_be_mistaken_for_model_output(
    client: TestClient, auth: dict[str, str]
) -> None:
    """The refusal must not carry the fabricated strings in any form."""
    body = _submit(client, auth).text
    for marker in FABRICATION_MARKERS:
        assert marker not in body, f"the fabricated batch text {marker!r} is still served"


def test_the_fabrication_is_deleted_from_the_source_not_guarded(client: TestClient) -> None:
    """N1's lesson: dead code behind a disabled flag is how that bug survived.

    The execution block was deleted there rather than left behind the guard, and the
    same applies here -- a fabricating branch that is currently unreachable is one
    edit away from being reachable again.
    """
    import ast
    import inspect

    from scheduler.api import batch

    tree = ast.parse(inspect.getsource(batch))

    # Docstrings are excluded, or this test fails on the docstring that explains what
    # was removed -- which happened, and is the third time in this change set that a
    # check fired on its own account of the bug. What matters is whether a fabricated
    # string can still be RETURNED, so only non-docstring literals are scanned.
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    live_strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]

    for marker in FABRICATION_MARKERS:
        offenders = [text for text in live_strings if marker in text]
        assert not offenders, (
            f"{marker!r} is still a live string in scheduler/api/batch.py, not just "
            f"a docstring: {offenders}. Delete the block; do not guard it."
        )


def test_authentication_is_still_required(client: TestClient) -> None:
    """ROADMAP 2.4's fix survives this change.

    2.4 gave both batch routes a JWT dependency, after they had none while their
    sibling `/v1/chat/completions` required one. Refusing to *implement* the feature
    must not quietly un-refuse *unauthenticated* access to it -- a 501 that answers
    anyone is a smaller bug than a 200, not no bug.
    """
    assert (
        client.post("/v1/batch", json={"requests": [{"custom_id": "a", "prompt": "x"}]}).status_code
        == 401
    )
    assert client.get("/v1/batch/batch_whatever").status_code == 401


def test_retrieving_a_batch_returns_404_for_everyone(
    client: TestClient, auth: dict[str, str]
) -> None:
    """With nothing submittable, every id is absent -- and says so identically.

    2.4 made a batch belonging to another tenant answer 404 rather than 403, so the
    endpoint could not be used to enumerate real batch ids. Now no batch exists at
    all, which is the same answer for a different reason, and the behaviour a client
    sees is unchanged.
    """
    response = client.get("/v1/batch/batch_does_not_exist", headers=auth)
    assert response.status_code == 404
