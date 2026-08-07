"""Unit and integration tests for the LocalDiskArtifactStore driver."""

import hashlib
import os
import shutil
import tempfile
from collections.abc import Generator

import pytest
from node.storage.local import LocalDiskArtifactStore


@pytest.fixture
def temp_artifact_store() -> Generator[LocalDiskArtifactStore, None, None]:
    """Fixture to set up a temporary directory and yield a LocalDiskArtifactStore instance."""
    temp_dir = tempfile.mkdtemp()
    store = LocalDiskArtifactStore(base_directory=temp_dir)
    yield store
    shutil.rmtree(temp_dir)


@pytest.mark.asyncio
async def test_save_and_retrieve_artifact(
    temp_artifact_store: LocalDiskArtifactStore,
) -> None:
    """Verify that artifact saving generates correct metadata and can be retrieved exactly."""
    task_id = "test-task-123"
    data = b"public-intelligence-test-data"
    metadata = {"content_type": "text/plain", "created_by": "test-runner"}

    # 1. Save artifact
    art_meta = await temp_artifact_store.save_artifact(
        task_id=task_id, data=data, metadata=metadata
    )

    # 2. Check metadata fields
    expected_checksum = hashlib.sha256(data).hexdigest()
    expected_art_id = f"art_{task_id}_{expected_checksum[:12]}"

    assert art_meta.artifact_id == expected_art_id
    assert art_meta.task_id == task_id
    assert art_meta.checksum == expected_checksum
    assert art_meta.status == "COMMITTED"
    assert art_meta.uri.startswith("file://")
    assert art_meta.metadata == metadata

    # Verify file actually exists on local disk
    filepath = art_meta.uri[len("file://") :]
    assert os.path.exists(filepath)

    # 3. Retrieve and assert correctness
    retrieved_data = await temp_artifact_store.get_artifact(art_meta.uri)
    assert retrieved_data == data


@pytest.mark.asyncio
async def test_get_artifact_file_not_found(
    temp_artifact_store: LocalDiskArtifactStore,
) -> None:
    """Verify that requesting a missing file path raises a FileNotFoundError."""
    # A valid file:// URI pointing to a non-existent path
    non_existent_uri = "file:///tmp/public_intelligence/artifacts/art_non_existent.bin"

    with pytest.raises(FileNotFoundError) as exc_info:
        await temp_artifact_store.get_artifact(non_existent_uri)

    assert "Artifact file not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_artifact_invalid_uri_format(
    temp_artifact_store: LocalDiskArtifactStore,
) -> None:
    """Verify that passing an invalid URI prefix raises a ValueError."""
    invalid_uri = "/tmp/public_intelligence/artifacts/art_test.bin"

    with pytest.raises(ValueError) as exc_info:
        await temp_artifact_store.get_artifact(invalid_uri)

    assert "Invalid URI format" in str(exc_info.value)
