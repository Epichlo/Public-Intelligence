"""Dispatches inference to a node over the Zenoh mesh.

A node behind residential NAT has no inbound port for the Scheduler to dial, and every
installer-provisioned node registers `ip_address = 127.0.0.1` regardless. It does hold an
outbound Zenoh session open, so this queries the node's inference queryable over that
session and reads the replies back. See `specs/node-reachability.md`.

Two failure modes matter and they are deliberately different exceptions:

- `MeshUnavailableError` -- nothing answered. The node may not have declared a queryable, the
  session may be down. The caller is free to fall back to HTTP.
- `MeshNodeError` -- the node answered, and the answer was a failure. Falling back would
  fail the same way while replacing a precise error (a 404 for an unpulled model) with a
  vague one, so the caller must surface it instead.

Zenoh's Python API is synchronous and delivers replies on its own threads, so replies are
drained on a worker thread and handed to the event loop through a queue. Draining the
blocking iterator, rather than passing a callback, is what makes "no queryable matched"
detectable immediately instead of only via the timeout: the iterator simply ends.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from scheduler.core.mesh_protocol import decode_reply, encode_request, infer_key_expr

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.stdlib.get_logger()

DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_FIRST_REPLY_TIMEOUT_SECONDS = 5.0

# Sentinel pushed onto the bridge queue when the reply iterator is exhausted.
_END = object()

# Drain tasks are held here for their lifetime. Without a strong reference the loop may
# garbage-collect a pending task mid-query, which would silently truncate replies.
_drain_tasks: set[asyncio.Task[None]] = set()


class MeshUnavailableError(Exception):
    """The node did not answer over the mesh. Falling back to HTTP is appropriate."""


class MeshNodeError(Exception):
    """The node answered with a failure. This must be surfaced, not retried elsewhere.

    Attributes:
        status: HTTP-equivalent status the node reported.
    """

    def __init__(self, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.status = status


class MeshStream:
    """An open streaming reply whose first chunk has already arrived.

    The first chunk is consumed before this object is handed back so the caller's decision
    about falling back to HTTP happens while it is still safe to make -- once a chunk has
    been forwarded to the requester, switching transports is no longer possible.
    """

    def __init__(
        self,
        first_chunk: str | None,
        queue: asyncio.Queue[Any],
        node_id: str,
        *,
        finished: bool = False,
    ) -> None:
        self._first_chunk = first_chunk
        self._queue = queue
        self._node_id = node_id
        self._last_index = 0
        self._finished = finished

    def __aiter__(self) -> AsyncIterator[str]:
        return self

    async def __anext__(self) -> str:
        if self._first_chunk is not None:
            chunk = self._first_chunk
            self._first_chunk = None
            return chunk

        if self._finished:
            raise StopAsyncIteration

        while True:
            item = await self._queue.get()

            if item is _END:
                # The node stopped replying without sending its terminator. Reporting this
                # as a clean end would hand back a truncated completion that the caller
                # could not distinguish from a complete one.
                self._finished = True
                raise MeshNodeError(
                    "Node stopped streaming without completing the response.", status=502
                )

            if isinstance(item, BaseException):
                self._finished = True
                raise MeshNodeError(f"Mesh stream failed: {item}", status=502) from item

            if not item.get("ok", False):
                self._finished = True
                raise MeshNodeError(
                    str(item.get("error", "Node reported an error.")),
                    status=int(item.get("status", 500)),
                )

            if item.get("done"):
                self._finished = True
                raise StopAsyncIteration

            index = item.get("i")
            if isinstance(index, int):
                if index < self._last_index:
                    logger.warning(
                        "mesh_stream_out_of_order_chunk",
                        node_id=self._node_id,
                        index=index,
                        previous=self._last_index,
                    )
                self._last_index = index

            chunk = item.get("chunk")
            if chunk is None:
                continue
            return str(chunk)


class MeshInferenceClient:
    """Queries a node's inference queryable over an open Zenoh session."""

    def __init__(
        self,
        session: Any | None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        first_reply_timeout: float = DEFAULT_FIRST_REPLY_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the client.

        Args:
            session: An open Zenoh session, or None if the Scheduler has no mesh.
            timeout: Total seconds a query may run. Must comfortably exceed generation
                time for the largest model a host serves.
            first_reply_timeout: Seconds to wait for the *first* reply before giving up
                and letting the caller fall back. Deliberately much shorter than
                `timeout`: it bounds what an unreachable node costs per request.
        """
        self._session = session
        self._timeout = timeout
        self._first_reply_timeout = first_reply_timeout

    async def infer(
        self,
        *,
        node_id: str,
        token: str,
        model: str,
        prompt: str,
    ) -> dict[str, str]:
        """Run one non-streaming inference on a node.

        Returns:
            The node's `{"model": ..., "response": ...}`.

        Raises:
            MeshUnavailableError: The node did not answer.
            MeshNodeError: The node answered with a failure.
        """
        queue = self._start_query(
            node_id=node_id, token=token, model=model, prompt=prompt, stream=False
        )
        reply = await self._first_reply(queue, node_id)

        if not reply.get("ok", False):
            raise MeshNodeError(
                str(reply.get("error", "Node reported an error.")),
                status=int(reply.get("status", 500)),
            )

        return {
            "model": str(reply.get("model", model)),
            "response": str(reply.get("response", "")),
        }

    async def open_stream(
        self,
        *,
        node_id: str,
        token: str,
        model: str,
        prompt: str,
    ) -> MeshStream:
        """Start a streaming inference and wait for its first chunk.

        Returns:
            A `MeshStream` that yields the first chunk and everything after it.

        Raises:
            MeshUnavailableError: The node did not answer. Nothing has been sent to the
                requester yet, so the caller may still fall back to HTTP.
            MeshNodeError: The node answered with a failure.
        """
        queue = self._start_query(
            node_id=node_id, token=token, model=model, prompt=prompt, stream=True
        )
        reply = await self._first_reply(queue, node_id)

        if not reply.get("ok", False):
            raise MeshNodeError(
                str(reply.get("error", "Node reported an error.")),
                status=int(reply.get("status", 500)),
            )

        if reply.get("done"):
            # A complete but empty generation -- a valid answer, so it must not look like
            # an unreachable node. Represent it as a stream that yields nothing.
            return MeshStream(None, queue, node_id, finished=True)

        chunk = reply.get("chunk")
        if chunk is None:
            raise MeshNodeError("Node sent a reply with no content.", status=502)

        return MeshStream(str(chunk), queue, node_id)

    def _start_query(
        self,
        *,
        node_id: str,
        token: str,
        model: str,
        prompt: str,
        stream: bool,
    ) -> asyncio.Queue[Any]:
        """Send the query and start draining replies into an asyncio queue.

        Raises:
            MeshUnavailableError: If there is no session, or Zenoh refused the query.
        """
        if self._session is None:
            raise MeshUnavailableError("Scheduler has no Zenoh session.")

        import zenoh

        payload = encode_request(
            node_id=node_id,
            model=model,
            prompt=prompt,
            stream=stream,
            token=token,
        )

        try:
            replies = self._session.get(
                infer_key_expr(node_id),
                payload=payload,
                timeout=self._timeout,
                # Required, not a preference: every streamed chunk replies on the same key
                # expression, and the default AUTO consolidation may drop samples sharing
                # a key -- which would silently discard tokens.
                consolidation=zenoh.ConsolidationMode.NONE,
            )
        except Exception as e:
            raise MeshUnavailableError(f"Mesh query could not be sent: {e}") from e

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()

        def drain() -> None:
            """Consume the blocking reply iterator on a worker thread."""
            try:
                for reply in replies:
                    error = getattr(reply, "err", None)
                    if error is not None:
                        # A zenoh-level `reply_err`. Our protocol never sends one, so this
                        # is transport-shaped and the caller may fall back.
                        loop.call_soon_threadsafe(
                            queue.put_nowait, MeshUnavailableError("Node replied with an error.")
                        )
                        continue

                    sample = getattr(reply, "ok", None)
                    if sample is None:
                        continue

                    try:
                        raw = sample.payload.to_bytes()
                    except AttributeError:
                        raw = bytes(sample.payload)

                    try:
                        decoded = decode_reply(raw)
                    except Exception as e:
                        loop.call_soon_threadsafe(
                            queue.put_nowait, MeshUnavailableError(f"Undecodable mesh reply: {e}")
                        )
                        continue

                    loop.call_soon_threadsafe(queue.put_nowait, decoded)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, MeshUnavailableError(str(e)))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _END)

        # The caller waits on the queue, never on this task, so it needs an owner for its
        # whole life -- see `_drain_tasks`.
        task = asyncio.ensure_future(asyncio.to_thread(drain))
        _drain_tasks.add(task)
        task.add_done_callback(_drain_tasks.discard)
        return queue

    async def _first_reply(self, queue: asyncio.Queue[Any], node_id: str) -> dict[str, Any]:
        """Await the first reply, or declare the node unreachable over the mesh."""
        try:
            item = await asyncio.wait_for(queue.get(), timeout=self._first_reply_timeout)
        except TimeoutError as e:
            raise MeshUnavailableError(
                f"Node {node_id} did not answer over the mesh within {self._first_reply_timeout}s."
            ) from e

        if item is _END:
            raise MeshUnavailableError(f"No queryable answered for node {node_id}.")

        if isinstance(item, MeshUnavailableError):
            raise item

        if isinstance(item, BaseException):
            raise MeshUnavailableError(str(item)) from item

        return item
