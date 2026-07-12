"""Tests for FastAPI endpoints and Inference API routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from node.clients import OllamaError
from node.main import app
from node.models import ModelInfo


@pytest.fixture
def mock_ollama_client() -> AsyncMock:
    """Fixture to provide a mocked OllamaClient."""
    return AsyncMock()


def test_health_endpoint_healthy(mock_ollama_client: AsyncMock) -> None:
    """Verify GET /health returns status healthy when Ollama is online."""
    mock_ollama_client.health.return_value = True

    mock_runtime = AsyncMock()
    mock_runtime.ollama_client = mock_ollama_client
    mock_runtime.scheduler_client = AsyncMock()

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "ollama": True}
        mock_ollama_client.health.assert_called_once()


def test_health_endpoint_degraded(mock_ollama_client: AsyncMock) -> None:
    """Verify GET /health returns status degraded when Ollama is offline."""
    mock_ollama_client.health.return_value = False

    mock_runtime = AsyncMock()
    mock_runtime.ollama_client = mock_ollama_client
    mock_runtime.scheduler_client = AsyncMock()

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "degraded", "ollama": False}
        mock_ollama_client.health.assert_called_once()


def test_list_models_success(mock_ollama_client: AsyncMock) -> None:
    """Verify GET /models returns list of hosted models from Ollama."""
    mock_model = ModelInfo(
        name="llama3-8b", size_gb=4.7, family="llama", context_length=8192
    )
    mock_ollama_client.list_models.return_value = [mock_model]

    mock_runtime = AsyncMock()
    mock_runtime.ollama_client = mock_ollama_client
    mock_runtime.scheduler_client = AsyncMock()

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        response = client.get("/models")
        assert response.status_code == 200
        assert response.json() == [mock_model.model_dump()]
        mock_ollama_client.list_models.assert_called_once()


def test_list_models_failure(mock_ollama_client: AsyncMock) -> None:
    """Verify GET /models returns 500 when model listing fails."""
    mock_ollama_client.list_models.side_effect = OllamaError("Connection error")

    mock_runtime = AsyncMock()
    mock_runtime.ollama_client = mock_ollama_client
    mock_runtime.scheduler_client = AsyncMock()

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        response = client.get("/models")
        assert response.status_code == 500
        assert "Connection error" in response.json()["detail"]


def test_infer_success(mock_ollama_client: AsyncMock) -> None:
    """Verify POST /infer returns inference response from Ollama Client."""
    mock_response = MagicMock()
    mock_response.model = "llama3-8b"
    mock_response.response = "Hello response"
    mock_ollama_client.generate.return_value = mock_response

    mock_runtime = AsyncMock()
    mock_runtime.ollama_client = mock_ollama_client
    mock_runtime.scheduler_client = AsyncMock()

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        payload = {"model": "llama3-8b", "prompt": "Hi"}
        response = client.post("/infer", json=payload)
        assert response.status_code == 200
        assert response.json() == {
            "model": "llama3-8b",
            "response": "Hello response",
        }
        mock_ollama_client.generate.assert_called_once()


def test_infer_model_not_found(mock_ollama_client: AsyncMock) -> None:
    """Verify POST /infer returns 404 when model is not found in Ollama."""
    mock_ollama_client.generate.side_effect = OllamaError(
        "Model 'non-existent' was not found"
    )

    mock_runtime = AsyncMock()
    mock_runtime.ollama_client = mock_ollama_client
    mock_runtime.scheduler_client = AsyncMock()

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        payload = {"model": "non-existent", "prompt": "Hi"}
        response = client.post("/infer", json=payload)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


def test_infer_generic_failure(mock_ollama_client: AsyncMock) -> None:
    """Verify POST /infer returns 500 when Ollama execution fails."""
    mock_ollama_client.generate.side_effect = OllamaError("Inference failed")

    mock_runtime = AsyncMock()
    mock_runtime.ollama_client = mock_ollama_client
    mock_runtime.scheduler_client = AsyncMock()

    with (
        patch("node.main.Runtime", return_value=mock_runtime),
        TestClient(app) as client,
    ):
        payload = {"model": "llama3-8b", "prompt": "Hi"}
        response = client.post("/infer", json=payload)
        assert response.status_code == 500
        assert "Inference failed" in response.json()["detail"]
