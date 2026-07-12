"""Tests for node configuration."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from node.core.configuration import Settings, get_settings


def test_default_values() -> None:
    """Verify that settings has correct default values."""
    # Ensure no environment variables interfere
    with patch.dict(os.environ, {}, clear=True):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.node_id == "node-local"
        assert settings.hostname == "localhost"
        assert settings.region == "local"
        assert settings.scheduler_url == "http://localhost:8080"
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000
        assert settings.heartbeat_interval_seconds == 30
        assert settings.hosted_models == []
        assert settings.log_level == "INFO"
        assert settings.debug is False


def test_environment_overrides() -> None:
    """Verify that settings can be overridden by environment variables."""
    env = {
        "NODE_NODE_ID": "node-test-123",
        "NODE_HOSTNAME": "test-host",
        "NODE_REGION": "us-west",
        "NODE_SCHEDULER_URL": "https://scheduler.example.com",
        "NODE_HOST": "127.0.0.1",
        "NODE_PORT": "9000",
        "NODE_HEARTBEAT_INTERVAL_SECONDS": "60",
        "NODE_HOSTED_MODELS": "model-a,model-b",
        "NODE_LOG_LEVEL": "DEBUG",
        "NODE_DEBUG": "True",
    }
    with patch.dict(os.environ, env, clear=True):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.node_id == "node-test-123"
        assert settings.hostname == "test-host"
        assert settings.region == "us-west"
        assert settings.scheduler_url == "https://scheduler.example.com"
        assert settings.host == "127.0.0.1"
        assert settings.port == 9000
        assert settings.heartbeat_interval_seconds == 60
        assert settings.hosted_models == ["model-a", "model-b"]
        assert settings.log_level == "DEBUG"
        assert settings.debug is True


def test_validation_failures() -> None:
    """Verify that incorrect configuration raises ValidationError."""
    with pytest.raises(ValidationError):
        Settings(node_id=" ")  # Empty node_id

    with pytest.raises(ValidationError):
        Settings(scheduler_url="ftp://localhost:8080")  # Invalid protocol

    with pytest.raises(ValidationError):
        Settings(port=99999)  # Port too large

    with pytest.raises(ValidationError):
        Settings(port=0)  # Port too small

    with pytest.raises(ValidationError):
        Settings(heartbeat_interval_seconds=0)  # Interval below minimum

    with pytest.raises(ValidationError):
        Settings(heartbeat_interval_seconds=301)  # Interval above maximum

    with pytest.raises(ValidationError):
        Settings(log_level="TRACE")  # Invalid log level


def test_hosted_models_list_parsing() -> None:
    """Verify list parsing from various input formats for hosted_models."""
    # List input
    s1 = Settings(hosted_models=["model-1", "model-2"])
    assert s1.hosted_models == ["model-1", "model-2"]

    # Comma-separated string input
    s2 = Settings(hosted_models="model-1, model-2, model-3")
    assert s2.hosted_models == ["model-1", "model-2", "model-3"]

    # JSON array string input
    s3 = Settings(hosted_models='["model-1", "model-2"]')
    assert s3.hosted_models == ["model-1", "model-2"]

    # Single value string input
    s4 = Settings(hosted_models="model-1")
    assert s4.hosted_models == ["model-1"]

    # Empty string input
    s5 = Settings(hosted_models="")
    assert s5.hosted_models == []


def test_hosted_models_validation_failures() -> None:
    """Verify that hosted_models rejects empty or whitespace-only elements."""
    with pytest.raises(ValidationError):
        Settings(hosted_models=["", "llama3-8b"])

    with pytest.raises(ValidationError):
        Settings(hosted_models=[" ", "llama3-8b"])

    with pytest.raises(ValidationError):
        Settings(hosted_models="llama3-8b, ,mistral-7b")

    with pytest.raises(ValidationError):
        Settings(hosted_models='["", "llama3-8b"]')


def test_get_settings_cached() -> None:
    """Verify that get_settings() returns the same cached instance."""
    a = get_settings()
    b = get_settings()
    assert a is b
