"""Integration tests for the edge ingress gateway and rate-limiting.

The submit endpoint refuses honestly with 501 Not Implemented -- there is no
execution machinery behind it, and it used to answer "scheduled" for work that
would never run. Authentication and rate limiting are real, and those are what
these tests pin.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.core.rate_limiter import TokenBucketLimiter
from scheduler.main import app


@pytest.fixture(scope="module")
def key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    """Generate an RSA key pair for signing and verifying JWTs in tests."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_key, public_key_pem


@pytest.fixture(autouse=True)
def setup_test_app(key_pair: tuple[rsa.RSAPrivateKey, str]) -> None:
    """Configure the FastAPI app state with test keys and a fresh rate limiter."""
    _, public_key_pem = key_pair
    app.state.jwt_public_key = public_key_pem

    # Reset rate limiter
    app.state.rate_limiter = TokenBucketLimiter(capacity=5, refill_rate=0.5)

    # Reset registry state the gateway could observe.
    app.state.registry._nodes.clear()
    app.state.registry._heartbeats.clear()
    app.state.registry._telemetry.clear()


def generate_token(
    private_key: rsa.RSAPrivateKey, tenant_id: str | None, expired: bool = False
) -> str:
    """Generate a signed JWT for testing."""
    payload = {
        "sub": "client-user",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=10)
        if not expired
        else datetime.now(UTC) - timedelta(minutes=10),
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id

    return jwt.encode(payload, private_key, algorithm="RS256")


def test_ingress_submit_invalid_auth(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Verify that requests with invalid authentication are rejected with 401."""
    client = TestClient(app)
    task_payload = {"task_id": "task-1", "action": "test_action", "data": {}}

    # 1. No Authorization Header
    response = client.post("/api/v1/tasks/submit", json=task_payload)
    assert response.status_code == 422 or response.status_code == 401

    # 2. Malformed Header format
    response = client.post(
        "/api/v1/tasks/submit",
        json=task_payload,
        headers={"Authorization": "BearerInvalidToken"},
    )
    assert response.status_code == 401
    assert "Invalid Authorization header format" in response.json()["detail"]

    # 3. Invalid signature (signed with different key)
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    invalid_token = generate_token(other_private_key, tenant_id="tenant-A")
    response = client.post(
        "/api/v1/tasks/submit",
        json=task_payload,
        headers={"Authorization": f"Bearer {invalid_token}"},
    )
    assert response.status_code == 401
    assert "JWT signature verification failed" in response.json()["detail"]

    # 4. Token missing tenant_id claim
    private_key, _ = key_pair
    no_tenant_token = generate_token(private_key, tenant_id=None)
    response = client.post(
        "/api/v1/tasks/submit",
        json=task_payload,
        headers={"Authorization": f"Bearer {no_tenant_token}"},
    )
    assert response.status_code == 401
    assert "Missing 'tenant_id'" in response.json()["detail"]


def test_ingress_submit_rejects_a_token_without_exp(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """A JWT with no `exp` claim must be refused: it would never expire.

    JWTs are stateless and there is no revocation -- the ONLY bound on an issued
    credential is its `exp` claim (see `credential_max_ttl_hours` in config). A
    token minted without one is valid until the signing key is rotated, so
    verification has to REQUIRE the claim rather than merely honour it when it
    happens to be present. `scripts/mint_token.py` always sets `exp`; this holds
    the hand-minted case to the same rule.
    """
    private_key, _ = key_pair
    no_exp_token = jwt.encode(
        {"sub": "client-user", "tenant_id": "tenant-A", "iat": datetime.now(UTC)},
        private_key,
        algorithm="RS256",
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/tasks/submit",
        json={"task_id": "task-1", "action": "noop", "data": {}},
        headers={"Authorization": f"Bearer {no_exp_token}"},
    )

    assert response.status_code == 401
    assert "exp" in response.json()["detail"]


def test_ingress_submit_authorized_handoff(
    key_pair: tuple[rsa.RSAPrivateKey, str], setup_test_app: None
) -> None:
    """An authorised request is refused honestly with 501, not faked.

    This endpoint used to answer `{"status": "scheduled", "node_id", "tx_hash"}`
    after selecting a node -- and nothing ever executed the task: no store, no
    queue, no consumer. A placeholder answered as success is the N1 failure, so
    the endpoint now refuses with 501 Not Implemented and a body that makes no
    claim about work that will not happen. The rewrite of the old success-shape
    assertions is deliberate: the old shape was the defect.
    """
    private_key, _ = key_pair
    token = generate_token(private_key, tenant_id="tenant-A")

    client = TestClient(app)
    task_payload = {
        "task_id": "task-abc",
        "action": "replicate_model",
        "data": {"model_name": "llama3"},
    }

    response = client.post(
        "/api/v1/tasks/submit",
        json=task_payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 501
    res_json = response.json()
    # The body makes no scheduling claims: nothing was scheduled, so nothing may
    # say it was.
    assert "scheduled" not in res_json
    assert "tx_hash" not in res_json
    assert "node_id" not in res_json
    assert "not implemented" in res_json["detail"]

    # And the registry was not touched: no node was "selected" for a task that
    # will not run.
    assert not app.state.registry._nodes


def test_ingress_token_bucket_rate_limiter(
    key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    """Verify rate-limiting triggers HTTP 429 when burst capacity is exceeded.

    Allowed requests now answer 501 (the honest refusal) rather than 200; the
    limiter still counts each one, so exhaustion and tenant isolation behave
    exactly as before.
    """
    private_key, _ = key_pair
    client = TestClient(app)
    token_a = generate_token(private_key, tenant_id="tenant-A")
    token_b = generate_token(private_key, tenant_id="tenant-B")

    task_payload = {"task_id": "task-1", "action": "test_action", "data": {}}

    # Flood tenant-A (burst capacity = 5). Each allowed request is refused with
    # 501 -- refused is not unaccounted.
    for i in range(5):
        response = client.post(
            "/api/v1/tasks/submit",
            json=task_payload,
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert response.status_code == 501, f"Request {i + 1} was not honestly refused"

    # 6th request from tenant-A should trigger rate limit (429)
    response_429 = client.post(
        "/api/v1/tasks/submit",
        json=task_payload,
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response_429.status_code == 429
    assert "Rate limit exceeded" in response_429.json()["detail"]

    # Verify multi-tenant isolation: tenant-B is not affected by tenant-A's exhaust
    response_b = client.post(
        "/api/v1/tasks/submit",
        json=task_payload,
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response_b.status_code == 501
