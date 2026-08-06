"""The Scheduler must not hand its responses to any origin that asks (ROADMAP 2.3).

Every assertion here reads the **actual response header**, never the settings
object. The bug being fixed is precisely a config that reads as restrictive and
behaves permissively: `allow_origins=["*"]` with `allow_credentials=True` does not
send `*` — Starlette reflects the caller's own Origin back and sets
`access-control-allow-credentials: true`. Asserting on config would have passed
against that.

See specs/close-the-open-http-surface.md.
"""

import pytest
from fastapi.testclient import TestClient

from scheduler.core.config import Settings
from scheduler.main import create_app

HOSTILE = "https://evil.example"
FRIENDLY = "https://dashboard.public-intelligence.net"


def cors_headers(client: TestClient, origin: str) -> dict[str, str]:
    """Return only the CORS headers a simple cross-origin GET comes back with."""
    response = client.get("/health", headers={"Origin": origin})
    return {k.lower(): v for k, v in response.headers.items() if k.lower().startswith("access-")}


def preflight_headers(client: TestClient, origin: str) -> dict[str, str]:
    """Return the CORS headers a preflight comes back with."""
    response = client.options(
        "/v1/chat/completions",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    return {k.lower(): v for k, v in response.headers.items() if k.lower().startswith("access-")}


def build(origins: list[str] | None = None) -> TestClient:
    """An app whose CORS policy is passed in explicitly.

    Injected rather than read from settings inside `create_app`, for the same reason
    the durable store is (ROADMAP 2.1): middleware is built at app-construction
    time, so a `dependency_overrides` entry would arrive too late to affect it, and
    reading the environment there would let an ambient `.env` change what the suite
    is testing.
    """
    return TestClient(create_app(cors_origins=origins))


# --- closed by default ------------------------------------------------------


def test_no_configured_origin_means_no_cors_headers_at_all() -> None:
    """The default must not let a page read the response.

    Every browser call in packages/website goes to a same-origin Next.js `/api/...`
    route which reaches the services server-side, so nothing legitimate makes a
    cross-origin request. Closed is therefore the correct default, not a trade-off.
    """
    client = build()

    assert cors_headers(client, HOSTILE) == {}


def test_a_hostile_origin_is_never_reflected() -> None:
    """The exact defect: reflecting whatever Origin the caller sent.

    A page could preflight, send `Authorization`, and READ the reply. The request
    would still be sent without these headers -- what they change is whether the
    page gets to see the answer.
    """
    client = build()

    assert "access-control-allow-origin" not in preflight_headers(client, HOSTILE)


def test_credentials_are_not_offered_by_default() -> None:
    """`allow-credentials: true` alongside a reflected origin is the whole bug."""
    client = build()

    assert "access-control-allow-credentials" not in cors_headers(client, HOSTILE)


# --- open only to what an operator named ------------------------------------


def test_a_configured_origin_is_allowed() -> None:
    """Configuring an origin has to actually work, or operators will re-add `*`."""
    client = build([FRIENDLY])

    assert cors_headers(client, FRIENDLY).get("access-control-allow-origin") == FRIENDLY


def test_an_unconfigured_origin_is_still_refused_when_a_list_exists() -> None:
    """An allowlist that allows everything is not an allowlist."""
    client = build([FRIENDLY])

    assert cors_headers(client, HOSTILE).get("access-control-allow-origin") != HOSTILE


def test_the_wildcard_is_never_sent_as_an_origin() -> None:
    """`*` is not a valid answer in any configuration this service supports."""
    for origins in ([], [FRIENDLY]):
        client = build(origins)
        for origin in (HOSTILE, FRIENDLY):
            assert cors_headers(client, origin).get("access-control-allow-origin") != "*"


def test_a_configured_origin_gets_an_explicit_header_allowlist() -> None:
    """`allow_headers=["*"]` accepted any header a page cared to send. Name them.

    Asserted by requesting a header that is NOT on the list and expecting the
    preflight to be refused. Reading `access-control-allow-headers` off an allowed
    preflight cannot tell the two configurations apart: with an explicit list
    Starlette returns the list, and with `*` it echoes whatever was asked for, so
    both come back looking reasonable. Verified by mutation -- an earlier version of
    this test asserted on that header and passed with `allow_headers=["*"]` put back.
    """
    client = build([FRIENDLY])

    allowed = client.options(
        "/v1/chat/completions",
        headers={
            "Origin": FRIENDLY,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    refused = client.options(
        "/v1/chat/completions",
        headers={
            "Origin": FRIENDLY,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-not-on-the-allowlist",
        },
    )

    assert allowed.status_code == 200
    assert refused.status_code == 400, "an unlisted header must not be waved through"


# --- the trap the fix exists to remove --------------------------------------


def test_a_wildcard_origin_is_rejected_at_startup() -> None:
    """An operator setting `SCHEDULER_CORS_ALLOW_ORIGINS=*` must not silently
    reinstate reflected-origin credentials. Failing at boot with a reason beats
    a service that looks configured and answers every origin.
    """
    with pytest.raises(ValueError, match="reflect"):
        Settings(cors_allow_origins=["*"])


def test_the_starlette_behaviour_this_fix_assumes_is_still_true() -> None:
    """Pins the measurement the spec's reasoning rests on.

    Starlette reflects the Origin rather than sending `*` when credentials are
    enabled. If a future Starlette changed that, the spec's argument would be stale
    prose; this fails the suite instead.
    """
    from starlette.applications import Starlette
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    legacy = Starlette(routes=[Route("/x", lambda r: PlainTextResponse("ok"))])
    legacy.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    response = TestClient(legacy).get("/x", headers={"Origin": HOSTILE})

    assert response.headers["access-control-allow-origin"] == HOSTILE
    assert response.headers["access-control-allow-credentials"] == "true"
