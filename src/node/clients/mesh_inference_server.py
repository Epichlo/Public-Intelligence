"""Serves inference over the Node's outbound Zenoh session.

The Scheduler cannot dial this node: `install.sh` registers `ip_address = 127.0.0.1`, and a
residential router has no inbound port to forward. But the node already holds an outbound
Zenoh session for heartbeats and telemetry, so it declares a *queryable* on that session and
answers inference queries over it. Replies travel back down the connection the node opened,
which is what makes a NAT'd host reachable at all. See `specs/node-reachability.md`.

This is the same work `/infer` does, reached a different way, so it enforces the same things:
a credential is required, it fails closed when none is configured, and a missing model is a
404 rather than a 500. The credential check differs in mechanism only -- an HMAC proof rather
than the token itself, because Zenoh links are plaintext TCP by default. See
`node/core/mesh_protocol.py`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from typing import Any

from node.clients.ollama import OllamaError
from node.core.configuration import Settings
from node.core.mesh_protocol import (
    MeshInferenceRequest,
    MeshRequestError,
    NonceCache,
    encode_chunk,
    encode_done,
    encode_error,
    encode_result,
    infer_key_expr,
    verify_request,
)
from node.models import InferenceRequest

logger = logging.getLogger(__name__)


class ZenohInferenceServer:
    """Answers Scheduler inference queries arriving over Zenoh."""

    def __init__(
        self,
        settings: Settings,
        session: Any | None,
        ollama_client: Any,
    ) -> None:
        """Initialize the server.

        Args:
            settings: Node settings, supplying the node id and the auth token used to
                verify request signatures.
            session: An open Zenoh session, or None when the connection was deferred.
            ollama_client: Client used to run the inference.
        """
        self.settings = settings
        self._session = session
        self._ollama_client = ollama_client
        self._key_expr = infer_key_expr(settings.node_id)
        self._queryable: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Shared across queries on purpose: a nonce must be single-use for the node, not
        # merely within one request, or replay protection would be no protection at all.
        self._nonce_cache = NonceCache()
        self._inflight: set[Future[None]] = set()
        self._inflight_lock = threading.Lock()

    def start(self) -> None:
        """Declare the inference queryable, if there is a session to declare it on."""
        if self._session is None or self._queryable is not None:
            return

        self._loop = asyncio.get_running_loop()
        try:
            self._queryable = self._session.declare_queryable(self._key_expr, self._on_query)
        except Exception as e:
            # A node that cannot serve over the mesh is still a working node over HTTP,
            # so this must not abort startup.
            logger.warning("Failed to declare mesh inference queryable: %s", e)
            self._queryable = None
            return

        logger.info("Mesh inference queryable declared on key: %s", self._key_expr)

    def stop(self) -> None:
        """Undeclare the queryable so no further work is accepted."""
        if self._queryable is None:
            return
        try:
            self._queryable.undeclare()
        except Exception as e:
            logger.error("Error undeclaring mesh inference queryable: %s", e)
        finally:
            self._queryable = None
            self._loop = None
            logger.info("Mesh inference queryable undeclared.")

    def is_serving(self) -> bool:
        """Return whether the node is currently answering mesh inference queries."""
        return self._queryable is not None

    async def wait_for_inflight(self, timeout: float | None = None) -> None:
        """Wait for queries already being answered to finish.

        Used by shutdown so a request in progress is not dropped on the floor, and by
        tests to await work the Zenoh callback dispatched.

        Args:
            timeout: Overall seconds to wait. None waits indefinitely.
        """
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout

        while True:
            with self._inflight_lock:
                pending = [f for f in self._inflight if not f.done()]
            if not pending:
                return
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                return
            await asyncio.wait(
                [asyncio.wrap_future(f) for f in pending],
                timeout=remaining,
            )

    def _on_query(self, query: Any) -> None:
        """Zenoh callback. Runs on a Zenoh thread, not the event loop.

        Inference is async, so the work is handed to the event loop and this returns
        immediately. Zenoh finalises a query when the `Query` object is dropped, so the
        coroutine holding a reference to it is what keeps the query open long enough to
        reply -- see the note in `specs/node-reachability.md`.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            # No loop to run inference on. Answer rather than let the query time out.
            self._reply(query, encode_error("Node is not accepting inference.", status=503))
            return

        future = asyncio.run_coroutine_threadsafe(self._serve(query), loop)
        with self._inflight_lock:
            self._inflight.add(future)
        future.add_done_callback(self._forget_inflight)

    def _forget_inflight(self, future: Future[None]) -> None:
        with self._inflight_lock:
            self._inflight.discard(future)

    async def _serve(self, query: Any) -> None:
        """Verify one query and answer it."""
        try:
            request = self._verify(query)
        except MeshRequestError as e:
            logger.warning("Rejected mesh inference query: %s", e)
            self._reply(query, encode_error(str(e), status=e.status))
            return

        try:
            if request.stream:
                await self._serve_stream(query, request)
            else:
                await self._serve_once(query, request)
        except OllamaError as e:
            # Mirrors the HTTP route: an unpulled model is the caller's problem, anything
            # else is the node's.
            status = 404 if "not found" in str(e).lower() else 500
            logger.error("Mesh inference failed: %s", e)
            self._reply(query, encode_error(str(e), status=status))
        except Exception as e:
            logger.error("Unexpected error serving mesh inference: %s", e, exc_info=True)
            self._reply(query, encode_error(f"Node inference failed: {e}", status=500))

    def _verify(self, query: Any) -> MeshInferenceRequest:
        """Extract and verify the request envelope from a query."""
        payload = getattr(query, "payload", None)
        if payload is None:
            raise MeshRequestError("Mesh inference query carried no payload.", status=400)

        if hasattr(payload, "to_bytes"):
            raw = payload.to_bytes()
        elif isinstance(payload, (bytes, bytearray)):
            raw = bytes(payload)
        else:
            raw = str(payload).encode("utf-8")

        return verify_request(
            raw,
            node_id=self.settings.node_id,
            token=self.settings.network_auth_token,
            nonce_cache=self._nonce_cache,
        )

    async def _serve_once(self, query: Any, request: MeshInferenceRequest) -> None:
        """Answer a non-streaming request with a single reply."""
        response = await self._ollama_client.generate(
            InferenceRequest(model=request.model, prompt=request.prompt, stream=False)
        )
        self._reply(query, encode_result(response.model, response.response))

    async def _serve_stream(self, query: Any, request: MeshInferenceRequest) -> None:
        """Answer a streaming request with one reply per chunk, then a terminator."""
        index = 0
        generator = self._ollama_client.generate_stream(
            InferenceRequest(model=request.model, prompt=request.prompt, stream=True)
        )
        async for chunk in generator:
            self._reply(query, encode_chunk(index, chunk))
            index += 1
        self._reply(query, encode_done())

    def _reply(self, query: Any, payload: bytes) -> None:
        """Send one reply, tolerating a query the querier has already abandoned."""
        try:
            query.reply(self._key_expr, payload)
        except Exception as e:
            logger.warning("Failed to send mesh inference reply: %s", e)
