"""Tests for the Node's Zenoh inference queryable.

This is the path that makes a node behind NAT reachable: instead of the Scheduler dialling
`http://<ip>:8080/infer`, the node answers queries on the outbound Zenoh session it already
holds. See `specs/node-reachability.md`.

The Zenoh session is faked here so the contract can be asserted without a router. The real
router is exercised in the root suite (`tests/test_mesh_inference_e2e.py`), which is what
pins the behaviour a fake cannot prove -- in particular that a query stays open while an
async reply is produced.
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from node.clients.mesh_inference_server import ZenohInferenceServer
from node.core.configuration import Settings
from node.core.mesh_protocol import encode_request, infer_key_expr
from node.models import InferenceRequest, InferenceResponse

NODE_ID = "node-mesh-server"
TOKEN = "server-side-secret"


class FakeZBytes:
    """Stands in for zenoh's payload wrapper."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def to_bytes(self) -> bytes:
        return self._raw


class FakeQuery:
    """Records the replies the server sends for one query."""

    def __init__(self, payload: bytes) -> None:
        self.payload = FakeZBytes(payload)
        self.replies: list[dict[str, Any]] = []
        self.errors: list[str] = []

    def reply(self, key_expr: str, payload: bytes) -> None:
        self.replies.append(json.loads(payload.decode("utf-8")))

    def reply_err(self, payload: bytes) -> None:
        self.errors.append(payload.decode("utf-8"))


class FakeQueryable:
    def __init__(self) -> None:
        self.undeclared = False

    def undeclare(self) -> None:
        self.undeclared = True


class FakeSession:
    """Captures the queryable declaration so the test can invoke its callback."""

    def __init__(self) -> None:
        self.key_expr: str | None = None
        self.callback: Any = None
        self.queryable = FakeQueryable()

    def declare_queryable(self, key_expr: str, callback: Any, **kwargs: Any) -> FakeQueryable:
        self.key_expr = key_expr
        self.callback = callback
        return self.queryable


class FakeOllama:
    """Minimal stand-in for OllamaClient."""

    def __init__(self, text: str = "generated text", chunks: list[str] | None = None) -> None:
        self.text = text
        self.chunks = chunks if chunks is not None else ["Hel", "lo", "!"]
        self.error: Exception | None = None
        self.seen: list[InferenceRequest] = []

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        self.seen.append(request)
        if self.error is not None:
            raise self.error
        return InferenceResponse(model=request.model, response=self.text)

    async def generate_stream(self, request: InferenceRequest) -> AsyncGenerator[str, None]:
        self.seen.append(request)
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            yield chunk


@pytest.fixture
def settings() -> Settings:
    return Settings(node_id=NODE_ID, network_auth_token=TOKEN)


async def _drain(server: ZenohInferenceServer, query: FakeQuery) -> None:
    """Deliver one query and wait for the server to finish answering it."""
    server._session.callback(query)  # type: ignore[attr-defined]
    await server.wait_for_inflight(timeout=5.0)


def _request(**overrides: Any) -> bytes:
    kwargs: dict[str, Any] = {
        "node_id": NODE_ID,
        "model": "llama3",
        "prompt": "hello",
        "stream": False,
        "token": TOKEN,
    }
    kwargs.update(overrides)
    return encode_request(**kwargs)


@pytest.mark.asyncio
async def test_declares_queryable_on_its_own_key(settings: Settings) -> None:
    """The node must serve exactly its own key expression."""
    session = FakeSession()
    server = ZenohInferenceServer(settings, session, FakeOllama())

    server.start()

    assert session.key_expr == infer_key_expr(NODE_ID)
    assert session.callback is not None


@pytest.mark.asyncio
async def test_stop_undeclares_the_queryable(settings: Settings) -> None:
    """A stopped node must stop accepting work."""
    session = FakeSession()
    server = ZenohInferenceServer(settings, session, FakeOllama())
    server.start()

    server.stop()

    assert session.queryable.undeclared is True


@pytest.mark.asyncio
async def test_serves_a_signed_non_streaming_request(settings: Settings) -> None:
    """The happy path: verified request in, Ollama's output back as one reply."""
    session = FakeSession()
    ollama = FakeOllama(text="the completion")
    server = ZenohInferenceServer(settings, session, ollama)
    server.start()

    query = FakeQuery(_request(prompt="what is 2+2"))
    await _drain(server, query)

    assert query.replies == [{"ok": True, "model": "llama3", "response": "the completion"}]
    assert [r.prompt for r in ollama.seen] == ["what is 2+2"]


@pytest.mark.asyncio
async def test_serves_a_streaming_request_as_chunks_then_done(settings: Settings) -> None:
    """Streaming replies must arrive one per chunk, indexed, and be terminated."""
    session = FakeSession()
    ollama = FakeOllama(chunks=["Hel", "lo", "!"])
    server = ZenohInferenceServer(settings, session, ollama)
    server.start()

    query = FakeQuery(_request(stream=True))
    await _drain(server, query)

    assert query.replies == [
        {"ok": True, "i": 0, "chunk": "Hel"},
        {"ok": True, "i": 1, "chunk": "lo"},
        {"ok": True, "i": 2, "chunk": "!"},
        {"ok": True, "done": True},
    ]


@pytest.mark.asyncio
async def test_unsigned_request_is_refused_and_never_reaches_ollama(settings: Settings) -> None:
    """An unauthenticated query must not spend the host's GPU."""
    session = FakeSession()
    ollama = FakeOllama()
    server = ZenohInferenceServer(settings, session, ollama)
    server.start()

    query = FakeQuery(_request(token="wrong-token"))
    await _drain(server, query)

    assert ollama.seen == [], "unauthenticated mesh query reached the inference backend"
    assert len(query.replies) == 1
    assert query.replies[0]["ok"] is False
    assert query.replies[0]["status"] == 401


@pytest.mark.asyncio
async def test_node_without_a_token_serves_nothing(settings: Settings) -> None:
    """Fails closed, matching the HTTP control API."""
    unconfigured = Settings(node_id=NODE_ID, network_auth_token=None)
    session = FakeSession()
    ollama = FakeOllama()
    server = ZenohInferenceServer(unconfigured, session, ollama)
    server.start()

    query = FakeQuery(_request())
    await _drain(server, query)

    assert ollama.seen == []
    assert query.replies[0]["ok"] is False
    assert query.replies[0]["status"] == 401


@pytest.mark.asyncio
async def test_replayed_request_is_refused(settings: Settings) -> None:
    """The server holds a nonce cache across queries, not per query."""
    session = FakeSession()
    ollama = FakeOllama()
    server = ZenohInferenceServer(settings, session, ollama)
    server.start()

    payload = _request()
    first = FakeQuery(payload)
    await _drain(server, first)
    second = FakeQuery(payload)
    await _drain(server, second)

    assert first.replies[0]["ok"] is True
    assert second.replies[0]["ok"] is False, "the same signed request was served twice"
    assert len(ollama.seen) == 1


@pytest.mark.asyncio
async def test_missing_model_reports_404_not_500(settings: Settings) -> None:
    """A model the host has not pulled is a client error, not a node fault."""
    from node.clients import OllamaError

    session = FakeSession()
    ollama = FakeOllama()
    ollama.error = OllamaError("model 'nope' not found")
    server = ZenohInferenceServer(settings, session, ollama)
    server.start()

    query = FakeQuery(_request(model="nope"))
    await _drain(server, query)

    assert query.replies[0]["ok"] is False
    assert query.replies[0]["status"] == 404


@pytest.mark.asyncio
async def test_backend_failure_is_reported_as_an_error_reply(settings: Settings) -> None:
    """A crash mid-inference must produce an error reply, not silence.

    Silence would leave the Scheduler waiting out its timeout and then falling back to
    HTTP, which would fail the same way -- so the caller must be told the node answered.
    """
    from node.clients import OllamaError

    session = FakeSession()
    ollama = FakeOllama()
    ollama.error = OllamaError("ollama is down")
    server = ZenohInferenceServer(settings, session, ollama)
    server.start()

    query = FakeQuery(_request())
    await _drain(server, query)

    assert query.replies[0]["ok"] is False
    assert query.replies[0]["status"] == 500


@pytest.mark.asyncio
async def test_garbage_payload_does_not_kill_the_queryable(settings: Settings) -> None:
    """A malformed query must be refused, and the server must keep serving."""
    session = FakeSession()
    ollama = FakeOllama()
    server = ZenohInferenceServer(settings, session, ollama)
    server.start()

    bad = FakeQuery(b"not json at all")
    await _drain(server, bad)
    assert bad.replies[0]["ok"] is False

    good = FakeQuery(_request())
    await _drain(server, good)
    assert good.replies[0]["ok"] is True, "queryable stopped serving after one bad query"


@pytest.mark.asyncio
async def test_concurrent_queries_are_answered_independently(settings: Settings) -> None:
    """Two in-flight queries must not cross-contaminate their replies."""
    session = FakeSession()
    ollama = FakeOllama(text="shared")
    server = ZenohInferenceServer(settings, session, ollama)
    server.start()

    first = FakeQuery(_request(prompt="one"))
    second = FakeQuery(_request(prompt="two"))
    session.callback(first)
    session.callback(second)
    await server.wait_for_inflight(timeout=5.0)

    assert len(first.replies) == 1
    assert len(second.replies) == 1
    assert {r.prompt for r in ollama.seen} == {"one", "two"}


@pytest.mark.asyncio
async def test_start_without_a_session_is_a_noop(settings: Settings) -> None:
    """A node whose Zenoh connection was deferred must still boot."""
    server = ZenohInferenceServer(settings, None, FakeOllama())

    server.start()
    server.stop()

    assert server.is_serving() is False


@pytest.mark.asyncio
async def test_wait_for_inflight_returns_when_idle(settings: Settings) -> None:
    """Nothing in flight must not block shutdown."""
    session = FakeSession()
    server = ZenohInferenceServer(settings, session, FakeOllama())
    server.start()

    await asyncio.wait_for(server.wait_for_inflight(timeout=1.0), timeout=2.0)
