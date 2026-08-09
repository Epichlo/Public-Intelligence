"""A developer can obtain a credential, and only the operator can issue one (3.1).

Until now the gateway verified RS256 JWTs that nobody could get: `mint_token.py` reads
a private key off the operator's disk, so there were no requesters, only the person
running the Scheduler. This is the walkthrough step ROADMAP's definition of done calls
"a developer on a different network, with a credential they obtained themselves".

The two tests that matter most here are the negative ones. An issuance endpoint is a
key-minting oracle, so what guards it and what it refuses to sign are the whole
security story.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.core.config import Settings, get_settings
from scheduler.main import create_app

TOKEN = "operator-fleet-token"


@pytest.fixture
def keys(tmp_path: Path) -> tuple[Path, str]:
    """A private key on disk and its public PEM, as a real deployment has."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path = tmp_path / "jwt_private.pem"
    key_path.write_bytes(
        private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return key_path, public_pem


@pytest.fixture
def client(keys: tuple[Path, str], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    key_path, public_pem = keys
    app = create_app(jwt_public_key=public_pem)

    settings = Settings(
        network_auth_token=TOKEN,
        jwt_private_key_path=str(key_path),
        credential_max_ttl_hours=720,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr("scheduler.api.credentials.get_settings", lambda: settings)
    return TestClient(app)


def _issue(client: TestClient, **body: Any) -> Any:
    payload = {"tenant_id": "acme"}
    payload.update(body)
    return client.post("/v1/credentials", json=payload, headers={"X-Network-Auth-Token": TOKEN})


# --- who may issue ---------------------------------------------------------


def test_issuing_without_the_operator_credential_is_refused(client: TestClient) -> None:
    """The most important test in this file.

    An unguarded issuance endpoint is a public key-minting oracle: anyone who could
    reach it could mint a token for any tenant and use the gateway for free, read
    another tenant's batches, and bypass the rate limit by rotating tenant ids.
    """
    assert client.post("/v1/credentials", json={"tenant_id": "acme"}).status_code == 401


def test_a_requester_jwt_cannot_mint_more_credentials(
    client: TestClient, keys: tuple[Path, str]
) -> None:
    """Guarded by the FLEET token, not by a JWT, and this is why.

    If a valid requester JWT were sufficient, any credential holder could mint
    tokens for any other tenant -- privilege escalation dressed as a feature. A
    Bearer header must not satisfy this route at all.
    """
    issued = _issue(client).json()["token"]
    response = client.post(
        "/v1/credentials",
        json={"tenant_id": "someone-else"},
        headers={"Authorization": f"Bearer {issued}"},
    )
    assert response.status_code == 401


# --- what it issues --------------------------------------------------------


def test_an_issued_credential_is_accepted_by_the_gateway(client: TestClient) -> None:
    """End to end, and the only assertion that proves 3.1 actually closed the gap.

    A token this endpoint mints but the gateway rejects would be worse than no
    endpoint. 503 is the pass condition: authentication succeeded and there is no
    node registered to dispatch to.
    """
    response = _issue(client)
    assert response.status_code == 201, response.text
    token = response.json()["token"]

    completion = client.post(
        "/v1/chat/completions",
        json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert completion.status_code == 503, completion.text


def test_the_issued_token_carries_the_tenant_claim_the_gateway_requires(
    client: TestClient, keys: tuple[Path, str]
) -> None:
    """`verify_jwt` refuses a token with no `tenant_id`.

    Issuing one the gateway would reject is the most obvious failure this endpoint
    could have, so it is asserted on the decoded claims rather than inferred from the
    end-to-end test above.
    """
    _, public_pem = keys
    token = _issue(client, tenant_id="acme", subject="dev-1").json()["token"]

    claims = jwt.decode(token, public_pem, algorithms=["RS256"])
    assert claims["tenant_id"] == "acme"
    assert claims["sub"] == "dev-1"
    assert claims["exp"] > datetime.now(UTC).timestamp()


def test_the_token_carries_a_kid_so_rotation_works(
    client: TestClient, keys: tuple[Path, str]
) -> None:
    """ROADMAP C4 gave the verifier two keys; issuance has to name which one it used."""
    token = _issue(client).json()["token"]
    assert jwt.get_unverified_header(token)["kid"] == "primary"


def test_an_excessive_lifetime_is_capped_not_honoured(client: TestClient) -> None:
    """The only bound on an issued credential, because there is no revocation.

    Capped rather than rejected: an operator asking for a year gets the maximum, and
    a client that sends a bigger number cannot argue its way into a longer token.
    """
    token = _issue(client, ttl_hours=24 * 365 * 10).json()["token"]
    claims = jwt.decode(token, options={"verify_signature": False})

    lifetime_hours = (claims["exp"] - claims["iat"]) / 3600
    assert lifetime_hours <= 720 + 1


def test_unknown_fields_are_refused_rather_than_ignored(client: TestClient) -> None:
    """`extra="forbid"`. A typo'd field name must not silently issue a default token.

    `tenat_id="acme"` would otherwise mint a credential for the tenant literally
    named by the *missing* required field -- or be rejected for a confusing reason.
    """
    response = client.post(
        "/v1/credentials",
        json={"tenant_id": "acme", "admin": True},
        headers={"X-Network-Auth-Token": TOKEN},
    )
    assert response.status_code == 422


# --- when it cannot -------------------------------------------------------


def test_no_signing_key_configured_answers_503_and_says_what_to_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """503, not 500, and the message names the setting and the command.

    An operator hitting this has a configuration problem, and the error is the only
    place they will look.
    """
    app = create_app()
    settings = Settings(network_auth_token=TOKEN, jwt_private_key_path=None)
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr("scheduler.api.credentials.get_settings", lambda: settings)

    response = TestClient(app).post(
        "/v1/credentials", json={"tenant_id": "acme"}, headers={"X-Network-Auth-Token": TOKEN}
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "SCHEDULER_JWT_PRIVATE_KEY_PATH" in detail
    assert "--generate-keypair" in detail


def test_an_unreadable_key_does_not_leak_its_path_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed key file must produce a 503 that carries no key material."""
    bad = tmp_path / "not-a-key.pem"
    bad.write_text("-----BEGIN PRIVATE KEY-----\nnonsense\n-----END PRIVATE KEY-----\n")

    app = create_app()
    settings = Settings(network_auth_token=TOKEN, jwt_private_key_path=str(bad))
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr("scheduler.api.credentials.get_settings", lambda: settings)

    response = TestClient(app).post(
        "/v1/credentials", json={"tenant_id": "acme"}, headers={"X-Network-Auth-Token": TOKEN}
    )

    assert response.status_code == 503
    assert "nonsense" not in response.text
    assert "BEGIN PRIVATE KEY" not in response.text
