"""Transport layer implementing SharedMemory IPC and Backpressured WAN routing."""

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import Awaitable, Callable
from multiprocessing import shared_memory
from typing import Any

import zenoh

from node.models.sharding import TensorPayload

logger = logging.getLogger(__name__)


# Shared memory blocks created by this process, held open until cleanup().
#
# POSIX keeps a segment alive in /dev/shm until it is explicitly unlinked, so the
# creating handle can be closed immediately. Windows refcounts the underlying
# mapping and destroys it as soon as the *last* handle closes -- so releasing the
# creating handle inside write_data() destroyed the block before any reader could
# attach it. Retaining the handle until cleanup() gives both platforms the same
# lifetime: the block lives until explicitly released.
#
# Blocks whose cleanup() is never called stay resident for the life of the
# process; callers own that release, as they did before.
_OPEN_BLOCKS: dict[str, shared_memory.SharedMemory] = {}
_OPEN_BLOCKS_LOCK = threading.Lock()


class SharedMemoryIPC:
    """Zero-copy Shared Memory bridge for local co-located process communication."""

    @staticmethod
    def write_data(data: bytes) -> str:
        """Create a shared memory block and write bytes data to it.

        The creating handle is retained until `cleanup` so the block survives on
        Windows, where closing every handle destroys the mapping.

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
        except Exception:
            shm.close()
            shm.unlink()
            raise

        with _OPEN_BLOCKS_LOCK:
            _OPEN_BLOCKS[name] = shm
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
        """Release and unlink a shared memory block.

        Closes the retained creating handle when this process owns the block. On
        Windows that final close destroys the mapping; on POSIX `unlink` removes
        the /dev/shm entry. Blocks created by another process are attached first
        so they can still be unlinked.

        Args:
            name: String name of the shared memory block.
        """
        with _OPEN_BLOCKS_LOCK:
            shm = _OPEN_BLOCKS.pop(name, None)

        try:
            if shm is None:
                shm = shared_memory.SharedMemory(name=name)
            shm.close()
            shm.unlink()
        except Exception as e:
            logger.debug("SharedMemory cleanup failed for %s: %s", name, e)


class BackpressuredStreamRouter:
    """WAN streaming router enforcing backpressure via sliding window flow control."""

    def __init__(self, session_id: str, zenoh_session: zenoh.Session, window_size: int = 4) -> None:
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
        self._tensor_ack_subs: dict[str, Any] = {}

        self.ack_topic = f"public-intelligence/net/transport/ack/{self.session_id}"
        self.subscriber: zenoh.Subscriber[Any] | None = self.zenoh_session.declare_subscriber(
            self.ack_topic, self._on_ack
        )

        self.stream_topic = f"public-intelligence/net/transport/stream/{self.session_id}"
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
            logger.debug("Failed to parse ACK json in session %s: %s", self.session_id, e)

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

    async def send_tensor_payload(
        self,
        payload: TensorPayload,
        publish_func: Callable[[str, bytes], Awaitable[None]] | None = None,
        is_local: bool = False,
    ) -> None:
        """Send framed TensorPayload using backpressured flow control.

        Args:
            payload: TensorPayload containing activations and metadata.
            publish_func: Optional publisher taking (topic, payload_bytes).
            is_local: Whether target is co-located on same machine.
        """
        raw_frame = payload.to_framed_bytes()
        target_topic = get_tensor_topic(payload.task_id, payload.target_stage_index)

        ack_topic = get_tensor_ack_topic(payload.task_id, payload.stage_index)
        if ack_topic not in self._tensor_ack_subs:
            sub = self.zenoh_session.declare_subscriber(ack_topic, self._on_ack)
            self._tensor_ack_subs[ack_topic] = sub

        if publish_func is not None:

            async def _pub_wrapper(data: bytes) -> None:
                res = publish_func(target_topic, data)
                if asyncio.iscoroutine(res):
                    await res

            await self.send_chunk(raw_frame, publish_func=_pub_wrapper, is_local=is_local)
        else:
            pub = self.zenoh_session.declare_publisher(target_topic)
            try:

                def _pub(data: bytes) -> None:
                    pub.put(data)

                await self.send_chunk(raw_frame, publish_func=_pub, is_local=is_local)
            finally:
                if hasattr(pub, "undeclare"):
                    try:
                        pub.undeclare()  # type: ignore[no-untyped-call]
                    except Exception as e:
                        logger.debug("Failed to undeclare temporary tensor publisher: %s", e)

    async def start_tensor_listener(
        self,
        task_id: str,
        stage_index: int,
        on_payload: Callable[[TensorPayload], Awaitable[None]],
    ) -> Any:
        """Subscribe to stage tensor channel and process incoming activation payloads.

        Args:
            task_id: Unique pipeline task identifier.
            stage_index: Target stage index to listen on.
            on_payload: Async callback function invoked with deserialized TensorPayload.

        Returns:
            The Zenoh subscriber object.
        """
        stream_topic = get_tensor_topic(task_id, stage_index)
        loop = asyncio.get_running_loop()

        def _on_sample(sample: zenoh.Sample) -> None:
            try:
                payload_str = sample.payload.to_string()
            except AttributeError:
                try:
                    payload_str = sample.payload.decode("utf-8")  # type: ignore[attr-defined]
                except (AttributeError, UnicodeDecodeError):
                    payload_str = str(sample.payload)

            raw_bytes: bytes
            if payload_str.startswith("shm://"):
                shm_name = payload_str[6:]
                try:
                    raw_bytes = SharedMemoryIPC.read_data(shm_name)
                except Exception as e:
                    logger.error("Failed to read from shared memory %s: %s", shm_name, e)
                    return
                finally:
                    SharedMemoryIPC.cleanup(shm_name)
            else:
                try:
                    if isinstance(sample.payload, bytes):
                        raw_bytes = sample.payload
                    elif isinstance(sample.payload, str):
                        raw_bytes = sample.payload.encode("utf-8")
                    else:
                        raw_bytes = sample.payload.to_bytes()
                except Exception:
                    raw_bytes = payload_str.encode("utf-8")

            try:
                tensor_payload = TensorPayload.from_framed_bytes(raw_bytes)
            except Exception as e:
                logger.error("Failed to deserialize TensorPayload: %s", e)
                return

            res = on_payload(tensor_payload)
            if asyncio.iscoroutine(res) and loop.is_running():
                loop.call_soon_threadsafe(lambda: asyncio.create_task(res))

            ack_topic = get_tensor_ack_topic(task_id, tensor_payload.stage_index)
            self.ack_count += 1
            ack_payload = json.dumps({"seq": self.ack_count})
            try:
                self.zenoh_session.put(ack_topic, ack_payload)
            except Exception as e:
                logger.debug("Failed to send tensor ACK on %s: %s", ack_topic, e)

        return self.zenoh_session.declare_subscriber(stream_topic, _on_sample)

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

        for topic, sub in list(self._tensor_ack_subs.items()):
            try:
                if hasattr(sub, "undeclare"):
                    sub.undeclare()
            except Exception as e:
                logger.debug("Failed to undeclare tensor ACK subscriber for %s: %s", topic, e)
        self._tensor_ack_subs.clear()

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


class BackpressuredReceiver:
    """Receiver-side flow control helper to send acknowledgments back to the sender."""

    def __init__(self, session_id: str, zenoh_session: zenoh.Session) -> None:
        """Initialize the BackpressuredReceiver.

        Args:
            session_id: Unique streaming session ID.
            zenoh_session: Active Zenoh session.
        """
        self.session_id = session_id
        self.zenoh_session = zenoh_session
        self.ack_topic = f"public-intelligence/net/transport/ack/{self.session_id}"
        self.processed_count = 0
        self.subscriber: zenoh.Subscriber[Any] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def send_ack(self) -> None:
        """Publish a processing capacity signal (ACK) back to the stream router."""
        self.processed_count += 1
        payload = json.dumps({"seq": self.processed_count})
        self.zenoh_session.put(self.ack_topic, payload)

    def start(self, on_chunk: Callable[[bytes], Any]) -> None:
        """Subscribe to the stream topic and process incoming chunks."""
        self.stream_topic = f"public-intelligence/net/transport/stream/{self.session_id}"
        self._loop = asyncio.get_running_loop()

        def _on_sample(sample: zenoh.Sample) -> None:
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
                try:
                    data = SharedMemoryIPC.read_data(shm_name)
                except Exception as e:
                    logger.error("Failed to read from shared memory %s: %s", shm_name, e)
                    return
                finally:
                    SharedMemoryIPC.cleanup(shm_name)
            else:
                try:
                    if isinstance(sample.payload, bytes):
                        data = sample.payload
                    elif isinstance(sample.payload, str):
                        data = sample.payload.encode("utf-8")
                    else:
                        data = sample.payload.to_bytes()
                except Exception:
                    data = payload_str.encode("utf-8")

            res = on_chunk(data)
            if asyncio.iscoroutine(res) and self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(lambda: asyncio.create_task(res))

            self.send_ack()

        self.subscriber = self.zenoh_session.declare_subscriber(self.stream_topic, _on_sample)

    async def send_tensor_payload(
        self,
        payload: TensorPayload,
        publish_func: Callable[[str, bytes], Awaitable[None]] | None = None,
        is_local: bool = False,
    ) -> None:
        """Send framed TensorPayload using backpressured flow control.

        Args:
            payload: TensorPayload containing activations and metadata.
            publish_func: Optional publisher taking (topic, payload_bytes).
            is_local: Whether target is co-located on same machine.
        """
        router = BackpressuredStreamRouter(f"rec-send-{uuid.uuid4().hex[:8]}", self.zenoh_session)
        try:
            await router.send_tensor_payload(payload, publish_func=publish_func, is_local=is_local)
        finally:
            router.stop()

    async def start_tensor_listener(
        self,
        task_id: str,
        stage_index: int,
        on_payload: Callable[[TensorPayload], Awaitable[None]],
    ) -> Any:
        """Subscribe to stage tensor channel and process incoming activation payloads.

        Args:
            task_id: Unique pipeline task identifier.
            stage_index: Target stage index to listen on.
            on_payload: Async callback function invoked with deserialized TensorPayload.

        Returns:
            The Zenoh subscriber object.
        """
        stream_topic = get_tensor_topic(task_id, stage_index)
        loop = asyncio.get_running_loop()
        self._loop = loop

        def _on_sample(sample: zenoh.Sample) -> None:
            if hasattr(sample.payload, "to_bytes"):
                raw_bytes = sample.payload.to_bytes()
            elif isinstance(sample.payload, bytes):
                raw_bytes = sample.payload
            elif isinstance(sample.payload, str):
                raw_bytes = sample.payload.encode("utf-8")
            else:
                raw_bytes = bytes(sample.payload)

            if raw_bytes.startswith(b"shm://"):
                shm_name = raw_bytes[6:].decode("utf-8", errors="ignore")
                try:
                    raw_bytes = SharedMemoryIPC.read_data(shm_name)
                except Exception as e:
                    logger.error("Failed to read from shared memory %s: %s", shm_name, e)
                    return
                finally:
                    SharedMemoryIPC.cleanup(shm_name)

            try:
                tensor_payload = TensorPayload.from_framed_bytes(raw_bytes)
            except Exception as e:
                logger.error("Failed to deserialize TensorPayload: %s", e)
                return

            res = on_payload(tensor_payload)
            if asyncio.iscoroutine(res) and loop.is_running():
                loop.call_soon_threadsafe(lambda: asyncio.create_task(res))

            ack_topic = get_tensor_ack_topic(task_id, tensor_payload.stage_index)
            self.processed_count += 1
            ack_payload = json.dumps({"seq": self.processed_count})
            try:
                self.zenoh_session.put(ack_topic, ack_payload)
            except Exception as e:
                logger.debug("Failed to send tensor ACK on %s: %s", ack_topic, e)

        subscriber = self.zenoh_session.declare_subscriber(stream_topic, _on_sample)
        self.subscriber = subscriber
        return subscriber

    def stop(self) -> None:
        """Stop subscription and clean up."""
        if self.subscriber is not None:
            try:
                if hasattr(self.subscriber, "undeclare"):
                    self.subscriber.undeclare()  # type: ignore[no-untyped-call]
            except Exception as e:
                logger.debug("Failed to undeclare subscriber: %s", e)
            self.subscriber = None


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
