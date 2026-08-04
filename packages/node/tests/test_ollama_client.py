"""Tests for the OllamaClient."""

from unittest.mock import AsyncMock, MagicMock

import ollama
import pytest

from node.clients import OllamaClient, OllamaError
from node.core.configuration import Settings
from node.models import InferenceRequest


@pytest.fixture
def settings() -> Settings:
    """Fixture to provide test settings with a mock Ollama host."""
    return Settings(ollama_host="http://mock-ollama:11434")


@pytest.mark.anyio
async def test_health_success(settings: Settings) -> None:
    """Verify that health returns True when Ollama tags list succeeds."""
    mock_client = AsyncMock()
    mock_client.list.return_value = MagicMock(models=[])
    client = OllamaClient(settings, client=mock_client)

    assert await client.health() is True
    mock_client.list.assert_called_once()


@pytest.mark.anyio
async def test_health_failure(settings: Settings) -> None:
    """Verify that health returns False when Ollama tags list fails."""
    mock_client = AsyncMock()
    mock_client.list.side_effect = Exception("Connection refused")
    client = OllamaClient(settings, client=mock_client)

    assert await client.health() is False
    mock_client.list.assert_called_once()


@pytest.mark.anyio
async def test_list_models_success(settings: Settings) -> None:
    """Verify listing models translates details and show response to ModelInfo."""
    mock_client = AsyncMock()

    # Mock return value of list()
    mock_model_data = MagicMock()
    mock_model_data.model = "llama3-8b"
    mock_model_data.size = int(4.7 * (1024**3))
    mock_model_data.details.family = "llama"
    mock_client.list.return_value = MagicMock(models=[mock_model_data])

    # Mock return value of show("llama3-8b")
    mock_show_info = MagicMock()
    mock_show_info.modelinfo = {"llama.context_length": 8192}
    mock_client.show.return_value = mock_show_info

    client = OllamaClient(settings, client=mock_client)
    models = await client.list_models()

    assert len(models) == 1
    assert models[0].name == "llama3-8b"
    assert models[0].size_gb == 4.7
    assert models[0].family == "llama"
    assert models[0].context_length == 8192

    mock_client.list.assert_called_once()
    mock_client.show.assert_called_once_with("llama3-8b")


@pytest.mark.anyio
async def test_list_models_failure(settings: Settings) -> None:
    """Verify that list_models raises OllamaError on connection/Ollama failure."""
    mock_client = AsyncMock()
    mock_client.list.side_effect = Exception("Ollama server down")
    client = OllamaClient(settings, client=mock_client)

    with pytest.raises(OllamaError) as exc_info:
        await client.list_models()

    assert "Failed to list models" in str(exc_info.value)


@pytest.mark.anyio
async def test_generate_success(settings: Settings) -> None:
    """Verify that generation returns InferenceResponse on success."""
    mock_client = AsyncMock()
    mock_gen_response = MagicMock()
    mock_gen_response.model = "llama3-8b"
    mock_gen_response.response = "This is a response."
    mock_client.generate.return_value = mock_gen_response

    client = OllamaClient(settings, client=mock_client)
    req = InferenceRequest(model="llama3-8b", prompt="Hello")
    resp = await client.generate(req)

    assert resp.model == "llama3-8b"
    assert resp.response == "This is a response."
    mock_client.generate.assert_called_once_with(model="llama3-8b", prompt="Hello")


@pytest.mark.anyio
async def test_generate_missing_model(settings: Settings) -> None:
    """Verify that ResponseError 404 raises a clean model not found error."""
    mock_client = AsyncMock()
    mock_client.generate.side_effect = ollama.ResponseError("model not found", status_code=404)

    client = OllamaClient(settings, client=mock_client)
    req = InferenceRequest(model="non-existent", prompt="Hello")

    with pytest.raises(OllamaError) as exc_info:
        await client.generate(req)

    assert "was not found" in str(exc_info.value)


@pytest.mark.anyio
async def test_generate_generic_failure(settings: Settings) -> None:
    """Verify that other failures (like connection/runtime errors) raise OllamaError."""
    mock_client = AsyncMock()
    mock_client.generate.side_effect = Exception("Runtime error")

    client = OllamaClient(settings, client=mock_client)
    req = InferenceRequest(model="llama3-8b", prompt="Hello")

    with pytest.raises(OllamaError) as exc_info:
        await client.generate(req)

    assert "Ollama generation failed" in str(exc_info.value)


@pytest.mark.anyio
async def test_generate_stream_success(settings: Settings) -> None:
    """Verify that generate_stream yields formatted SSE chunks."""
    mock_client = AsyncMock()

    async def mock_generator():
        yield {"model": "llama3-8b", "response": "chunk1", "done": False}
        yield {"model": "llama3-8b", "response": "chunk2", "done": True}

    mock_client.generate.return_value = mock_generator()
    client = OllamaClient(settings, client=mock_client)
    req = InferenceRequest(model="llama3-8b", prompt="Hello", stream=True)

    chunks = []
    async for chunk in client.generate_stream(req):
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0] == ('data: {"model": "llama3-8b", "response": "chunk1", "done": false}\n\n')
    assert chunks[1] == ('data: {"model": "llama3-8b", "response": "chunk2", "done": true}\n\n')
    mock_client.generate.assert_called_once_with(model="llama3-8b", prompt="Hello", stream=True)
