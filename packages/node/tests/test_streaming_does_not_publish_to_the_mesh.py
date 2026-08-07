"""A streamed completion must not be republished onto the Zenoh mesh.

Found while doing ROADMAP C2. `node/api/inference.py` built a
`BackpressuredStreamRouter` for **every** streaming request whenever the node had a
live Zenoh session, and that router calls `publisher.put(chunk)` for each chunk onto
`public-intelligence/net/transport/stream/{session_id}` -- **in plaintext, on the
shared mesh, with no subscriber anywhere in this codebase.**

Two things make it worse than "unused code that happens to run":

1. ROADMAP 2.7 spent an entire protocol change AES-256-GCM enveloping *telemetry*
   -- CPU percentages and VRAM figures -- on this same mesh, because it was
   forgeable and readable. The actual generated text was going out beside it in the
   clear the whole time, to a key any peer can subscribe to with a `**` wildcard.
2. The route yielded `session_id: <id>` as the first line of the SSE body, which
   both corrupts the stream for any OpenAI-compatible client and hands the caller
   the mesh topic to subscribe to.

It is leftover split-inference plumbing. Split inference is cut from v1 and the
gateway answers 501 for it (ROADMAP N1), so this path exists to serve a feature the
product does not have.

These tests pin the fix at the level that matters -- what leaves the process -- not
at the level of which import statement is present.
"""

from collections.abc import AsyncGenerator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from node.api.inference import get_ollama_client
from node.main import app

SECRET = "the capital of France is Paris"


class _RecordingPublisher:
    """Stands in for `zenoh.Publisher`, recording everything put on the wire."""

    def __init__(self, key: str, sink: list[tuple[str, bytes]]) -> None:
        self.key = key
        self._sink = sink

    def put(self, payload: bytes, **kwargs: Any) -> None:
        self._sink.append((self.key, bytes(payload)))

    def undeclare(self) -> None:
        pass


class _RecordingSession:
    """A Zenoh session that looks real to the route and records every publication.

    The route skips its mesh path when `"mock" in type(session).__name__.lower()`,
    so this class is deliberately NOT named with "mock" in it -- a test double that
    trips the production guard would prove nothing.
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []
        self.declared_subscribers: list[str] = []

    def declare_publisher(self, key: str, **kwargs: Any) -> _RecordingPublisher:
        return _RecordingPublisher(key, self.published)

    def declare_subscriber(self, key: str, handler: Any, **kwargs: Any) -> Any:
        self.declared_subscribers.append(key)
        return type("Sub", (), {"undeclare": lambda self: None})()

    def put(self, key: str, payload: Any, **kwargs: Any) -> None:
        self.published.append((key, str(payload).encode()))


class _StubOllama:
    """Streams one completion containing a string nothing else in the test uses."""

    async def generate_stream(self, request: Any) -> AsyncGenerator[str, None]:
        for word in SECRET.split():
            yield word + " "

    async def generate(self, request: Any) -> Any:
        raise AssertionError("streaming test must not hit the non-streaming path")


@pytest.fixture
def live_session_client() -> Iterator[tuple[TestClient, _RecordingSession]]:
    """A node whose runtime holds what the route accepts as a live Zenoh session."""
    session = _RecordingSession()
    runtime = type("Runtime", (), {"zenoh_client": type("ZC", (), {"session": session})()})()

    app.dependency_overrides[get_ollama_client] = lambda: _StubOllama()
    try:
        with TestClient(app) as client:
            # Set AFTER the lifespan runs -- startup assigns the real runtime and
            # would otherwise overwrite this the moment the client is entered.
            app.state.runtime = runtime
            yield client, session
    finally:
        app.state.runtime = None
        app.dependency_overrides.pop(get_ollama_client, None)


def _stream(client: TestClient) -> str:
    response = client.post(
        "/infer",
        json={"model": "llama3", "prompt": "What is the capital of France?", "stream": True},
    )
    assert response.status_code == 200, response.text
    return response.text


def test_generated_tokens_are_never_published_to_the_mesh(
    live_session_client: tuple[TestClient, _RecordingSession],
) -> None:
    """The completion text must not appear in anything put on a Zenoh key."""
    client, session = live_session_client
    body = _stream(client)

    assert SECRET.split()[0] in body, "the caller should still receive the completion"

    leaked = [
        (key, payload)
        for key, payload in session.published
        if any(word.encode() in payload for word in SECRET.split())
    ]
    assert not leaked, (
        "generated text was published onto the Zenoh mesh in plaintext. "
        f"Any peer subscribing to 'public-intelligence/net/transport/stream/**' "
        f"reads every token of every completion. Leaked on: {[k for k, _ in leaked]}"
    )


def test_no_transport_stream_topic_is_declared_at_all(
    live_session_client: tuple[TestClient, _RecordingSession],
) -> None:
    """Not even an empty stream topic, and no ack subscriber to go with it.

    Checked separately from the payload assertion because a router that declares
    the publisher and happens to send nothing is still advertising a mesh key that
    exists to carry completion text.
    """
    client, session = live_session_client
    _stream(client)

    published_keys = {key for key, _ in session.published}
    assert not any("transport/stream" in key for key in published_keys), published_keys
    assert not any("transport/ack" in key for key in session.declared_subscribers), (
        session.declared_subscribers
    )


def test_the_sse_body_is_not_prefixed_with_a_session_id_line(
    live_session_client: tuple[TestClient, _RecordingSession],
) -> None:
    """`session_id: <id>` is not a valid SSE field and no client asked for it."""
    client, _ = live_session_client
    body = _stream(client)

    assert not body.startswith("session_id:"), body[:120]
    assert "session_id:" not in body, body[:200]


async def test_a_long_stream_completes_instead_of_deadlocking(
    live_session_client: tuple[TestClient, _RecordingSession],
) -> None:
    """More chunks than the old flow-control window, on a node with a live session.

    `BackpressuredStreamRouter.send_chunk` blocked once `sent - acked >= window_size`
    (default 4), and nothing in this repository has ever published an ACK to
    `.../transport/ack/{session_id}`. So a response longer than four chunks hung
    forever -- on exactly the deployment this project exists to serve, a node
    attached to the mesh.

    SECRET is six words, which is why it was chosen: four would have passed.
    """
    client, _ = live_session_client
    body = _stream(client)

    # Every word arrives, so nothing was truncated at the window boundary either.
    for word in SECRET.split():
        assert word in body, f"stream stopped before {word!r}: {body!r}"
