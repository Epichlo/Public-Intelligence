"""End-to-end mesh inference over a real Zenoh router.

Every other test in this repo that touches inference mocks the transport. That is how ROADMAP
1.1 stayed invisible: Scheduler tests mock `httpx`, Node tests bypass auth, and the root E2E
drives the two apps independently rather than over a wire. So this test uses no transport
mocks at all -- a real Zenoh router on TCP loopback, a real node-side queryable, a real
Scheduler-side query, and the real signed envelope in between. Only Ollama is faked, because
inference itself is not what is under test.

What only a real router can prove, and a fake session cannot:

- Zenoh finalises a query when the `Query` object is dropped. The queryable callback runs on a
  Zenoh thread and returns immediately, handing the query to a coroutine; if that reference
  were lost, replies would be silently discarded. See `specs/node-reachability.md`.
- Multiple replies to one query survive the router. Streaming depends on it, and the default
  consolidation mode would drop them.

This is still one process on loopback. Two machines behind two NATs is ROADMAP 1.5.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import zenoh

from node.clients.mesh_inference_server import ZenohInferenceServer
from node.core.configuration import Settings as NodeSettings
from node.models import InferenceRequest, InferenceResponse
from scheduler.core.mesh_inference_client import (
    MeshInferenceClient,
    MeshNodeError,
    MeshUnavailableError,
)

NODE_ID = "node-e2e-mesh"
TOKEN = "e2e-shared-node-token"
ENDPOINT = "tcp/127.0.0.1:7453"


class FakeOllama:
    """Stands in for the local Ollama server; inference is not what is under test."""

    def __init__(self, text: str = "real mesh answer", chunks: list[str] | None = None) -> None:
        self.text = text
        self.chunks = chunks if chunks is not None else ["over ", "the ", "mesh"]
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
            # Yield control so the replies are genuinely produced over time rather than
            # all at once, which is what a real generation does.
            await asyncio.sleep(0)
            yield chunk


def _scheduler_session() -> Any:
    """The Scheduler's session: listens, as the deployed router does."""
    config = zenoh.Config()
    config.insert_json5("listen/endpoints", f'["{ENDPOINT}"]')
    config.insert_json5("mode", '"router"')
    config.insert_json5("scouting/multicast/enabled", "false")
    return zenoh.open(config)


def _node_session() -> Any:
    """The node's session: dials out and holds the connection, as a NAT'd host must."""
    config = zenoh.Config()
    config.insert_json5("connect/endpoints", f'["{ENDPOINT}"]')
    config.insert_json5("mode", '"client"')
    config.insert_json5("scouting/multicast/enabled", "false")
    return zenoh.open(config)


class MeshHarness:
    """A live scheduler session, node session, and node-side inference server."""

    def __init__(self, ollama: FakeOllama, token: str | None = TOKEN) -> None:
        self.ollama = ollama
        self.token = token
        self.scheduler_session: Any = None
        self.node_session: Any = None
        self.server: ZenohInferenceServer | None = None

    async def __aenter__(self) -> "MeshHarness":
        self.scheduler_session = _scheduler_session()
        self.node_session = _node_session()
        # Let the TCP handshake and queryable declaration propagate through the router.
        await asyncio.sleep(0.4)

        settings = NodeSettings(node_id=NODE_ID, network_auth_token=self.token)
        self.server = ZenohInferenceServer(settings, self.node_session, self.ollama)
        self.server.start()
        await asyncio.sleep(0.4)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self.server is not None:
            self.server.stop()
            await self.server.wait_for_inflight(timeout=5.0)
        for session in (self.node_session, self.scheduler_session):
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
        await asyncio.sleep(0.1)

    def client(self, **kwargs: Any) -> MeshInferenceClient:
        kwargs.setdefault("first_reply_timeout", 10.0)
        kwargs.setdefault("timeout", 20.0)
        return MeshInferenceClient(self.scheduler_session, **kwargs)


@pytest.mark.asyncio
async def test_non_streaming_inference_over_a_real_router() -> None:
    """The core claim of ROADMAP 1.1: a request reaches a node with no inbound port."""
    ollama = FakeOllama(text="served without an open port")

    async with MeshHarness(ollama) as harness:
        result = await harness.client().infer(
            node_id=NODE_ID, token=TOKEN, model="llama3", prompt="are you reachable?"
        )

    assert result["response"] == "served without an open port"
    assert result["model"] == "llama3"
    assert [r.prompt for r in ollama.seen] == ["are you reachable?"]


@pytest.mark.asyncio
async def test_streaming_inference_over_a_real_router() -> None:
    """Multiple replies to one query must survive the router, in order.

    This is the assertion that would fail if consolidation were left at its default: the
    chunks all reply on one key expression, so a consolidating router may drop them.
    """
    ollama = FakeOllama(chunks=["one ", "two ", "three"])

    async with MeshHarness(ollama) as harness:
        stream = await harness.client().open_stream(
            node_id=NODE_ID, token=TOKEN, model="llama3", prompt="count"
        )
        chunks = [chunk async for chunk in stream]

    assert chunks == ["one ", "two ", "three"], (
        "streamed chunks were lost or reordered crossing a real Zenoh router"
    )


@pytest.mark.asyncio
async def test_an_unsigned_request_is_refused_over_a_real_router() -> None:
    """Anyone can reach the key expression; only the token holder can spend the GPU."""
    ollama = FakeOllama()

    async with MeshHarness(ollama) as harness:
        with pytest.raises(MeshNodeError) as excinfo:
            await harness.client().infer(
                node_id=NODE_ID,
                token="not-the-nodes-token",
                model="llama3",
                prompt="let me in",
            )

    assert excinfo.value.status == 401
    assert ollama.seen == [], "an unauthenticated mesh request reached the backend"


@pytest.mark.asyncio
async def test_a_node_with_no_token_refuses_over_a_real_router() -> None:
    """Fail-closed holds across the real transport, not just in unit tests."""
    ollama = FakeOllama()

    async with MeshHarness(ollama, token=None) as harness:
        with pytest.raises(MeshNodeError) as excinfo:
            await harness.client().infer(
                node_id=NODE_ID, token=TOKEN, model="llama3", prompt="hello"
            )

    assert excinfo.value.status == 401
    assert ollama.seen == []


@pytest.mark.asyncio
async def test_a_replayed_request_is_refused_over_a_real_router() -> None:
    """A captured envelope must not be servable a second time."""
    from scheduler.core.mesh_protocol import encode_request, infer_key_expr

    ollama = FakeOllama()

    async with MeshHarness(ollama) as harness:
        payload = encode_request(
            node_id=NODE_ID, model="llama3", prompt="once only", stream=False, token=TOKEN
        )
        key = infer_key_expr(NODE_ID)

        def send() -> list[dict[str, Any]]:
            replies = harness.scheduler_session.get(
                key,
                payload=payload,
                timeout=10.0,
                consolidation=zenoh.ConsolidationMode.NONE,
            )
            out = []
            for reply in replies:
                sample = reply.ok
                if sample is not None:
                    import json

                    out.append(json.loads(sample.payload.to_bytes().decode()))
            return out

        first = await asyncio.to_thread(send)
        second = await asyncio.to_thread(send)

    assert first and first[0]["ok"] is True
    assert second and second[0]["ok"] is False, "the same signed request was served twice"
    assert len(ollama.seen) == 1


@pytest.mark.asyncio
async def test_a_missing_model_comes_back_as_404_over_a_real_router() -> None:
    """A node-reported failure must arrive as an answer, not as silence.

    Silence would make the Scheduler fall back to HTTP and hide the real reason.
    """
    from node.clients import OllamaError

    ollama = FakeOllama()
    ollama.error = OllamaError("model 'ghost' not found")

    async with MeshHarness(ollama) as harness:
        with pytest.raises(MeshNodeError) as excinfo:
            await harness.client().infer(
                node_id=NODE_ID, token=TOKEN, model="ghost", prompt="hi"
            )

    assert excinfo.value.status == 404


@pytest.mark.asyncio
async def test_querying_a_node_that_is_not_serving_is_unavailable_not_a_hang() -> None:
    """No queryable for that node id: the caller must be free to fall back to HTTP."""
    ollama = FakeOllama()

    async with MeshHarness(ollama) as harness:
        with pytest.raises(MeshUnavailableError):
            await harness.client(first_reply_timeout=3.0).infer(
                node_id="node-that-does-not-exist",
                token=TOKEN,
                model="llama3",
                prompt="anyone home?",
            )


@pytest.mark.asyncio
async def test_the_node_stops_answering_after_it_is_stopped() -> None:
    """Undeclaring the queryable must actually stop work arriving."""
    ollama = FakeOllama()

    async with MeshHarness(ollama) as harness:
        assert harness.server is not None
        harness.server.stop()
        await asyncio.sleep(0.3)

        with pytest.raises(MeshUnavailableError):
            await harness.client(first_reply_timeout=3.0).infer(
                node_id=NODE_ID, token=TOKEN, model="llama3", prompt="still there?"
            )

    assert ollama.seen == []
