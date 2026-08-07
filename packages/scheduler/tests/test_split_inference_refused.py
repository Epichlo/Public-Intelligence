"""Split inference is refused, not simulated (ROADMAP N1).

Before this, a valid JWT plus `x-split-inference: true` returned **HTTP 200** with
`content: 'token_556'` for "What is the capital of France?" -- in the standard
OpenAI response shape, so every compatible client would show it to a user as the
model's answer. The content came from `LocalBoundaryEngine`, seeded `random.gauss`
matrices over a toy vocabulary.

No test could have caught that. The suite asserted the split path returned
*something*; nothing asserted that what it returned was real.

See specs/stop-returning-fabricated-completions.md.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from scheduler.main import create_app

PROMPT: dict[str, Any] = {
    "model": "llama3",
    "messages": [{"role": "user", "content": "What is the capital of France?"}],
}


@pytest.fixture(scope="module")
def key_pair() -> tuple[rsa.RSAPrivateKey, str]:
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
    _, public_pem = key_pair
    app = create_app()
    app.state.jwt_public_key = public_pem
    return TestClient(app)


@pytest.fixture
def auth(key_pair: tuple[rsa.RSAPrivateKey, str]) -> dict[str, str]:
    private_key, _ = key_pair
    token = jwt.encode(
        {"tenant_id": "any-tenant", "exp": datetime.now(UTC) + timedelta(hours=1)},
        private_key,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


# --- the three ways in ------------------------------------------------------


def test_the_header_is_refused_not_simulated(client: TestClient, auth: dict[str, str]) -> None:
    """The exact request that returned `token_556`."""
    response = client.post(
        "/v1/chat/completions", json=PROMPT, headers={**auth, "x-split-inference": "true"}
    )

    assert response.status_code == 501
    assert "split" in response.json()["detail"].lower()


def test_the_body_flag_is_refused(client: TestClient, auth: dict[str, str]) -> None:
    """`split_inference` stays in the request model on purpose.

    Removing the field would make this a 422 -- "malformed" -- when the honest
    answer is "understood, not available".
    """
    response = client.post(
        "/v1/chat/completions", json={**PROMPT, "split_inference": True}, headers=auth
    )

    assert response.status_code == 501


def test_the_settings_trigger_was_always_dead() -> None:
    """FINDING, not a feature: `enable_split_inference` is not a setting.

    The original guard read
    `getattr(get_settings(), "enable_split_inference", False)` as a third way to
    turn split inference on. `Settings` has no such field and never did, so that
    branch was permanently False -- an operator who set
    `SCHEDULER_ENABLE_SPLIT_INFERENCE` got nothing, silently.

    The spec for this change initially claimed the flag "keeps working, as a way to
    get 501s". That was wrong and is corrected there. The `getattr` is kept in the
    guard so that if anyone ever adds the field it refuses rather than fabricates.
    """
    from scheduler.core.config import Settings

    assert "enable_split_inference" not in Settings.model_fields


# --- the simulation is unreachable ------------------------------------------


def test_the_gateway_no_longer_reaches_the_simulation() -> None:
    """`openai.py` must not be able to construct a `LocalBoundaryEngine` at all.

    Asserted on the source rather than on a response, because a response test can
    only prove the paths it thought to try. This proves the wiring is gone.
    """
    source = Path(__file__).resolve().parents[1] / "src" / "scheduler" / "api" / "openai.py"
    code = [
        line
        for line in source.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]

    # Matches USE, not mention: the file explains this history in a comment that
    # names the class, and forbidding the name would delete the explanation. Same
    # reasoning as the archived-repo check in tests/test_installer_paths.py.
    assert not [line for line in code if "LocalBoundaryEngine" in line]
    assert not [line for line in code if "boundary_engine" in line]


def test_no_response_can_carry_the_simulations_token_prefix(
    client: TestClient, auth: dict[str, str]
) -> None:
    """`token_<n>` is what the simulation's detokeniser emits.

    Belt and braces against the header path being reinstated: if any of these
    requests ever answers 200 with that prefix in it, the fabrication is back.
    """
    attempts = [
        client.post(
            "/v1/chat/completions", json=PROMPT, headers={**auth, "x-split-inference": "true"}
        ),
        client.post("/v1/chat/completions", json={**PROMPT, "split_inference": True}, headers=auth),
    ]

    for response in attempts:
        assert response.status_code == 501
        assert "token_" not in response.text


# --- ordinary requests are untouched ----------------------------------------


def test_an_ordinary_request_is_unaffected(client: TestClient, auth: dict[str, str]) -> None:
    """No node is registered, so the honest answer is 503 -- not 501, and not 200.

    The distinction is the whole point: "nobody can serve this right now" and
    "this feature does not exist" are different answers, and neither is a made-up
    completion.
    """
    response = client.post("/v1/chat/completions", json=PROMPT, headers=auth)

    assert response.status_code == 503
    assert response.status_code != 501
