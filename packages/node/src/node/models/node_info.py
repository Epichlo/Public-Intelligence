"""NodeInfo domain model."""

import ipaddress

from pydantic import BaseModel, Field, field_validator

from node.models.gpu_info import GPUInfo, cpu_only_gpu
from node.models.model_info import ModelInfo


class NodeInfo(BaseModel):
    """Represents the static identity and hardware capabilities of this Node."""

    node_id: str = Field(
        ...,
        description="Unique identifier for this Node in the network.",
    )
    hostname: str = Field(
        ...,
        description="Publicly accessible hostname or IP of this Node.",
    )
    region: str = Field(
        ...,
        description="Geographic region where the Node is running.",
    )
    ip_address: str = Field(
        ...,
        description="The IP address of the Node.",
    )
    cpu_cores: int = Field(
        ...,
        description="Number of CPU cores available on the Node.",
    )
    ram_total_gb: float = Field(
        ...,
        description="Total system RAM in gigabytes.",
    )
    gpu: GPUInfo = Field(
        default_factory=cpu_only_gpu,
        description=(
            "Real GPU hardware on this host. Defaults to the honest cpu-only profile "
            "rather than to a made-up capacity, so a caller that forgets to set it "
            "advertises no VRAM instead of claiming some."
        ),
    )
    available_models: list[ModelInfo] = Field(
        default_factory=list,
        description="List of hosted AI models and their capabilities.",
    )

    @field_validator("node_id", "hostname", "region")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        """Validate that the string is not empty or whitespace-only."""
        if not v.strip():
            raise ValueError("Value cannot be empty or whitespace-only.")
        return v.strip()

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, v: str) -> str:
        """Validate that the string is a valid IPv4 or IPv6 address."""
        stripped = v.strip()
        try:
            ipaddress.ip_address(stripped)
        except ValueError as err:
            raise ValueError("Must be a valid IPv4 or IPv6 address.") from err
        return stripped

    @field_validator("cpu_cores")
    @classmethod
    def validate_cpu_cores(cls, v: int) -> int:
        """Validate that cpu_cores is positive."""
        if v <= 0:
            raise ValueError("CPU cores must be greater than 0.")
        return v

    @field_validator("ram_total_gb")
    @classmethod
    def validate_ram_total(cls, v: float) -> float:
        """Validate that ram_total_gb is positive."""
        if v <= 0.0:
            raise ValueError("Total RAM must be greater than 0.0.")
        return v
