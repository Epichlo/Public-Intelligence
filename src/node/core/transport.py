"""Transport layer implementing SharedMemory IPC and Backpressured WAN routing."""

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from multiprocessing import shared_memory
from typing import Any

import zenoh

logger = logging.getLogger(__name__)


class SharedMemoryIPC:
    """Zero-copy Shared Memory bridge for local co-located process communication."""

    @staticmethod
    def write_data(data: bytes) -> str:
        """Create a shared memory block and write bytes data to it.

        Args:
            data: Binary payload to write.

        Returns:
            The unique string name of the shared memory block.
        """
        name = f"pi_shm_{uuid.uuid4().hex[:12]}"
        shm = shared_memory.SharedMemory(name=name, create=True, size=len(data) + 4)
        try:
            shm.buf[:4] = len(data).to_bytes(4, "big")  # type: ignore[index]
            shm.buf[4 : 4 + len(data)] = data  # type: ignore[index]
        finally:
            shm.close()
        return name

    @staticmethod
    def read_data(name: str) -> bytes:
        """Read data from an existing shared memory block.

        Args:
            name: String name of the shared memory block.

        Returns:
            The read binary payload.
        """
        shm = shared_memory.SharedMemory(name=name)
        try:
            data_len = int.from_bytes(shm.buf[:4], "big")  # type: ignore[index]
            data = bytes(shm.buf[4 : 4 + data_len])  # type: ignore[index]
        finally:
            shm.close()
        return data

    @staticmethod
    def cleanup(name: str) -> None:
        """Clean up and unlink a shared memory block.

        Args:
            name: String name of the shared memory block.
        """
        try:
            shm = shared_memory.SharedMemory(name=name)
            shm.close()
            shm.unlink()
        except Exception as e:
            logger.debug("SharedMemory cleanup failed for %s: %s", name, e)


class BackpressuredStreamRouter:
    """WAN streaming router enforcing backpressure via sliding window flow control."""

    def __init__(
        self, session_id: str, zenoh_session: zenoh.Session, window_size: int = 4
    ) -> None:
        """Initialize the BackpressuredStreamRouter.

        Args:
            session_id: Unique streaming session ID.
            zenoh_session: Active Zenoh session.
            window_size: Maximum unacknowledged frames allowed in flight.
        """
        self.session_id = session_id
        self.zenoh_session = zenoh_session
        self.window_size = window_size
        self.sent_count = 0
        self.ack_count = 0
        self._ack_event = asyncio.Event()

        self.ack_topic = f"public-intelligence/net/transport/ack/{self.session_id}"
        self.subscriber: zenoh.Subscriber[Any] | None = (
            self.zenoh_session.declare_subscriber(self.ack_topic, self._on_ack)
        )

        self.stream_topic = (
            f"public-intelligence/net/transport/stream/{self.session_id}"
        )
        self.publisher: zenoh.Publisher | None = self.zenoh_session.declare_publisher(
            self.stream_topic
        )

    def _on_ack(self, sample: zenoh.Sample) -> None:
        try:
            payload_str = sample.payload.to_string()
        except AttributeError:
            try:
                payload_str = sample.payload.decode("utf-8")  # type: ignore[attr-defined]
            except (AttributeError, UnicodeDecodeError):
                payload_str = str(sample.payload)

        try:
            data = json.loads(payload_str)
            seq = data.get("seq", 0)
            self.receive_ack(seq)
        except Exception as e:
            logger.debug(
                "Failed to parse ACK json in session %s: %s", self.session_id, e
            )

    def receive_ack(self, ack_seq: int) -> None:
        """Process incoming capacity acknowledgments from the consumer."""
        self.ack_count = max(self.ack_count, ack_seq)
        self._ack_event.set()

    async def send_chunk(
        self,
        chunk: bytes,
        publish_func: Callable[[bytes], Any] | None = None,
        is_local: bool = False,
    ) -> bytes:
        """Send a chunk, blocking if the flow control window is full.

        Args:
            chunk: Binary payload chunk.
            publish_func: Optional coroutine or function to transmit the chunk.
            is_local: Whether the receiver is local (co-located).

        Returns:
            The payload that was transmitted (either the token or the raw chunk).
        """
        while self.sent_count - self.ack_count >= self.window_size:
            self._ack_event.clear()
            await self._ack_event.wait()

        self.sent_count += 1

        payload_to_send: bytes
        if is_local:
            shm_name = SharedMemoryIPC.write_data(chunk)
            payload_to_send = f"shm://{shm_name}".encode()
        else:
            payload_to_send = chunk

        if publish_func is not None:
            res = publish_func(payload_to_send)
            if asyncio.iscoroutine(res):
                await res
        elif self.publisher is not None:
            self.publisher.put(payload_to_send)

        return payload_to_send

    def stop(self) -> None:
        """Undeclare Zenoh subscribers and publishers, and stop the router."""
        if self.subscriber is not None:
            try:
                if hasattr(self.subscriber, "undeclare"):
                    self.subscriber.undeclare()  # type: ignore[no-untyped-call]
            except Exception as e:
                logger.debug("Failed to undeclare subscriber: %s", e)
            self.subscriber = None

        if self.publisher is not None:
            try:
                if hasattr(self.publisher, "undeclare"):
                    self.publisher.undeclare()  # type: ignore[no-untyped-call]
            except Exception as e:
                logger.debug("Failed to undeclare publisher: %s", e)
            self.publisher = None

    @staticmethod
    def get_tensor_topic(task_id: str, stage_index: int) -> str:
        """Generate Zenoh topic string for transmitting tensor payloads.

        Args:
            task_id: Unique pipeline task identifier.
            stage_index: Index of target pipeline stage.

        Returns:
            Zenoh topic string.
        """
        return get_tensor_topic(task_id, stage_index)

    @staticmethod
    def get_tensor_ack_topic(task_id: str, stage_index: int) -> str:
        """Generate Zenoh topic string for receiving tensor payload ACKs.

        Args:
            task_id: Unique pipeline task identifier.
            stage_index: Index of sending pipeline stage.

        Returns:
            Zenoh topic string.
        """
        return get_tensor_ack_topic(task_id, stage_index)


def get_tensor_topic(task_id: str, stage_index: int) -> str:
    """Generate Zenoh topic string for transmitting tensor payloads.

    Args:
        task_id: Unique pipeline task identifier.
        stage_index: Index of target pipeline stage.

    Returns:
        Zenoh topic string.
    """
    return f"public-intelligence/net/tasks/{task_id}/tensors/{stage_index}"


def get_tensor_ack_topic(task_id: str, stage_index: int) -> str:
    """Generate Zenoh topic string for receiving tensor payload ACKs.

    Args:
        task_id: Unique pipeline task identifier.
        stage_index: Index of sending pipeline stage.

    Returns:
        Zenoh topic string.
    """
    return f"public-intelligence/net/tasks/{task_id}/tensors/{stage_index}/ack"
