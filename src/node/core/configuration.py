"""Configuration management for the Public Intelligence Node."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for the Public Intelligence Node.

    Loads configurations from environment variables prefixed with NODE_
    or from a local .env file.
    """

    # API configuration
    host: str = Field(
        default="0.0.0.0",
        description="The host interface to bind the FastAPI server to.",
    )
    port: int = Field(
        default=8000,
        description="The port to bind the FastAPI server to.",
    )

    # Scheduler configuration
    scheduler_url: str = Field(
        default="http://localhost:8080",
        description="The base URL of the Scheduler service.",
    )

    # Node Identification
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
    hosted_models: list[str] = Field(
        default_factory=list,
        description="List of AI model names hosted and supported by this Node.",
    )
    heartbeat_interval: int = Field(
        default=30,
        description="Interval in seconds for sending heartbeats to the Scheduler.",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="The logging level to use (DEBUG, INFO, WARNING, ERROR).",
    )

    model_config = SettingsConfigDict(
        env_prefix="NODE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> Settings:
    """Retrieve the global settings instance.

    Returns:
        Settings: The loaded Settings instance.
    """
    return Settings()
