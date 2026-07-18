"""Unit tests for abstract inference backends and client implementations."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from node.backends.mock import EchoBackend
from node.backends.ollama import OllamaBackend


@pytest.mark.anyio
async def test_echo_backend_generation() -> None:
    """Verify that EchoBackend initializes, generates, and streams responses.

    Ensures correct mirroring of outputs.
    """
    backend = EchoBackend()
    await backend.initialize()

    # 1. Non-streaming generation check
    response = await backend.generate(model="mock-model", prompt="Hello control plane")
    assert response == "Echo: Hello control plane"

    # 2. Streaming generation check
    chunks = []
    async for chunk in backend.generate_stream(
        model="mock-model", prompt="Hello control plane"
    ):
        chunks.append(chunk)
    assert "".join(chunks) == "Echo: Hello control plane"


@pytest.mark.anyio
async def test_ollama_backend_initialize_failure() -> None:
    """Verify that OllamaBackend raises a ConnectionError on connection failure."""
    backend = OllamaBackend(base_url="http://invalid-host-name-ollama:11434")
    with pytest.raises(ConnectionError) as exc_info:
        await backend.initialize()
    assert "Could not connect to Ollama server" in str(exc_info.value)


@pytest.mark.anyio
async def test_ollama_backend_initialize_unexpected_status() -> None:
    """Verify that OllamaBackend raises a ConnectionError on non-200 status code."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        backend = OllamaBackend()
        with pytest.raises(ConnectionError) as exc_info:
            await backend.initialize()
        assert "Ollama server returned status code: 500" in str(exc_info.value)


@pytest.mark.anyio
async def test_ollama_backend_generate_success() -> None:
    """Verify that OllamaBackend successfully parses non-streaming generate response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "Hello from Ollama"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        backend = OllamaBackend()
        res = await backend.generate(model="llama3", prompt="Hi")
        assert res == "Hello from Ollama"
        mock_post.assert_called_once()


@pytest.mark.anyio
async def test_ollama_backend_generate_stream_success() -> None:
    """Verify that OllamaBackend parses and yields chunks iteratively.

    Ensures correct parsing of stream lines.
    """
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()

    async def mock_aiter_lines() -> AsyncGenerator[str, None]:
        yield '{"response": "Hello"}'
        yield '{"response": " world"}'

    mock_response.aiter_lines = mock_aiter_lines

    # Mock async context manager for client.stream
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient.stream", return_value=mock_stream_ctx):
        backend = OllamaBackend()
        chunks = []
        async for chunk in backend.generate_stream(model="llama3", prompt="Hi"):
            chunks.append(chunk)

        assert "".join(chunks) == "Hello world"
