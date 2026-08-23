"""Shared pytest fixtures for the Node test suite."""

from collections.abc import Iterator

import pytest

from node.api.auth import verify_node_auth
from node.core.completion_cache import CompletionCache
from node.main import app


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "real_auth: exercise the genuine node auth dependency instead of bypassing it",
    )


@pytest.fixture(autouse=True)
def fresh_completion_cache() -> Iterator[None]:
    """Give every test a clean /infer memo.

    The route dependency attaches its CompletionCache to the module-level
    `app` object, where it persists across tests -- without this, one test's
    successful generation of a prompt reaches the next test as an already-
    answered hit and the mocked failure never runs.
    """
    app.state.completion_cache = CompletionCache()
    yield


@pytest.fixture(autouse=True)
def bypass_node_auth(request: pytest.FixtureRequest) -> Iterator[None]:
    """Satisfy the node auth dependency for tests that are not about auth.

    Every route on the Node now requires `X-Network-Auth-Token`. Tests covering
    inference, telemetry, and sandbox behaviour should not each have to carry a
    credential -- that would test the auth layer repeatedly and obscure what they
    are actually asserting.

    Modules that *do* test authentication opt out with
    `pytestmark = pytest.mark.real_auth`, so the real dependency runs and the
    fail-closed behaviour stays pinned by `test_control_api_auth.py`.

    The override is popped rather than cleared so this never discards overrides
    installed by another fixture.
    """
    if request.node.get_closest_marker("real_auth"):
        yield
        return

    app.dependency_overrides[verify_node_auth] = lambda: None
    try:
        yield
    finally:
        app.dependency_overrides.pop(verify_node_auth, None)
