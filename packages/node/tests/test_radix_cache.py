"""Unit and integration tests for the RadixTrieCache."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from node.core.radix_cache import RadixTrieCache
from node.main import app


@pytest.fixture
def mock_ollama_client() -> AsyncMock:
    """Fixture to provide a mocked OllamaClient."""
    return AsyncMock()


@pytest.mark.anyio
async def test_radix_trie_prefix_matching() -> None:
    """Verify prefix matching on lookup_prefix and insert_prefix."""
    cache = RadixTrieCache()

    # 1. Lookup when empty
    prefix, suffix = await cache.lookup_prefix("hello world")
    assert prefix == ""
    assert suffix == "hello world"

    # 2. Insert and match
    await cache.insert_prefix("hello ")
    prefix, suffix = await cache.lookup_prefix("hello world")
    assert prefix == "hello "
    assert suffix == "world"

    # 3. Insert longer match
    await cache.insert_prefix("hello world")
    prefix, suffix = await cache.lookup_prefix("hello world suffix")
    assert prefix == "hello world"
    assert suffix == " suffix"

    # 4. Insertion of multiple distinct paths sharing prefixes
    await cache.insert_prefix("hello friend")
    prefix, suffix = await cache.lookup_prefix("hello friend suffix")
    assert prefix == "hello friend"
    assert suffix == " suffix"

    # Match common prefix parts that are not complete leaves
    prefix, suffix = await cache.lookup_prefix("hello foe")
    assert prefix == "hello "
    assert suffix == "foe"


@pytest.mark.anyio
async def test_radix_trie_lru_eviction() -> None:
    """Verify that RadixTrieCache performs Least Recently Used (LRU) node evictions."""
    cache = RadixTrieCache(capacity=3)

    # Insert 3 prompt paths
    await cache.insert_prefix("apple")
    await cache.insert_prefix("banana")
    await cache.insert_prefix("cherry")

    # Update access time of apple
    await cache.lookup_prefix("apple")

    # Insert date (triggers eviction of banana, which is the oldest)
    await cache.insert_prefix("date")

    # Verify banana is evicted
    prefix_p2, _suffix_p2 = await cache.lookup_prefix("banana")
    assert prefix_p2 == ""

    # Verify others are still in cache
    prefix_p1, _ = await cache.lookup_prefix("apple")
    assert prefix_p1 == "apple"

    prefix_p3, _ = await cache.lookup_prefix("cherry")
    assert prefix_p3 == "cherry"

    prefix_p4, _ = await cache.lookup_prefix("date")
    assert prefix_p4 == "date"


def test_api_infer_prefix_routing(mock_ollama_client: AsyncMock) -> None:
    """Verify that POST /infer intercepts prompt prefixes and routes suffixes."""
    mock_response = MagicMock()
    mock_response.model = "llama3-8b"
    mock_response.response = "Generated suffix completion"
    mock_ollama_client.generate.return_value = mock_response

    mock_runtime = AsyncMock()
    mock_runtime.ollama_client = mock_ollama_client
    mock_runtime.scheduler_client = AsyncMock()

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        # Manually initialize and set the RadixTrieCache in app state
        cache = RadixTrieCache()
        app.state.radix_cache = cache

        # Insert a prefix
        asyncio.run(cache.insert_prefix("hello "))

        # Post infer request with prompt "hello world"
        payload = {"model": "llama3-8b", "prompt": "hello world"}
        response = client.post("/infer", json=payload)

        assert response.status_code == 200

        # Verify that only the suffix "world" was routed to the backend serving model
        called_request = mock_ollama_client.generate.call_args[0][0]
        assert called_request.prompt == "world"

        # Verify that full prompt path "hello world" has been appended to the trie
        prefix, suffix = asyncio.run(cache.lookup_prefix("hello world"))
        assert prefix == "hello world"
        assert suffix == ""
