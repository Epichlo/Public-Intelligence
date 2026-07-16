"""Unit and integration tests for the Transport layer."""

import asyncio
import json

import pytest
import zenoh

from node.core.transport import BackpressuredStreamRouter, SharedMemoryIPC


def test_shared_memory_ipc_lifecycle() -> None:
    """Verify SharedMemoryIPC write, read, and cleanup lifecycle."""
    payload = b"hello shared memory zero copy payload"
    shm_name = SharedMemoryIPC.write_data(payload)

    try:
        assert shm_name.startswith("pi_shm_")

        # Read back data
        read_payload = SharedMemoryIPC.read_data(shm_name)
        assert read_payload == payload
    finally:
        # Clean up
        SharedMemoryIPC.cleanup(shm_name)

        # Attempting to read after cleanup should fail
        with pytest.raises(FileNotFoundError):
            SharedMemoryIPC.read_data(shm_name)


@pytest.mark.anyio
async def test_backpressured_stream_router_sliding_window() -> None:
    """Verify BackpressuredStreamRouter blocks when window capacity is full."""
    # Open local Zenoh session
    config = zenoh.Config()
    # Disable multicast scouting to prevent local network interference in test run
    config.insert_json5("scouting/multicast/enabled", "false")

    with zenoh.open(config) as session:
        session_id = "test-session-backpressure"
        router = BackpressuredStreamRouter(session_id, session, window_size=2)

        sent_chunks = []

        async def dummy_publish(chunk: bytes) -> None:
            sent_chunks.append(chunk)

        # Send 2 chunks (should complete instantly within the window size of 2)
        await router.send_chunk(b"chunk1", dummy_publish)
        await router.send_chunk(b"chunk2", dummy_publish)
        assert len(sent_chunks) == 2

        # Sending 3rd chunk should block because window is full
        # (sent_count - ack_count = 2)
        send_task = asyncio.create_task(router.send_chunk(b"chunk3", dummy_publish))

        # Wait a short moment to ensure the task is running and blocked
        await asyncio.sleep(0.2)
        assert not send_task.done()
        assert len(sent_chunks) == 2

        # Simulate ACK from consumer (acknowledges sequence 1)
        router.receive_ack(1)

        # Wait for the task to unblock and finish
        await asyncio.wait_for(send_task, timeout=2.0)

        assert send_task.done()
        assert len(sent_chunks) == 3
        assert sent_chunks[2] == b"chunk3"

        router.stop()
