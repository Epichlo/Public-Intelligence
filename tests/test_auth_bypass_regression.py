"""Regression tests proving the `dev_*` bearer token auth bypass is gone.

Until 2026-08-02 `verify_jwt` short-circuited on any token starting with `dev_`
(plus the literals `dev`, `local`, `test`) and returned `tenant-dev` claims
without verifying a signature. The website proxy sent `Bearer dev_token` by
default, so every unauthenticated caller was authenticated.

These tests fail if that branch -- or any equivalent -- is reintroduced.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.main import app

# Tokens the removed branch accepted. Every one must now be rejected.
BYPASS_TOKENS = [
    "dev_token",
    "dev_anything",
    "dev_",
    "dev_admin_override",
    "dev",
    "local",
    "test",
]

# Both routers depend on `verify_jwt`, so both must reject.
PROTECTED_ENDPOINTS = [
    ("/api/v1/tasks/submit", {"task_id": "t-1", "action": "noop", "data": {}}),
    (
        "/v1/chat/completions",
        {"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
    ),
]


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
def configure_app(key_pair: tuple[rsa.RSAPrivateKey, str]) -> None:
    """Point the app at the test public key so real verification can succeed."""
    _, public_key_pem = key_pair
    app.state.jwt_public_key = public_key_pem


def sign(private_key: rsa.RSAPrivateKey, tenant_id: str = "tenant-a") -> str:
    """Mint a validly signed RS256 token carrying a tenant claim."""
    return jwt.encode(
        {
            "sub": "client-user",
            "tenant_id": tenant_id,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        private_key,
        algorithm="RS256",
    )


@pytest.mark.parametrize("token", BYPASS_TOKENS)
@pytest.mark.parametrize(("path", "payload"), PROTECTED_ENDPOINTS)
def test_dev_bypass_tokens_are_rejected(token: str, path: str, payload: dict[str, object]) -> None:
    """Every token the old bypass accepted must now fail signature verification."""
    client = TestClient(app)
    response = client.post(path, json=payload, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401, (
        f"AUTH BYPASS: {path} accepted unsigned token {token!r} with status {response.status_code}"
    )

    # The response must not carry the bypass principal.
    body = response.text
    assert "tenant-dev" not in body
    assert "dev_user" not in body


def test_bypass_principal_is_absent_from_source() -> None:
    """The literal bypass branch must not exist in the shipped source."""
    from pathlib import Path

    import scheduler

    src_root = Path(scheduler.__file__).resolve().parent
    offenders = [
        f"{path.name}:{num}: {line.strip()}"
        for path in src_root.rglob("*.py")
        for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if "tenant-dev" in line or "dev_token" in line
    ]
    assert not offenders, "bypass literals still present in source: " + "; ".join(offenders)


@pytest.mark.parametrize(("path", "payload"), PROTECTED_ENDPOINTS)
def test_validly_signed_token_is_not_rejected(
    key_pair: tuple[rsa.RSAPrivateKey, str],
    path: str,
    payload: dict[str, object],
) -> None:
    """Positive control: real RS256 tokens still authenticate.

    Guards against 'fixing' the bypass by breaking authentication outright. The
    request may still fail downstream (no compute nodes registered), so this
    asserts only that it is not an auth rejection.
    """
    private_key, _ = key_pair
    client = TestClient(app)
    response = client.post(
        path, json=payload, headers={"Authorization": f"Bearer {sign(private_key)}"}
    )

    assert response.status_code != 401, (
        f"validly signed token was rejected at {path}: {response.text[:200]}"
    )


def test_missing_authorization_header_is_not_authenticated() -> None:
    """A request with no Authorization header must never reach a handler."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/tasks/submit", json={"task_id": "t-1", "action": "noop", "data": {}}
    )
    assert response.status_code in (401, 422)
    assert "tenant-dev" not in response.text
