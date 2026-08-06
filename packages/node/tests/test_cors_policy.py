"""The Node must not hand its responses to any origin that asks (ROADMAP 2.3).

Same defect as the Scheduler's, and it matters more here: a Node runs on a host's
own machine, usually on localhost, so a reflected-origin policy makes it readable
from any page that host visits in a browser.

See specs/close-the-open-http-surface.md.
"""

import pytest
from fastapi.testclient import TestClient

from node.core.configuration import Settings
from node.main import create_app

HOSTILE = "https://evil.example"
FRIENDLY = "http://localhost:3000"


def cors_headers(client: TestClient, origin: str) -> dict[str, str]:
    """Return only the CORS headers a simple cross-origin GET comes back with."""
    response = client.get("/health", headers={"Origin": origin})
    return {k.lower(): v for k, v in response.headers.items() if k.lower().startswith("access-")}


def build(origins: list[str] | None = None) -> TestClient:
    """A node app whose CORS policy is passed in explicitly.

    `raise_server_exceptions=False` and no `with` block: the lifespan starts the
    whole Runtime, which is not what this file is testing.
    """
    return TestClient(create_app(cors_origins=origins))


def test_no_configured_origin_means_no_cors_headers_at_all() -> None:
    """Closed by default. The dashboard reaches this through a server-side proxy."""
    assert cors_headers(build(), HOSTILE) == {}


def test_a_hostile_origin_is_never_reflected() -> None:
    """`allow_origins=["*"]` with credentials reflects the caller's Origin back."""
    assert cors_headers(build(), HOSTILE).get("access-control-allow-origin") != HOSTILE


def test_credentials_are_not_offered_by_default() -> None:
    """No `allow-credentials: true` unless an operator named the origins."""
    assert "access-control-allow-credentials" not in cors_headers(build(), HOSTILE)


def test_a_configured_origin_is_allowed() -> None:
    """A host running their own browser UI on localhost can opt in."""
    assert cors_headers(build([FRIENDLY]), FRIENDLY).get("access-control-allow-origin") == FRIENDLY


def test_an_unconfigured_origin_is_still_refused_when_a_list_exists() -> None:
    """Opting one origin in must not open the door to all of them."""
    assert cors_headers(build([FRIENDLY]), HOSTILE).get("access-control-allow-origin") != HOSTILE


def test_the_wildcard_is_never_sent_as_an_origin() -> None:
    """`*` is not a valid answer in any configuration this service supports."""
    for origins in ([], [FRIENDLY]):
        for origin in (HOSTILE, FRIENDLY):
            assert cors_headers(build(origins), origin).get("access-control-allow-origin") != "*"


def test_a_wildcard_origin_is_rejected_at_startup() -> None:
    """`NODE_CORS_ALLOW_ORIGINS=*` must not silently reinstate the defect."""
    with pytest.raises(ValueError, match="reflect"):
        Settings(cors_allow_origins=["*"])
