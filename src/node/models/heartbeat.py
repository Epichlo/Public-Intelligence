"""Heartbeat domain model."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class Heartbeat(BaseModel):
    """Represents the runtime state and resource utilization of the Node."""

    node_id: str = Field(
        ...,
        description="Unique identifier of the Node sending the heartbeat.",
    )
    timestamp: datetime = Field(
        ...,
        description="The timestamp when these metrics were collected.",
    )
    queue_length: int = Field(
        ...,
        description="The number of inference requests currently queued.",
    )
    cpu_utilization: float = Field(
        ...,
        description="CPU utilization percentage (0.0 to 100.0).",
    )
    ram_available_gb: float = Field(
        ...,
        description="Available system RAM in gigabytes.",
    )
    gpu_utilization: float = Field(
        ...,
        description="GPU utilization percentage (0.0 to 100.0).",
    )
    vram_available_gb: float = Field(
        ...,
        description="Available GPU VRAM in gigabytes.",
    )

    @field_validator("node_id")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        """Validate that node_id is not empty or whitespace-only."""
        if not v.strip():
            raise ValueError("node_id cannot be empty or whitespace-only.")
        return v.strip()

    @field_validator("queue_length")
    @classmethod
    def validate_queue_length(cls, v: int) -> int:
        """Validate that queue_length is non-negative."""
        if v < 0:
            raise ValueError("Queue length cannot be negative.")
        return v

    @field_validator("cpu_utilization", "gpu_utilization")
    @classmethod
    def validate_utilization(cls, v: float) -> float:
        """Validate that utilization is between 0.0 and 100.0 inclusive."""
        if not (0.0 <= v <= 100.0):
            raise ValueError(
                "Utilization percentage must be between 0.0 and 100.0 inclusive."
            )
        return v

    @field_validator("ram_available_gb", "vram_available_gb")
    @classmethod
    def validate_available_memory(cls, v: float) -> float:
        """Validate that available memory is non-negative."""
        if v < 0.0:
            raise ValueError("Available memory must be non-negative.")
        return v
