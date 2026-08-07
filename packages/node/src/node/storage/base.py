"""Abstract base class definitions for Public Intelligence artifact storage drivers."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ArtifactMetadata(BaseModel):
    """Pydantic model representing metadata associated with a saved artifact."""

    artifact_id: str
    task_id: str
    uri: str
    checksum: str
    status: str
    metadata: dict[str, Any]


class ArtifactStore(ABC):
    """Abstract base class defining the contract for storage drivers."""

    @abstractmethod
    async def save_artifact(
        self, task_id: str, data: bytes, metadata: dict[str, Any]
    ) -> ArtifactMetadata:
        """Save raw binary artifact data.

        Args:
            task_id: Unique task identifier.
            data: Raw binary payload.
            metadata: Associated metadata.

        Returns:
            ArtifactMetadata describing the saved artifact.
        """
        pass

    @abstractmethod
    async def get_artifact(self, uri: str) -> bytes:
        """Retrieve raw binary artifact data using its URI.

        Args:
            uri: Storage location URI.

        Returns:
            Raw bytes of the artifact.
        """
        pass
