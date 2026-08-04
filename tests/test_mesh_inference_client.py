"""Tests for the Scheduler's mesh inference client.

The distinction this module exists to get right is between *the node did not answer* and
*the node answered with a failure*. The first must fall back to HTTP; the second must not,
because retrying over another transport would just fail the same way while hiding the real
error from the caller. So the two are separate exception types, asserted separately below.

The Zenoh session is faked here. The real router is exercised in the root suite
(`tests/test_mesh_inference_e2e.py`).
"""

import asyncio
import time
from typing import Any

import pytest

from scheduler.core.mesh_inference_client import (
    MeshInferenceClient,
    MeshNodeError,
    MeshUnavailableError,
)
from scheduler.core.mesh_protocol import (
    encode_chunk,
    encode_done,
    encode_error,
    encode_result,
    infer_key_expr,
    verify_request,
)

NODE_ID = "node-mesh-client"
TOKEN = "client-side-secret"


class FakePayload:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def to_bytes(self) -> bytes:
        return self._raw


class FakeSample:
    def __init__(self, raw: bytes) -> None:
        self.payload = FakePayload(raw)


class FakeReply:
    """A successful zenoh reply."""

    def __init__(self, raw: bytes) -> None:
        self.ok = FakeSample(raw)
        self.err = None


class FakeReplyError:
    """A zenoh-level error reply, as `Query.reply_err` produces."""

    def __init__(self, message: str = "queryable exploded") -> None:
        self.ok = None
        self.err = FakePayload(message.encode())


class FakeSession:
    """Returns a fixed reply sequence and records the query it was asked to send."""

    def __init__(self, replies: list[Any] | None = None, raises: Exception | None = None) -> None:
        self._replies = replies if replies is not None else []
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    def get(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"selector": selector, **kwargs})
        if self._raises is not None:
            raise self._raises
        return iter(self._replies)


class SlowSession:
    """Never produces a reply, so the first-reply deadline is what ends the wait."""

    def __init__(self, delay: float = 30.0) -> None:
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    def get(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"selector": selector, **kwargs})

        def generator() -> Any:
            time.sleep(self.delay)
            return
            yield

        return generator()


def _client(session: Any, **kwargs: Any) -> MeshInferenceClient:
    kwargs.setdefault("first_reply_timeout", 0.3)
    return MeshInferenceClient(session, **kwargs)


@pytest.mark.asyncio
async def test_non_streaming_request_returns_the_completion() -> None:
    session = FakeSession([FakeReply(encode_result("llama3", "the answer"))])
    client = _client(session)

    result = await client.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="q")

    assert result == {"model": "llama3", "response": "the answer"}


@pytest.mark.asyncio
async def test_query_goes_to_that_node_and_is_signed_for_it() -> None:
    """The node verifies the signature, so a malformed query would simply be refused."""
    session = FakeSession([FakeReply(encode_result("llama3", "ok"))])
    client = _client(session)

    await client.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="the prompt")

    call = session.calls[0]
    assert call["selector"] == infer_key_expr(NODE_ID)
    verified = verify_request(call["payload"], node_id=NODE_ID, token=TOKEN)
    assert verified.model == "llama3"
    assert verified.prompt == "the prompt"
    assert verified.stream is False


@pytest.mark.asyncio
async def test_streaming_query_is_signed_as_streaming() -> None:
    """`stream` is inside the signed digest, so it cannot be flipped in transit."""
    session = FakeSession([FakeReply(encode_chunk(0, "a")), FakeReply(encode_done())])
    client = _client(session)

    stream = await client.open_stream(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="p")
    async for _ in stream:
        pass

    verified = verify_request(session.calls[0]["payload"], node_id=NODE_ID, token=TOKEN)
    assert verified.stream is True


@pytest.mark.asyncio
async def test_replies_are_not_consolidated() -> None:
    """Streaming chunks all share one key expression.

    Under the default AUTO consolidation Zenoh may drop samples with the same key, which
    would silently eat tokens. NONE is required, not a preference.
    """
    session = FakeSession([FakeReply(encode_result("llama3", "ok"))])
    client = _client(session)

    await client.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="q")

    import zenoh

    consolidation = session.calls[0].get("consolidation")
    assert consolidation is not None, "query did not set a consolidation mode"
    assert consolidation == zenoh.ConsolidationMode.NONE, (
        f"consolidation was {consolidation}; anything but NONE may drop streamed chunks"
    )


@pytest.mark.asyncio
async def test_no_reply_is_mesh_unavailable() -> None:
    """Nothing answered, so the caller is free to try HTTP."""
    session = FakeSession([])
    client = _client(session)

    with pytest.raises(MeshUnavailableError):
        await client.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="q")


@pytest.mark.asyncio
async def test_silence_gives_up_at_the_first_reply_deadline() -> None:
    """A node marked reachable that never declared a queryable must not hang a request."""
    # Kept short only so the worker thread does not hold up interpreter shutdown; the
    # deadline being asserted is 0.2s, an order of magnitude below it.
    session = SlowSession(delay=2.0)
    client = _client(session, first_reply_timeout=0.2)

    started = time.monotonic()
    with pytest.raises(MeshUnavailableError):
        await client.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="q")

    assert time.monotonic() - started < 1.0, "did not honour the first-reply deadline"


@pytest.mark.asyncio
async def test_transport_error_is_mesh_unavailable() -> None:
    session = FakeSession(raises=RuntimeError("session closed"))
    client = _client(session)

    with pytest.raises(MeshUnavailableError):
        await client.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="q")


@pytest.mark.asyncio
async def test_absent_session_is_mesh_unavailable() -> None:
    """A Scheduler whose Zenoh session failed to open must fall back, not crash."""
    client = _client(None)

    with pytest.raises(MeshUnavailableError):
        await client.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="q")


@pytest.mark.asyncio
async def test_zenoh_level_reply_error_is_mesh_unavailable() -> None:
    """A `reply_err` is a transport-shaped failure, not an answer from our protocol."""
    session = FakeSession([FakeReplyError()])
    client = _client(session)

    with pytest.raises(MeshUnavailableError):
        await client.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="q")


@pytest.mark.asyncio
async def test_node_error_reply_is_not_mesh_unavailable() -> None:
    """The node answered. Falling back to HTTP would hide a real 404 behind a retry."""
    session = FakeSession([FakeReply(encode_error("model 'nope' not found", status=404))])
    client = _client(session)

    with pytest.raises(MeshNodeError) as excinfo:
        await client.infer(node_id=NODE_ID, token=TOKEN, model="nope", prompt="q")

    assert excinfo.value.status == 404
    assert "not found" in str(excinfo.value)


@pytest.mark.asyncio
async def test_streaming_yields_chunks_in_order_then_stops() -> None:
    session = FakeSession(
        [
            FakeReply(encode_chunk(0, "Hel")),
            FakeReply(encode_chunk(1, "lo")),
            FakeReply(encode_chunk(2, "!")),
            FakeReply(encode_done()),
        ]
    )
    client = _client(session)

    stream = await client.open_stream(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="p")
    chunks = [chunk async for chunk in stream]

    assert chunks == ["Hel", "lo", "!"]


@pytest.mark.asyncio
async def test_streaming_with_no_reply_is_mesh_unavailable_before_any_chunk() -> None:
    """Fallback is only safe before bytes have been sent, so it must surface here."""
    session = FakeSession([])
    client = _client(session)

    with pytest.raises(MeshUnavailableError):
        await client.open_stream(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="p")


@pytest.mark.asyncio
async def test_streaming_error_before_any_chunk_is_a_node_error() -> None:
    session = FakeSession([FakeReply(encode_error("model 'nope' not found", status=404))])
    client = _client(session)

    with pytest.raises(MeshNodeError) as excinfo:
        await client.open_stream(node_id=NODE_ID, token=TOKEN, model="nope", prompt="p")

    assert excinfo.value.status == 404


@pytest.mark.asyncio
async def test_streaming_error_after_a_chunk_propagates() -> None:
    """Once a chunk is out there is no falling back; the error must reach the caller."""
    session = FakeSession(
        [
            FakeReply(encode_chunk(0, "partial")),
            FakeReply(encode_error("ollama died", status=500)),
        ]
    )
    client = _client(session)

    stream = await client.open_stream(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="p")
    seen: list[str] = []
    with pytest.raises(MeshNodeError):
        async for chunk in stream:
            seen.append(chunk)

    assert seen == ["partial"]


@pytest.mark.asyncio
async def test_stream_ending_without_done_is_not_silently_truncated() -> None:
    """A stream that just stops must not look like a clean completion.

    If it did, a node killed mid-generation would return a truncated answer that the
    caller had no way to tell from a complete one.
    """
    session = FakeSession([FakeReply(encode_chunk(0, "half an ans"))])
    client = _client(session)

    stream = await client.open_stream(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="p")
    seen: list[str] = []
    with pytest.raises(MeshNodeError):
        async for chunk in stream:
            seen.append(chunk)

    assert seen == ["half an ans"]


@pytest.mark.asyncio
async def test_out_of_order_chunks_are_still_delivered() -> None:
    """Zenoh gives no reply-ordering guarantee. Dropping a chunk would be worse.

    The client notices and logs; it does not reorder. See the note in
    `specs/node-reachability.md`.
    """
    session = FakeSession(
        [
            FakeReply(encode_chunk(1, "second")),
            FakeReply(encode_chunk(0, "first")),
            FakeReply(encode_done()),
        ]
    )
    client = _client(session)

    stream = await client.open_stream(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="p")
    chunks = [chunk async for chunk in stream]

    assert chunks == ["second", "first"]


@pytest.mark.asyncio
async def test_malformed_reply_does_not_crash_the_caller() -> None:
    """Garbage from a node must present as a failure, not an unhandled exception."""
    session = FakeSession([FakeReply(b"not json")])
    client = _client(session)

    with pytest.raises((MeshUnavailableError, MeshNodeError)):
        await client.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="q")


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_interfere() -> None:
    """Each query gets its own reply stream; the bridge must not share state."""
    client_a = _client(FakeSession([FakeReply(encode_result("llama3", "A"))]))
    client_b = _client(FakeSession([FakeReply(encode_result("llama3", "B"))]))

    results = await asyncio.gather(
        client_a.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="a"),
        client_b.infer(node_id=NODE_ID, token=TOKEN, model="llama3", prompt="b"),
    )

    assert [r["response"] for r in results] == ["A", "B"]
