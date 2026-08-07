"""Signing keys must rotate, and an unconfigured Scheduler must fail closed (C4).

Two things were wrong, and the second is worse than the roadmap line said.

**One key, no rotation.** Replacing the signing key invalidated every live token at
once, so rotation was an outage. Issued tokens now carry a `kid` header and the
Scheduler accepts **two** active keys, which makes rotation a sequence with no
window where valid tokens are refused: add the new key as secondary, start signing
with it, retire the old one when the last token minted under it has expired.

**A hardcoded fallback public key.** `ingress.py:16` held an RSA public key literal,
used whenever neither `app.state.jwt_public_key` nor `$JWT_PUBLIC_KEY` was set. It is
listed in `VERIFY.md` step 3 as a known unfixed issue.

Its danger was misjudged as low on the grounds that the matching private key is not
in this repository, so nobody can mint a token it accepts. That is true and it is not
the point: **the key came from somewhere.** It is a "standard dummy" PEM of the kind
that circulates in tutorials and sample projects, and whoever generated it may still
have the private half. A verifier that trusts a key with unknown provenance is not
"probably fine"; it is an authentication decision nobody made.

The fix is to fail closed. No configured key means 401 for every request and a loud
startup error -- an unconfigured gateway should refuse everyone, not accept whoever
holds a key that shipped with the source.
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


def _keypair() -> tuple[rsa.RSAPrivateKey, str]:
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


def _token(private: rsa.RSAPrivateKey, kid: str | None = None, tenant: str = "tenant-a") -> str:
    headers: dict[str, Any] = {"kid": kid} if kid else {}
    return jwt.encode(
        {
            "sub": "u",
            "tenant_id": tenant,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        private,
        algorithm="RS256",
        headers=headers,
    )


def _client(**state: Any) -> TestClient:
    app = create_app()
    for key, value in state.items():
        setattr(app.state, key, value)
    return TestClient(app)


def _call(client: TestClient, token: str) -> int:
    return client.post(
        "/v1/chat/completions",
        json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {token}"},
    ).status_code


# --- failing closed --------------------------------------------------------


def test_an_unconfigured_gateway_refuses_everyone(monkeypatch: pytest.MonkeyPatch) -> None:
    """No key configured must mean 401, not "try the key that shipped with the source"."""
    monkeypatch.delenv("JWT_PUBLIC_KEY", raising=False)
    private, _ = _keypair()
    client = _client(jwt_public_key=None)

    assert _call(client, _token(private)) == 401


def test_no_public_key_literal_survives_in_the_source() -> None:
    """The hardcoded PEM must be gone, not merely unreferenced.

    Asserted on the file rather than on behaviour because a literal left in place
    is one `getattr` default away from being live again -- which is exactly how it
    was reachable in the first place.
    """
    from pathlib import Path

    import scheduler

    source_root = Path(scheduler.__file__).parent
    offenders = [
        str(path.relative_to(source_root))
        for path in source_root.rglob("*.py")
        if "BEGIN PUBLIC KEY" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"an embedded public key is back in {offenders}"


# --- rotation --------------------------------------------------------------


def test_a_token_signed_by_the_primary_key_is_accepted() -> None:
    private, public = _keypair()
    client = _client(jwt_public_key=public)
    # 503, not 401: authentication passed and there is no node to dispatch to.
    assert _call(client, _token(private)) == 503


def test_a_token_signed_by_the_secondary_key_is_also_accepted() -> None:
    """The whole point of C4: two keys valid at once, so rotation is not an outage."""
    old_private, old_public = _keypair()
    new_private, new_public = _keypair()

    client = _client(jwt_public_key=new_public, jwt_public_key_secondary=old_public)

    assert _call(client, _token(new_private)) == 503, "new key must work"
    assert _call(client, _token(old_private)) == 503, "old key must still work during rotation"


def test_a_token_signed_by_a_retired_key_is_refused() -> None:
    """Retiring a key has to actually retire it."""
    retired_private, _ = _keypair()
    _, current_public = _keypair()

    client = _client(jwt_public_key=current_public, jwt_public_key_secondary=None)
    assert _call(client, _token(retired_private)) == 401


def test_an_unknown_kid_does_not_bypass_verification() -> None:
    """`kid` is a hint for key selection, never an assertion of validity.

    The classic failure is treating an unrecognised `kid` as "no key matched, so
    skip the check" or as a lookup that returns None and is then not verified
    against. A token whose kid names nothing must be refused on its signature.
    """
    attacker_private, _ = _keypair()
    _, real_public = _keypair()

    client = _client(jwt_public_key=real_public)
    assert _call(client, _token(attacker_private, kid="not-a-real-kid")) == 401


def test_a_kid_naming_the_secondary_key_selects_it() -> None:
    """A correct kid must reach the right key rather than relying on try-both luck."""
    old_private, old_public = _keypair()
    _, new_public = _keypair()

    client = _client(
        jwt_public_key=new_public,
        jwt_public_key_secondary=old_public,
    )
    assert _call(client, _token(old_private, kid="secondary")) == 503


def test_the_algorithm_is_pinned_to_rs256() -> None:
    """An unsigned `alg: none` token must never be accepted.

    Included because this is the single most common JWT verification bug and the
    key-selection rewrite in this change touches exactly the code that prevents it.
    """
    _, public = _keypair()
    client = _client(jwt_public_key=public)

    unsigned = jwt.encode(
        {"sub": "u", "tenant_id": "tenant-a", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        key="",
        algorithm="none",
    )
    assert _call(client, unsigned) == 401
