"""Exact-prompt completion memoization on the /infer route.

This replaces a character-level radix trie that split each prompt into a
"cached prefix" plus suffix and sent only the suffix to Ollama. Splitting
was unsound for generation: a shared text prefix does not give the model
the continuation's context, and an exact repeat -- the one case the trie
matched completely -- computed its suffix as EMPTY, so the second asking
of "What is the capital of France?" reached Ollama as an empty prompt.
The tests below pin the replacement: an exact repeat is served from the
memo without touching Ollama, and every near-overlap prompt goes through
INTACT.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from node.core.completion_cache import CompletionCache
from node.main import app


def _ollama_returning(text: str) -> AsyncMock:
    """An OllamaClient double whose generate() returns `text` as the completion."""
    client = AsyncMock()
    response = MagicMock(spec=["model", "response"])
    response.model = "llama3-8b"
    response.response = text
    client.generate.return_value = response
    return client


def _post_infer(client: TestClient, prompt: str, model: str = "llama3-8b") -> dict[str, object]:
    response = client.post("/infer", json={"model": model, "prompt": prompt})
    assert response.status_code == 200
    return response.json()


# --- the cache itself --------------------------------------------------------


def test_lookup_miss_returns_none_and_insert_hit_returns_completion() -> None:
    cache = CompletionCache()

    assert cache.lookup("llama3-8b", "What is 2+2?") is None

    cache.insert("llama3-8b", "What is 2+2?", "4")
    assert cache.lookup("llama3-8b", "What is 2+2?") == "4"
    # A different prompt is a miss even though they share a long text prefix.
    assert cache.lookup("llama3-8b", "What is 2+2? Answer in words.") is None


def test_the_same_prompt_on_two_models_is_two_entries() -> None:
    """Prompt alone must not be the key.

    Two models see identical literal prompts all the time; keyed on text
    only, the second model was served the first model's completion under
    its own name.
    """
    cache = CompletionCache()
    cache.insert("llama3-8b", "What is the capital of France?", "Paris")
    cache.insert("mistral-7b", "What is the capital of France?", "La ville de Paris")

    assert cache.lookup("llama3-8b", "What is the capital of France?") == "Paris"
    assert cache.lookup("mistral-7b", "What is the capital of France?") == (
        "La ville de Paris"
    )


def test_eviction_is_bounded_by_capacity_in_lru_order() -> None:
    cache = CompletionCache(capacity=2)

    cache.insert("m", "a", "1")
    cache.insert("m", "b", "2")
    assert cache.lookup("m", "a") == "1"  # refresh 'a'
    cache.insert("m", "c", "3")  # evicts 'b', the least recently used

    assert cache.lookup("m", "b") is None
    assert cache.lookup("m", "a") == "1"
    assert cache.lookup("m", "c") == "3"

    cache.insert("m", "d", "4")  # evicts 'a', refreshed above but now oldest
    assert cache.lookup("m", "a") is None
    assert len(cache.entries) == 2


# --- the route ---------------------------------------------------------------


def test_exact_repeat_is_served_without_calling_ollama() -> None:
    ollama = _ollama_returning("Paris")
    with (
        patch("node.main.Runtime", return_value=AsyncMock()),
        TestClient(app) as client,
    ):
        app.state.ollama_client = ollama
        app.state.completion_cache = CompletionCache()

        first = _post_infer(client, "What is the capital of France?", "llama3-8b")
        second = _post_infer(client, "What is the capital of France?", "llama3-8b")

    # One question asked twice reaches Ollama exactly once.
    assert ollama.generate.await_count == 1
    assert first["response"] == "Paris"
    assert second["response"] == "Paris"


def test_the_same_prompt_for_a_different_model_is_not_a_hit() -> None:
    """Route-level pin of the multi-model collision: model is part of the key."""
    ollama = AsyncMock()

    def _response(text: str) -> MagicMock:
        r = MagicMock(spec=["model", "response"])
        r.model = "whichever"
        r.response = text
        return r

    ollama.generate.side_effect = [_response("Paris"), _response("La ville de Paris")]
    with (
        patch("node.main.Runtime", return_value=AsyncMock()),
        TestClient(app) as client,
    ):
        app.state.ollama_client = ollama
        app.state.completion_cache = CompletionCache()

        llama = _post_infer(client, "What is the capital of France?", "llama3-8b")
        mistral = _post_infer(client, "What is the capital of France?", "mistral-7b")

    # The identical prompt for a different model must reach Ollama again,
    # and each answer must come back under its own request.
    assert ollama.generate.await_count == 2
    assert llama["response"] == "Paris"
    assert mistral["response"] == "La ville de Paris"


def test_near_overlap_prompt_is_sent_through_intact() -> None:
    ollama = _ollama_returning("answer")
    with (
        patch("node.main.Runtime", return_value=AsyncMock()),
        TestClient(app) as client,
    ):
        app.state.ollama_client = ollama
        app.state.completion_cache = CompletionCache()

        _post_infer(client, "What is 2+2?", "llama3-8b")
        _post_infer(client, "What is 2+2? Answer in words.", "llama3-8b")

    # The second question is NOT a hit and is NOT truncated to its shared
    # prefix or its tail: Ollama sees exactly what the caller asked.
    prompts_sent = [call.args[0].prompt for call in ollama.generate.call_args_list]
    assert prompts_sent == ["What is 2+2?", "What is 2+2? Answer in words."]
