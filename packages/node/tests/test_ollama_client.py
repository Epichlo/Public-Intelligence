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


def _listed_model(name: str, digest: str, size_gb: float = 4.7) -> MagicMock:
    """Build one entry as `ollama.AsyncClient.list()` returns it."""
    entry = MagicMock()
    entry.model = name
    entry.digest = digest
    entry.size = int(size_gb * (1024**3))
    entry.details.family = "llama"
    return entry


@pytest.mark.anyio
async def test_context_length_is_resolved_once_per_digest(settings: Settings) -> None:
    """Re-listing the same models must not re-issue `show()` for each of them.

    `list_models` is now called on an interval rather than once at startup (see
    specs/truthful-model-catalogue.md), and every entry it returns used to cost a
    follow-up `show()`. Left alone, a node hosting ten models would make ten extra
    round trips to Ollama every refresh, forever, to re-learn constants.
    """
    mock_client = AsyncMock()
    mock_client.list.return_value = MagicMock(
        models=[_listed_model("llama3-8b", "sha256:aaa"), _listed_model("mistral-7b", "sha256:bbb")]
    )
    mock_show = MagicMock()
    mock_show.modelinfo = {"llama.context_length": 8192}
    mock_client.show.return_value = mock_show

    client = OllamaClient(settings, client=mock_client)

    first = await client.list_models()
    assert mock_client.show.await_count == 2

    second = await client.list_models()
    assert mock_client.show.await_count == 2
    assert [m.context_length for m in second] == [m.context_length for m in first] == [8192, 8192]


@pytest.mark.anyio
async def test_a_repulled_model_resolves_its_context_length_again(settings: Settings) -> None:
    """The cache is keyed by digest, so re-pulling a model invalidates its entry.

    Keying by name would pin the first answer for a model whose weights -- and
    therefore whose context length -- had since been replaced.
    """
    mock_client = AsyncMock()
    mock_client.list.return_value = MagicMock(models=[_listed_model("llama3-8b", "sha256:aaa")])
    mock_show = MagicMock()
    mock_show.modelinfo = {"llama.context_length": 8192}
    mock_client.show.return_value = mock_show

    client = OllamaClient(settings, client=mock_client)
    assert (await client.list_models())[0].context_length == 8192

    mock_client.list.return_value = MagicMock(models=[_listed_model("llama3-8b", "sha256:ccc")])
    mock_show.modelinfo = {"llama.context_length": 32768}

    assert (await client.list_models())[0].context_length == 32768
    assert mock_client.show.await_count == 2


@pytest.mark.anyio
async def test_a_failed_show_is_not_cached(settings: Settings) -> None:
    """The 2048 fallback means "not known yet", so one blip must not make it permanent."""
    mock_client = AsyncMock()
    mock_client.list.return_value = MagicMock(models=[_listed_model("llama3-8b", "sha256:aaa")])
    mock_client.show.side_effect = Exception("ollama busy")

    client = OllamaClient(settings, client=mock_client)
    assert (await client.list_models())[0].context_length == 2048

    mock_show = MagicMock()
    mock_show.modelinfo = {"llama.context_length": 8192}
    mock_client.show.side_effect = None
    mock_client.show.return_value = mock_show

    assert (await client.list_models())[0].context_length == 8192
