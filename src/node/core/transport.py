"""Transport layer implementing SharedMemory IPC and Backpressured WAN routing."""

import asyncio
import json
import uuid
from collections.abc import Callable
from multiprocessing import shared_memory
from typing import Any

import zenoh


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
        except Exception:
            pass


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
        self.subscriber: zenoh.Subscriber[Any] | None = self.zenoh_session.declare_subscriber(
            self.ack_topic, self._on_ack
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
        except Exception:
            pass

    def receive_ack(self, ack_seq: int) -> None:
        """Process incoming capacity acknowledgments from the consumer."""
        self.ack_count = max(self.ack_count, ack_seq)
        self._ack_event.set()

    async def send_chunk(
        self, chunk: bytes, publish_func: Callable[[bytes], Any]
    ) -> None:
        """Send a chunk, blocking if the flow control window is full.

        Args:
            chunk: Binary payload chunk.
            publish_func: Coroutine or function to transmit the chunk.
        """
        while self.sent_count - self.ack_count >= self.window_size:
            self._ack_event.clear()
            await self._ack_event.wait()

        self.sent_count += 1
        res = publish_func(chunk)
        if asyncio.iscoroutine(res):
            await res

    def stop(self) -> None:
        """Undeclare Zenoh subscribers and stop the router."""
        if self.subscriber is not None:
            try:
                if hasattr(self.subscriber, "undeclare"):
                    self.subscriber.undeclare()  # type: ignore[no-untyped-call]
            except Exception:
                pass
            self.subscriber = None
