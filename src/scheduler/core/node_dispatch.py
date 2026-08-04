"""Chooses how to reach a node, and reaches it.

Two transports exist and they are not interchangeable:

- **Mesh (Zenoh query).** The only one that works for a node behind residential NAT. Used
  when the registry has *observed* that node on the mesh.
- **HTTP (dial `ip_address`).** Works for same-host and containerised deployments. For an
  installer-provisioned node `ip_address` is `127.0.0.1`, so this dials the Scheduler
  itself -- which is why it cannot be the only option. Kept as the fallback.

Both `openai.py` and `schedule.py` proxy to nodes, and ROADMAP 0.1 shipped half-fixed
because only one of them was updated. Routing lives here so there is one place to change
and one place to test.

See `specs/node-reachability.md`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from scheduler.core.mesh_inference_client import MeshNodeError, MeshUnavailableError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.stdlib.get_logger()


class NodeDispatchError(Exception):
    """A node failed to serve a request, with the status the caller should report.

    Attributes:
        status: HTTP status for the response.
        detail: Message safe to return to the caller.
    """

    def __init__(self, detail: str, status: int = 502) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def node_infer_url(ip_address: str, node_api_port: int) -> str:
    """Build the HTTP `/infer` URL for a node."""
    if ip_address.startswith(("http://", "https://")):
        return f"{ip_address}/infer"
    return f"http://{ip_address}:{node_api_port}/infer"


def _resolve_token(registry: Any, node_id: str, settings: Any) -> str | None:
    """Return the credential to present to a node.

    Prefers the per-node token captured at registration (ROADMAP 0.1), falling back to a
    fleet-wide token for deployments configured that way.
    """
    return registry.get_node_token(node_id) or settings.network_auth_token


def _use_mesh(registry: Any, node_id: str, settings: Any, mesh_client: Any) -> bool:
    """Decide whether to try the mesh for this node."""
    if mesh_client is None:
        return False
    if not getattr(settings, "mesh_inference_enabled", True):
        return False
    return registry.is_mesh_reachable(node_id)


async def infer_once(
    *,
    registry: Any,
    settings: Any,
    mesh_client: Any,
    node_id: str,
    ip_address: str,
    model: str,
    prompt: str,
) -> dict[str, str]:
    """Run one non-streaming inference on a node, over whichever transport works.

    Returns:
        `{"model": ..., "response": ...}`.

    Raises:
        NodeDispatchError: The node could not serve the request. `status` carries the
            node's own status where it reported one.
    """
    token = _resolve_token(registry, node_id, settings)
    if not token:
        logger.warning("node_infer_no_credential", node_id=node_id)

    if _use_mesh(registry, node_id, settings, mesh_client):
        try:
            result = await mesh_client.infer(
                node_id=node_id, token=token or "", model=model, prompt=prompt
            )
            logger.info("node_dispatch_mesh", node_id=node_id, model=model)
            return result
        except MeshNodeError as e:
            # The node answered. Retrying over HTTP would fail the same way and would
            # replace a precise status with a vague one.
            raise NodeDispatchError(str(e), status=e.status) from e
        except MeshUnavailableError as e:
            logger.info("node_dispatch_mesh_unavailable", node_id=node_id, error=str(e))

    return await _http_infer_once(
        settings=settings,
        node_id=node_id,
        ip_address=ip_address,
        model=model,
        prompt=prompt,
        token=token,
    )


async def _http_infer_once(
    *,
    settings: Any,
    node_id: str,
    ip_address: str,
    model: str,
    prompt: str,
    token: str | None,
) -> dict[str, str]:
    """Dial the node's HTTP `/infer`."""
    url = node_infer_url(ip_address, settings.node_api_port)
    headers = {"X-Network-Auth-Token": token} if token else {}
    payload = {"model": model, "prompt": prompt, "stream": False}

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.RequestError as e:
            logger.error("node_infer_request_failed", url=url, error=str(e))
            raise NodeDispatchError(
                f"Failed to communicate with compute node: {e}", status=502
            ) from e

        if response.status_code != 200:
            raise NodeDispatchError(
                f"Compute node error: {response.text}", status=response.status_code
            )

        data = response.json()

    logger.info("node_dispatch_http", node_id=node_id, model=model)
    return {
        "model": str(data.get("model", model)),
        "response": str(data.get("response", "")),
    }


async def open_inference_stream(
    *,
    registry: Any,
    settings: Any,
    mesh_client: Any,
    node_id: str,
    ip_address: str,
    model: str,
    prompt: str,
) -> AsyncIterator[str]:
    """Start a streaming inference and return an iterator of token text.

    The transport decision is made before this returns, so a caller that has not yet sent
    anything to the requester can still be handed a clean failure. Once iteration starts
    there is no falling back -- bytes may already be on their way out.

    Returns:
        An async iterator of token strings, already stripped of any SSE framing.

    Raises:
        NodeDispatchError: The node reported a failure before producing any output.
    """
    token = _resolve_token(registry, node_id, settings)
    if not token:
        logger.warning("node_infer_no_credential", node_id=node_id)

    if _use_mesh(registry, node_id, settings, mesh_client):
        try:
            stream = await mesh_client.open_stream(
                node_id=node_id, token=token or "", model=model, prompt=prompt
            )
            logger.info("node_dispatch_mesh_stream", node_id=node_id, model=model)
            return _iterate_mesh_stream(stream)
        except MeshNodeError as e:
            raise NodeDispatchError(str(e), status=e.status) from e
        except MeshUnavailableError as e:
            logger.info("node_dispatch_mesh_unavailable", node_id=node_id, error=str(e))

    logger.info("node_dispatch_http_stream", node_id=node_id, model=model)
    return _http_stream(
        settings=settings,
        ip_address=ip_address,
        model=model,
        prompt=prompt,
        token=token,
    )


async def _iterate_mesh_stream(stream: Any) -> AsyncIterator[str]:
    """Adapt a `MeshStream` to a plain token iterator.

    A `MeshNodeError` raised part-way through becomes a `NodeDispatchError` so callers
    have one exception type to handle regardless of transport.
    """
    try:
        async for chunk in stream:
            yield chunk
    except MeshNodeError as e:
        raise NodeDispatchError(str(e), status=e.status) from e


async def _http_stream(
    *,
    settings: Any,
    ip_address: str,
    model: str,
    prompt: str,
    token: str | None,
) -> AsyncIterator[str]:
    """Stream from the node's HTTP `/infer`, unwrapping its line framing.

    The node emits raw lines, optionally SSE-prefixed, optionally JSON, and prefixes the
    stream with a `session_id:` line when its Zenoh transport router is active. That
    unwrapping used to live in the gateway's SSE generator; it belongs with the transport
    that produces it, so the gateway sees the same clean token strings either way.
    """
    url = node_infer_url(ip_address, settings.node_api_port)
    headers = {"X-Network-Auth-Token": token} if token else {}
    payload = {"model": model, "prompt": prompt, "stream": True}

    async with (
        httpx.AsyncClient(timeout=60.0) as client,
        client.stream("POST", url, json=payload, headers=headers) as response,
    ):
        if response.status_code != 200:
            error_text = await response.aread()
            raise NodeDispatchError(
                error_text.decode("utf-8", errors="ignore"),
                status=response.status_code,
            )

        async for line in response.aiter_lines():
            if not line.strip():
                continue

            clean = line[6:].strip() if line.startswith("data: ") else line
            if clean.startswith("session_id:"):
                continue

            try:
                parsed = json.loads(clean)
            except json.JSONDecodeError:
                yield clean
                continue

            if isinstance(parsed, dict):
                value = parsed.get("response", parsed.get("text", clean))
                yield "" if value is None else str(value)
            else:
                yield clean
