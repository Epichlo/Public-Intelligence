"""`/v1/batch` must require a credential, and scope results to who submitted them.

Both routes had no auth dependency at all while their sibling
`/v1/chat/completions` required an RS256 JWT. Authentication alone would not be
enough: a batch carried no owner, so any valid token could read every batch by id.

See specs/close-the-open-http-surface.md.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.main import create_app

PAYLOAD: dict[str, Any] = {
    "requests": [{"custom_id": "req-1", "model": "llama3", "prompt": "hello", "max_tokens": 8}],
    "priority": "batch",
}


@pytest.fixture(scope="module")
def key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    """An RSA key pair; the public half is what the app verifies against."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_key, public_pem


@pytest.fixture
def client(key_pair: tuple[rsa.RSAPrivateKey, str]) -> TestClient:
    """An app that trusts `key_pair`'s public half."""
    _, public_pem = key_pair
    app = create_app()
    app.state.jwt_public_key = public_pem
    return TestClient(app)


def bearer(private_key: rsa.RSAPrivateKey, tenant_id: str) -> dict[str, str]:
    """A valid RS256 bearer token for `tenant_id`."""
    token = jwt.encode(
        {"tenant_id": tenant_id, "exp": datetime.now(UTC) + timedelta(hours=1)},
        private_key,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


# --- authentication ---------------------------------------------------------


def test_submitting_without_a_credential_is_rejected(client: TestClient) -> None:
    """401, and specifically NOT 202.

    Anyone who could reach the Scheduler could queue work. The status matters as
    much as the rejection: `Header(...)` made the header required by FastAPI, so a
    missing one produced a 422 validation error rather than an authentication
    failure.
    """
    response = client.post("/v1/batch", json=PAYLOAD)

    assert response.status_code == 401


def test_reading_a_batch_without_a_credential_is_rejected(client: TestClient) -> None:
    """The read side was open too, which is what made ids worth guessing."""
    response = client.get("/v1/batch/batch_whatever")

    assert response.status_code == 401


def test_a_garbage_token_is_rejected(client: TestClient) -> None:
    """Fails closed on an unverifiable signature rather than falling through."""
    response = client.post("/v1/batch", json=PAYLOAD, headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401


def test_a_valid_token_can_submit(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """The endpoint still works for a legitimate caller."""
    private_key, _ = key_pair

    response = client.post("/v1/batch", json=PAYLOAD, headers=bearer(private_key, "tenant-a"))

    assert response.status_code == 202
    assert response.json()["total_items"] == 1


# --- authorisation ----------------------------------------------------------


def test_the_submitting_tenant_can_read_its_own_batch(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """The ownership check must not lock out the owner."""
    private_key, _ = key_pair
    auth = bearer(private_key, "tenant-a")

    batch_id = client.post("/v1/batch", json=PAYLOAD, headers=auth).json()["batch_id"]
    response = client.get(f"/v1/batch/{batch_id}", headers=auth)

    assert response.status_code == 200
    assert response.json()["batch_id"] == batch_id


def test_another_tenant_cannot_read_it(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """Authentication without ownership would mean any token reads every batch."""
    private_key, _ = key_pair

    batch_id = client.post(
        "/v1/batch", json=PAYLOAD, headers=bearer(private_key, "tenant-a")
    ).json()["batch_id"]
    response = client.get(f"/v1/batch/{batch_id}", headers=bearer(private_key, "tenant-b"))

    assert response.status_code == 404


def test_someone_elses_batch_is_indistinguishable_from_a_missing_one(
    client: TestClient, key_pair: tuple[rsa.RSAPrivateKey, str]
) -> None:
    """403 would confirm the id exists, making the endpoint an enumeration oracle."""
    private_key, _ = key_pair

    batch_id = client.post(
        "/v1/batch", json=PAYLOAD, headers=bearer(private_key, "tenant-a")
    ).json()["batch_id"]
    other = bearer(private_key, "tenant-b")

    theirs = client.get(f"/v1/batch/{batch_id}", headers=other)
    absent = client.get("/v1/batch/batch_000000000000", headers=other)

    assert theirs.status_code == absent.status_code == 404
    # The two bodies necessarily differ in the id each caller asked about; comparing
    # them directly was a flaw in this test, not a leak. What must not differ is
    # anything else -- both answer the same "not found" template, so neither reply
    # reveals which of the two ids is real.
    assert theirs.json() == {"detail": f"Batch job {batch_id} not found"}
    assert absent.json() == {"detail": "Batch job batch_000000000000 not found"}


# --- state does not leak between apps ---------------------------------------


def test_two_apps_in_one_process_do_not_share_batches(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Batch state was a module-level dict, so every app in the process shared it.

    A correctness bug on its own, and the specific blocker
    specs/scheduler-persistence.md recorded against persisting batches.
    """
    private_key, public_pem = key_pair
    auth = bearer(private_key, "tenant-a")

    first = create_app()
    first.state.jwt_public_key = public_pem
    second = create_app()
    second.state.jwt_public_key = public_pem

    batch_id = TestClient(first).post("/v1/batch", json=PAYLOAD, headers=auth).json()["batch_id"]
    response = TestClient(second).get(f"/v1/batch/{batch_id}", headers=auth)

    assert response.status_code == 404


# --- the 422-instead-of-401 wart, which batch inherited ---------------------


def test_a_missing_authorization_header_is_401_on_chat_completions(
    client: TestClient,
) -> None:
    """`Header(...)` made FastAPI reject the request before `verify_jwt` ran.

    The result was 422 for "no credential", on the gateway's main route. Fixed here
    because 2.4's own rejection test would otherwise have to assert the wrong status.
    """
    response = client.post(
        "/v1/chat/completions",
        json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 401
