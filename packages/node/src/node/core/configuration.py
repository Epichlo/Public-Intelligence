"""Configuration management for the Public Intelligence Node."""

import json
import os
import sys
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    """Configuration settings for the Public Intelligence Node.

    Loads configurations from environment variables prefixed with NODE_
    or from a local .env file.
    """

    # Identity
    node_id: str = Field(
        default="node-local",
        description="Unique identifier for this Node in the network.",
    )
    hostname: str = Field(
        default="localhost",
        description="Publicly accessible hostname or IP of this Node.",
    )
    region: str = Field(
        default="local",
        description="Geographic region where the Node is running.",
    )

    # Scheduler
    scheduler_url: str = Field(
        default="http://localhost:8080",
        description="The base URL of the Scheduler service.",
    )

    # Ollama
    ollama_host: str = Field(
        default="http://localhost:11434",
        description="The host URL of the local Ollama server.",
    )

    # API
    # B104 (bind-all-interfaces) is suppressed on the default below, and that is
    # deliberate, not accidental: the node runs inside a container (see
    # docker-compose.yml, NODE_HOST=0.0.0.0) where loopback would be unreachable
    # through published ports. Operators wanting a specific interface override it
    # via NODE_HOST/HOST.
    #
    # This explanation must not begin with the `nosec` token: bandit parses the
    # words following it as test IDs and warns on each one.
    host: str = Field(
        default="0.0.0.0",  # nosec B104
        validation_alias=AliasChoices("NODE_HOST", "HOST"),
        description="The host interface to bind the FastAPI server to.",
    )
    port: int = Field(
        default=8080,
        validation_alias=AliasChoices("NODE_PORT", "PORT"),
        description="The port to bind the FastAPI server to.",
    )

    # Heartbeat
    heartbeat_interval_seconds: int = Field(
        default=30,
        description="Interval in seconds for sending heartbeats to the Scheduler.",
    )

    # Models
    hosted_models: list[str] = Field(
        default_factory=list,
        description="List of AI model names hosted and supported by this Node.",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="The logging level to use (DEBUG, INFO, WARNING, ERROR, CRITICAL).",
    )

    # Environment
    debug: bool = Field(
        default=False,
        description="Enable debug mode for the application.",
    )

    network_auth_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NODE_NETWORK_AUTH_TOKEN", "NETWORK_AUTH_TOKEN"),
        description="Secure network authentication token.",
    )

    # Zenoh WAN Networking
    zenoh_router_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NODE_ZENOH_ROUTER_URL", "ZENOH_ROUTER_URL"),
        description="Primary Zenoh WAN router URL (e.g. tcp/router:7447).",
    )
    zenoh_peer_endpoints: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("NODE_ZENOH_PEER_ENDPOINTS", "ZENOH_PEER_ENDPOINTS"),
        description="Additional Zenoh WAN peer endpoints for redundancy.",
    )
    bootstrap_routers: list[str] = Field(
        default_factory=lambda: ["tcp/bootstrap.public-intelligence.net:7447"],
        validation_alias=AliasChoices("NODE_BOOTSTRAP_ROUTERS", "BOOTSTRAP_ROUTERS"),
        description="Fallback Zenoh bootstrap routers for auto-joining WAN.",
    )
    zenoh_gossip_scouting: bool = Field(
        default=True,
        validation_alias=AliasChoices("NODE_ZENOH_GOSSIP_SCOUTING", "ZENOH_GOSSIP_SCOUTING"),
        description="Enable/disable Zenoh gossip scouting for dynamic WAN peer join.",
    )
    zenoh_connect_timeout_seconds: float = Field(
        default=5.0,
        description="Timeout in seconds for Zenoh peer connection attempts.",
    )
    zenoh_max_retry_interval_seconds: float = Field(
        default=30.0,
        description="Maximum retry interval in seconds for Zenoh reconnects.",
    )
    zenoh_multicast_scouting: bool = Field(
        default=True,
        description="Enable/disable local LAN multicast scouting.",
    )

    model_config = SettingsConfigDict(
        env_prefix="NODE_",
        env_file=(
            None if ("pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ) else ".env"
        ),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("node_id", "hostname", "region")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        """Validate that the string is not empty or pure whitespace."""
        if not v.strip():
            raise ValueError("Value cannot be empty or whitespace.")
        return v.strip()

    @field_validator("scheduler_url", "ollama_host")
    @classmethod
    def validate_urls(cls, v: str) -> str:
        """Validate that the URL starts with http:// or https://."""
        stripped = v.strip()
        if not stripped.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return stripped

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate that the port is in the valid range."""
        if not (1 <= v <= 65535):
            raise ValueError("Port must be between 1 and 65535 inclusive.")
        return v

    @field_validator("heartbeat_interval_seconds")
    @classmethod
    def validate_heartbeat_interval(cls, v: int) -> int:
        """Validate that the heartbeat interval is in range [1, 300]."""
        if not (1 <= v <= 300):
            raise ValueError("Heartbeat interval must be between 1 and 300 seconds inclusive.")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate that the log level is one of the allowed levels."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_val = v.strip().upper()
        if upper_val not in allowed:
            raise ValueError(f"Log level must be one of {allowed}")
        return upper_val

    @field_validator("hosted_models", mode="before")
    @classmethod
    def parse_hosted_models(cls, v: Any) -> list[str]:
        """Parse list of hosted models from comma-separated string, JSON, or list.

        Raises ValueError if any model name is empty or whitespace-only.
        """
        raw_items: list[Any] = []
        if isinstance(v, list):
            raw_items = v
        elif isinstance(v, str):
            val = v.strip()
            if not val:
                return []
            # Check if it's a JSON array representation
            if val.startswith("[") and val.endswith("]"):
                try:
                    parsed = json.loads(val)
                    raw_items = parsed if isinstance(parsed, list) else [val]
                except json.JSONDecodeError:
                    raw_items = [val]
            else:
                # Comma-separated parsing
                raw_items = val.split(",")
        else:
            return []

        parsed_items: list[str] = []
        for item in raw_items:
            item_str = str(item).strip()
            if not item_str:
                raise ValueError("Model name cannot be empty or whitespace-only.")
            parsed_items.append(item_str)
        return parsed_items

    @field_validator("zenoh_peer_endpoints", "bootstrap_routers", mode="before")
    @classmethod
    def parse_zenoh_peer_endpoints(cls, v: Any) -> list[str]:
        """Parse list of peer endpoints/bootstrap routers from string, JSON, or list.

        Raises ValueError if any endpoint is empty or whitespace-only.
        """
        raw_items: list[Any] = []
        if isinstance(v, list):
            raw_items = v
        elif isinstance(v, str):
            val = v.strip()
            if not val:
                return []
            if val.startswith("[") and val.endswith("]"):
                try:
                    parsed = json.loads(val)
                    raw_items = parsed if isinstance(parsed, list) else [val]
                except json.JSONDecodeError:
                    raw_items = [val]
            else:
                raw_items = val.split(",")
        else:
            return []

        parsed_items: list[str] = []
        for item in raw_items:
            item_str = str(item).strip()
            if not item_str:
                raise ValueError("Peer endpoint cannot be empty or whitespace-only.")
            parsed_items.append(item_str)
        return parsed_items

    @classmethod
    def settings_customise_sources(
        cls,
        _settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customise settings sources to allow lenient list parsing in env / dotenv.

        By default, pydantic-settings tries to parse list annotations as JSON.
        If JSON parsing fails, we fall back to raw string so that our before
        validator can parse comma-separated lists.
        """

        # Patch EnvSettingsSource
        if hasattr(env_settings, "decode_complex_value"):
            orig_env_decode = env_settings.decode_complex_value

            def custom_env_decode(field_name: str, field: Any, value: Any) -> Any:
                if field_name in (
                    "hosted_models",
                    "zenoh_peer_endpoints",
                    "bootstrap_routers",
                ):
                    try:
                        return json.loads(value)
                    except (ValueError, TypeError, json.JSONDecodeError):
                        return value
                return orig_env_decode(field_name, field, value)

            env_settings.decode_complex_value = custom_env_decode  # type: ignore

        # Patch DotEnvSettingsSource
        if hasattr(dotenv_settings, "decode_complex_value"):
            orig_dotenv_decode = dotenv_settings.decode_complex_value

            def custom_dotenv_decode(field_name: str, field: Any, value: Any) -> Any:
                if field_name in (
                    "hosted_models",
                    "zenoh_peer_endpoints",
                    "bootstrap_routers",
                ):
                    try:
                        return json.loads(value)
                    except (ValueError, TypeError, json.JSONDecodeError):
                        return value
                return orig_dotenv_decode(field_name, field, value)

            dotenv_settings.decode_complex_value = custom_dotenv_decode  # type: ignore

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    """Retrieve the cached global settings instance.

    Returns:
        Settings: The loaded Settings instance.
    """
    return Settings()
