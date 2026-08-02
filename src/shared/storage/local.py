"""Concrete local disk storage driver implementation for Public Intelligence artifacts."""

import hashlib
import os
import tempfile
from typing import Any

from src.shared.storage.base import ArtifactMetadata, ArtifactStore

# Resolved from the OS temp directory rather than a hardcoded "/tmp": that path
# does not exist on Windows (it resolves to <drive>:\tmp), and a fixed, predictable
# location under a world-writable directory is a symlink-attack surface.
DEFAULT_ARTIFACT_DIR = os.path.join(
    tempfile.gettempdir(), "public_intelligence", "artifacts"
)


class LocalDiskArtifactStore(ArtifactStore):
    """Concrete implementation of ArtifactStore using the local filesystem."""

    def __init__(self, base_directory: str = DEFAULT_ARTIFACT_DIR) -> None:
        """Initialize the LocalDiskArtifactStore and ensure the base directory exists safely.

        Args:
            base_directory: The base local directory path where artifacts are saved.
        """
        self.base_directory = base_directory
        os.makedirs(self.base_directory, exist_ok=True)

    async def save_artifact(
        self, task_id: str, data: bytes, metadata: dict[str, Any]
    ) -> ArtifactMetadata:
        """Save a raw binary data artifact to the local disk.

        Calculates the SHA-256 checksum, generates a structured ID, writes the data
        to `{artifact_id}.bin`, and returns the ArtifactMetadata.

        Args:
            task_id: Unique identifier for the task producing the artifact.
            data: Raw binary bytes of the artifact.
            metadata: Dict of metadata attributes associated with the artifact.

        Returns:
            ArtifactMetadata describing the committed artifact.
        """
        # Calculate the full SHA-256 checksum string of the data
        checksum = hashlib.sha256(data).hexdigest()

        # Generate structured artifact_id: art_{task_id}_{checksum[:12]}
        artifact_id = f"art_{task_id}_{checksum[:12]}"

        # Write raw binary data to a file named {artifact_id}.bin inside the base directory
        filename = f"{artifact_id}.bin"
        filepath = os.path.join(self.base_directory, filename)

        with open(filepath, "wb") as f:
            f.write(data)

        # Build and return valid ArtifactMetadata Pydantic object
        uri = f"file://{filepath}"
        return ArtifactMetadata(
            artifact_id=artifact_id,
            task_id=task_id,
            uri=uri,
            checksum=checksum,
            status="COMMITTED",
            metadata=metadata,
        )

    async def get_artifact(self, uri: str) -> bytes:
        """Retrieve the raw binary data of an artifact from the local disk using its URI.

        Args:
            uri: The storage URI starting with 'file://'.

        Returns:
            The raw bytes of the artifact.

        Raises:
            ValueError: If the URI format does not begin with 'file://'.
            FileNotFoundError: If the file does not exist on the local disk.
        """
        prefix = "file://"
        if not uri.startswith(prefix):
            raise ValueError(
                f"Invalid URI format. Expected protocol prefix: '{prefix}'"
            )

        # Strip the 'file://' prefix to get the absolute path
        filepath = uri[len(prefix) :]

        # Verify the file exists on the local disk
        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"Artifact file not found at local storage path: '{filepath}'"
            )

        with open(filepath, "rb") as f:
            return f.read()
