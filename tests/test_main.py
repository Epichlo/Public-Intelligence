"""Tests for FastAPI endpoints."""

from fastapi.testclient import TestClient

from node.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    """Verify that the GET /health endpoint works.

    Checks for correct status code and response payload.
    """
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
