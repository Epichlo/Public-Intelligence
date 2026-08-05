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
        assert settings.port == 8080
        assert settings.heartbeat_interval_seconds == 30
        assert settings.model_refresh_interval_seconds == 60
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
        "NODE_MODEL_REFRESH_INTERVAL_SECONDS": "120",
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
        assert settings.model_refresh_interval_seconds == 120
        assert settings.log_level == "DEBUG"
        assert settings.debug is True


def test_standard_environment_overrides() -> None:
    """Verify that settings can be overridden by standard HOST and PORT env vars."""
    env = {
        "HOST": "127.0.0.2",
        "PORT": "8500",
    }
    with patch.dict(os.environ, env, clear=True):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.host == "127.0.0.2"
        assert settings.port == 8500


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

    with pytest.raises(ValidationError):
        Settings(model_refresh_interval_seconds=0)  # Interval below minimum

    with pytest.raises(ValidationError):
        Settings(model_refresh_interval_seconds=3601)  # Interval above maximum


def test_there_is_no_configured_model_list() -> None:
    """Which models a node serves is read from Ollama, never configured.

    `hosted_models` used to be settable here and documented in `.env.example` as
    the models this node hosts. It did not control what the node advertised --
    nothing on the registration or heartbeat path read it -- so an operator who
    set it got no effect and no warning. See specs/truthful-model-catalogue.md.

    This is a regression guard: pydantic-settings ignores unknown keyword
    arguments by default, so re-adding a config-declared catalogue would not
    otherwise announce itself.
    """
    assert "hosted_models" not in Settings.model_fields


def test_get_settings_cached() -> None:
    """Verify that get_settings() returns the same cached instance."""
    a = get_settings()
    b = get_settings()
    assert a is b


def test_network_auth_token_loading() -> None:
    """Verify that network_auth_token is loaded from environment variables."""
    # Test NODE_NETWORK_AUTH_TOKEN
    env1 = {"NODE_NETWORK_AUTH_TOKEN": "node-secret"}
    with patch.dict(os.environ, env1, clear=True):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.network_auth_token == "node-secret"

    # Test standard NETWORK_AUTH_TOKEN
    env2 = {"NETWORK_AUTH_TOKEN": "global-secret"}
    with patch.dict(os.environ, env2, clear=True):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.network_auth_token == "global-secret"


def test_zenoh_wan_configuration() -> None:
    """Verify loading and parsing of Zenoh WAN configuration settings."""
    env = {
        "NODE_ZENOH_ROUTER_URL": "tcp/router.public-intelligence.net:7447",
        "NODE_ZENOH_PEER_ENDPOINTS": "tcp/peer1:7447,tcp/peer2:7447",
        "NODE_ZENOH_MULTICAST_SCOUTING": "False",
    }
    with patch.dict(os.environ, env, clear=True):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.zenoh_router_url == "tcp/router.public-intelligence.net:7447"
        assert settings.zenoh_peer_endpoints == ["tcp/peer1:7447", "tcp/peer2:7447"]
        assert settings.zenoh_multicast_scouting is False
