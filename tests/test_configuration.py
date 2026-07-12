"""Tests for node configuration."""

from node.core.configuration import Settings, get_settings


def test_get_settings() -> None:
    """Verify that settings can be retrieved and has correct default values."""
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert settings.node_id == "node-local"
    assert settings.log_level == "INFO"
    assert settings.scheduler_url == "http://localhost:8080"
    assert settings.hostname == "localhost"
    assert settings.region == "local"
    assert isinstance(settings.hosted_models, list)
    assert settings.heartbeat_interval == 30
