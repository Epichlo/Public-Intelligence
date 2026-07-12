"""ModelInfo domain model."""

from pydantic import BaseModel, Field, field_validator


class ModelInfo(BaseModel):
    """Represents a hosted AI model's metadata and capabilities."""

    name: str = Field(
        ...,
        description="The unique identifier or name of the model (e.g. 'llama3-8b').",
    )
    size_gb: float = Field(
        ...,
        description="The size of the model in gigabytes.",
    )
    family: str = Field(
        ...,
        description="The architecture family of the model (e.g. 'llama', 'mistral').",
    )
    context_length: int = Field(
        ...,
        description="The maximum context length in tokens supported by the model.",
    )

    @field_validator("name", "family")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        """Validate that the string is not empty or whitespace-only."""
        if not v.strip():
            raise ValueError("Value cannot be empty or whitespace-only.")
        return v.strip()

    @field_validator("size_gb")
    @classmethod
    def validate_size(cls, v: float) -> float:
        """Validate that the size is non-negative."""
        if v < 0.0:
            raise ValueError("Model size must be non-negative.")
        return v

    @field_validator("context_length")
    @classmethod
    def validate_context_length(cls, v: int) -> int:
        """Validate that the context length is positive."""
        if v <= 0:
            raise ValueError("Context length must be greater than 0.")
        return v
