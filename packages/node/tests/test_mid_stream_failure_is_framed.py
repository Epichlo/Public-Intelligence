"""A mid-stream Ollama failure must be machine-detectable by the caller.

`generate_stream` raises from inside its generator, but by then the 200 and
the SSE headers are already on the wire -- an HTTP error status is no longer
possible. With no framing, uvicorn simply closes the body and a truncated
completion is byte-for-byte indistinguishable from a finished one: Ollama
dying mid-answer looked like a normal end of stream. The node now emits one
explicit terminal error frame before closing, shaped like the mesh
protocol's encode_error payload ({"ok", "status", "error"}); no chunk
Ollama emits ever carries an "ok" key, so downstream parsers can tell them
apart reliably.
"""

from collections.abc import AsyncGenerator, Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from node.api.inference import get_ollama_client
from node.clients import OllamaError
from node.main import app


class _DiesMidStream:
    """Streams two real chunks, then dies the way a dropped socket would."""

    async def generate_stream(self, request: Any) -> AsyncGenerator[str, None]:
        yield 'data: {"model": "llama3", "response": "partial answer", "done": false}\n\n'
        yield 'data: {"model": "llama3", "response": " so fa", "done": false}\n\n'
        raise OllamaError("Ollama streaming generation failed: connection reset by peer")

    async def generate(self, request: Any) -> None:
        raise AssertionError("streaming test must not hit the non-streaming path")


class _CrashesMidStream:
    """Dies with a bug, not an OllamaError -- the frame must still appear."""

    async def generate_stream(self, request: Any) -> AsyncGenerator[str, None]:
        yield 'data: {"model": "llama3", "response": "chunk", "done": false}\n\n'
        raise RuntimeError("unexpected internal explosion")

    async def generate(self, request: Any) -> None:
        raise AssertionError("streaming test must not hit the non-streaming path")


class _Completes:
    """A clean stream: one chunk carrying done=true, no error."""

    async def generate_stream(self, request: Any) -> AsyncGenerator[str, None]:
        yield 'data: {"model": "llama3", "response": "all done", "done": true}\n\n'

    async def generate(self, request: Any) -> None:
        raise AssertionError("streaming test must not hit the non-streaming path")


_STUBS: dict[str, type[Any]] = {
    "ollama-dies": _DiesMidStream,
    "crashes": _CrashesMidStream,
    "completes": _Completes,
}


@pytest.fixture
def streaming_client(request: pytest.FixtureRequest) -> Iterator[TestClient]:
    stub = _STUBS[request.param]()
    app.dependency_overrides[get_ollama_client] = lambda: stub
    try:
        with (
            patch("node.main.Runtime", return_value=AsyncMock()),
            TestClient(app) as client,
        ):
            yield client
    finally:
        app.dependency_overrides.pop(get_ollama_client, None)


def _data_frames(body: str) -> list[dict[str, Any]]:
    frames = []
    for line in body.splitlines():
        if line.startswith("data: "):
            import json

            frames.append(json.loads(line[len("data: ") :]))
    return frames


@pytest.mark.parametrize("streaming_client", ["ollama-dies"], indirect=True)
def test_an_ollama_death_mid_stream_ends_in_an_explicit_error_frame(
    streaming_client: TestClient,
) -> None:
    response = streaming_client.post(
        "/infer", json={"model": "llama3", "prompt": "p", "stream": True}
    )

    # Headers went out before the failure, so the status cannot change; the
    # truncation must be visible in the BODY instead.
    assert response.status_code == 200
    frames = _data_frames(response.text)

    assert frames[0]["response"] == "partial answer"  # real bytes still delivered
    terminal = frames[-1]
    assert terminal["ok"] is False
    assert terminal["status"] == 502
    assert "connection reset" in terminal["error"]
    # And no normal Ollama chunk ever carries the marker, so the frame is
    # distinguishable from every legitimate end-of-stream.
    assert all("ok" not in frame for frame in frames[:-1])


@pytest.mark.parametrize("streaming_client", ["crashes"], indirect=True)
def test_a_non_ollama_crash_mid_stream_is_framed_too(streaming_client: TestClient) -> None:
    response = streaming_client.post(
        "/infer", json={"model": "llama3", "prompt": "p", "stream": True}
    )

    assert response.status_code == 200
    frames = _data_frames(response.text)
    assert frames[-1]["ok"] is False
    assert frames[-1]["status"] == 500


@pytest.mark.parametrize("streaming_client", ["completes"], indirect=True)
def test_a_clean_stream_still_ends_without_an_error_frame(streaming_client: TestClient) -> None:
    response = streaming_client.post(
        "/infer", json={"model": "llama3", "prompt": "p", "stream": True}
    )

    frames = _data_frames(response.text)
    assert len(frames) == 1
    assert frames[0]["done"] is True
