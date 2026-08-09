"""Unit and integration tests for the Transport layer."""

import asyncio
import logging

import pytest
import zenoh
from node.models.sharding import TensorPayload

from experimental.node.transport import (
    BackpressuredReceiver,
    BackpressuredStreamRouter,
    SharedMemoryIPC,
)

logger = logging.getLogger(__name__)


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


@pytest.mark.anyio
async def test_local_shared_memory_over_zenoh_and_backpressure() -> None:
    """Validate that local shm tokens are passed over Zenoh with backpressure."""
    config = zenoh.Config()
    config.insert_json5("scouting/multicast/enabled", "false")

    with zenoh.open(config) as session:
        session_id = "test-session-shm-loop"
        router = BackpressuredStreamRouter(session_id, session, window_size=2)

        received_chunks = []
        received_acks = []

        # Setup receiver subscriber manually for testing the node side
        stream_topic = f"public-intelligence/net/transport/stream/{session_id}"
        ack_topic = f"public-intelligence/net/transport/ack/{session_id}"

        def stream_callback(sample: zenoh.Sample) -> None:
            try:
                payload_str = sample.payload.to_string()
            except AttributeError:
                try:
                    payload_str = sample.payload.decode("utf-8")  # type: ignore[attr-defined]
                except (AttributeError, UnicodeDecodeError):
                    payload_str = str(sample.payload)

            data: bytes
            if payload_str.startswith("shm://"):
                shm_name = payload_str[6:]
                # Read data directly from shared memory (zero-copy)
                data = SharedMemoryIPC.read_data(shm_name)
                SharedMemoryIPC.cleanup(shm_name)
            else:
                data = payload_str.encode("utf-8")

            received_chunks.append(data)

            # Auto-ACK back
            ack_seq = len(received_chunks)
            session.put(ack_topic, f'{{"seq": {ack_seq}}}')
            received_acks.append(ack_seq)

        stream_sub = session.declare_subscriber(stream_topic, stream_callback)

        # Wait a brief moment for subscription establishment
        await asyncio.sleep(0.1)

        # Send chunk via router in is_local=True mode.
        # It should write to shared memory, send only the token over Zenoh,
        # and the receiver reads it directly.
        token_bytes = await router.send_chunk(b"hello-local-zero-copy", is_local=True)
        assert token_bytes.startswith(b"shm://")

        # Wait for delivery
        await asyncio.sleep(0.2)

        assert len(received_chunks) == 1
        assert received_chunks[0] == b"hello-local-zero-copy"
        assert len(received_acks) == 1

        # Clean up subscriber
        stream_sub.undeclare()
        router.stop()


@pytest.mark.anyio
async def test_send_tensor_payload_and_listener() -> None:
    """Verify send_tensor_payload and start_tensor_listener over Zenoh tensor topics."""
    config = zenoh.Config()
    config.insert_json5("scouting/multicast/enabled", "false")

    with zenoh.open(config) as session:
        router = BackpressuredStreamRouter("tensor-router-session", session)
        receiver = BackpressuredReceiver("tensor-receiver-session", session)

        received_payloads: list[TensorPayload] = []

        async def on_payload(payload: TensorPayload) -> None:
            received_payloads.append(payload)

        sub = await receiver.start_tensor_listener("task-tp-1", 1, on_payload)
        await asyncio.sleep(0.1)

        send_payload = TensorPayload(
            task_id="task-tp-1",
            stage_index=0,
            target_stage_index=1,
            is_split_inference=True,
            tensor_type="intermediate_activation",
            data=b"activation-vector-bytes-1234",
            shape=[1, 4, 128],
            dtype="float32",
            sequence_id=1,
        )

        await router.send_tensor_payload(send_payload)
        await asyncio.sleep(0.3)

        assert len(received_payloads) == 1
        restored = received_payloads[0]
        assert restored.task_id == "task-tp-1"
        assert restored.stage_index == 0
        assert restored.target_stage_index == 1
        assert restored.is_split_inference is True
        assert restored.tensor_type == "intermediate_activation"
        assert restored.data == b"activation-vector-bytes-1234"
        assert restored.shape == [1, 4, 128]
        assert restored.sequence_id == 1

        try:
            if hasattr(sub, "undeclare"):
                sub.undeclare()
        except Exception:
            pass
        router.stop()
        receiver.stop()
