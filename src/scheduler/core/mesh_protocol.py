"""Wire contract for inference dispatched over the Zenoh mesh.

The Scheduler cannot dial a node behind residential NAT: `install.sh` leaves every node
registering `ip_address = 127.0.0.1`, and a home router has no inbound port to forward.
The node does already open an outbound Zenoh session and hold it open, for heartbeats,
liveliness, and telemetry. Inference rides that same session -- the node declares a
queryable, the Scheduler queries it, and replies travel back down the connection the node
itself established. See `specs/node-reachability.md`.

This module is the envelope both sides must agree on, and it is duplicated
BYTE-IDENTICALLY at:

    Node/src/node/core/mesh_protocol.py
    Scheduler/src/scheduler/core/mesh_protocol.py

joining the modules CLAUDE.md warns about (`quantization.py`, `local_boundary.py`,
`kv_cache.py`, `transport.py`). There is no shared installable package to hold it --
`src/shared/` is an unimported third copy of the artifact store, not a dependency of
either service. Unlike those four, this pair is guarded: `tests/test_mesh_protocol_parity.py`
in the root suite -- the only interpreter where both packages import -- fails if the two
files diverge or stop interoperating. Change one, change the other.

## Authentication

The HTTP `/infer` path sends the node's actual credential in `X-Network-Auth-Token`.
Putting that in a mesh payload would expose it to the router operator and to anyone who
can read the link, since Zenoh links are plaintext TCP under the default config. So a mesh
request carries a proof of possession instead: an HMAC over the request, keyed by the
token. The token never crosses the wire, and because the signature covers a digest of the
body, a captured request cannot be edited into a different prompt.

Verification fails CLOSED, matching `node/api/auth.py`: a node with no token configured
serves nothing over the mesh either.

Replay is bounded two ways -- a +/-30s freshness window (the same one
`zenoh_router._process_telemetry` applies to telemetry) and single-use nonces. Telemetry
does not do the nonce half, so a captured telemetry envelope stays replayable inside its
window; that is a pre-existing gap in a different envelope, not something fixed here.

What is deliberately NOT protected: the prompt and the completion cross the router in
plaintext, exactly as they do today over `http://`. The HMAC keeps the credential off the
wire; it does not make the mesh confidential. TLS on Zenoh links is its own piece of work.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

# Key expression a node serves inference on. `{node_id}` is a concrete segment, so one
# node's queryable never matches another's query.
INFER_KEY_TEMPLATE = "public-intelligence/net/{node_id}/infer"

# Requests older or newer than this are refused. Matches the telemetry window in
# `zenoh_router._process_telemetry` so there is one staleness rule to reason about.
MAX_CLOCK_SKEW_SECONDS = 30.0

# Nonces retained for single-use enforcement. At 4096 entries this holds far more than
# one skew window's worth of traffic for any plausible single-node request rate, so a
# nonce is never evicted while it could still be replayed.
NONCE_CACHE_SIZE = 4096

PROTOCOL_VERSION = 1


class MeshRequestError(Exception):
    """A mesh inference request failed verification and must not be served.

    Attributes:
        status: HTTP-equivalent status to report back to the caller, so the mesh path
            and the HTTP path describe the same failure the same way.
    """

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class MeshInferenceRequest:
    """A verified inference request received over the mesh."""

    node_id: str
    model: str
    prompt: str
    stream: bool


def infer_key_expr(node_id: str) -> str:
    """Return the Zenoh key expression a given node serves inference on."""
    return INFER_KEY_TEMPLATE.format(node_id=node_id)


def _canonical_timestamp(timestamp: float) -> str:
    """Render a timestamp the one way both signer and verifier must agree on.

    Signing the raw float would make the signature depend on float repr surviving a
    JSON round-trip. Fixed precision removes that dependency.
    """
    return f"{timestamp:.6f}"


def _body_digest(model: str, prompt: str, stream: bool) -> str:
    """Digest the parts of the request the signature must bind to.

    NUL-separated because it cannot occur in any of the fields, so no combination of
    model and prompt can be re-split into a different request with the same digest.
    `stream` is rendered as 1/0 rather than Python's `True`/`False` to keep the contract
    language-independent.
    """
    material = f"{model}\0{prompt}\0{'1' if stream else '0'}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _signature(
    token: str,
    node_id: str,
    nonce: str,
    timestamp: float,
    body_digest: str,
) -> str:
    """Compute the proof of possession for one request."""
    message = f"{node_id}\n{nonce}\n{_canonical_timestamp(timestamp)}\n{body_digest}"
    return hmac.new(
        token.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class NonceCache:
    """Bounded single-use nonce store.

    Thread-safe because Zenoh dispatches queryable callbacks from its own thread pool,
    and verification runs on that thread rather than the event loop.
    """

    def __init__(self, capacity: int = NONCE_CACHE_SIZE) -> None:
        self._capacity = capacity
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def claim(self, nonce: str, timestamp: float) -> bool:
        """Record a nonce, returning False if it has already been used.

        Args:
            nonce: The nonce to claim.
            timestamp: Request timestamp, retained so the oldest entry is the one
                evicted when the cache is full.

        Returns:
            True if this is the first time the nonce has been seen.
        """
        with self._lock:
            if nonce in self._seen:
                return False
            if len(self._seen) >= self._capacity:
                oldest = min(self._seen, key=lambda key: self._seen[key])
                del self._seen[oldest]
            self._seen[nonce] = timestamp
            return True


def build_request(
    *,
    node_id: str,
    model: str,
    prompt: str,
    stream: bool,
    token: str,
    timestamp: float | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Build a signed mesh inference request.

    Args:
        node_id: Node the request is addressed to. Bound into the signature so a request
            captured from one node cannot be replayed against another.
        model: Model name to run.
        prompt: Prompt text.
        stream: Whether the node should reply with a chunk sequence.
        token: The target node's auth token. Used as the HMAC key only; never sent.
        timestamp: Override for the request time. Tests use it to forge staleness.
        nonce: Override for the nonce. Tests use it to forge a replay.

    Returns:
        The envelope, ready to serialise.
    """
    ts = time.time() if timestamp is None else timestamp
    nonce_value = secrets.token_hex(16) if nonce is None else nonce
    digest = _body_digest(model, prompt, stream)
    return {
        "v": PROTOCOL_VERSION,
        "node_id": node_id,
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "nonce": nonce_value,
        "timestamp": ts,
        "signature": _signature(token, node_id, nonce_value, ts, digest),
    }


def encode_request(**kwargs: Any) -> bytes:
    """Build and serialise a signed request. See `build_request` for arguments."""
    return json.dumps(build_request(**kwargs)).encode("utf-8")


def verify_request(
    payload: bytes | str,
    *,
    node_id: str,
    token: str | None,
    nonce_cache: NonceCache | None = None,
    now: float | None = None,
) -> MeshInferenceRequest:
    """Verify an incoming mesh request and return it, or refuse to serve it.

    Args:
        payload: Raw query payload.
        node_id: The verifying node's own id. A request addressed elsewhere is refused.
        token: The verifying node's auth token. `None` or empty fails closed.
        nonce_cache: Single-use nonce store. Omitted only where replay is not a concern
            (a caller verifying its own freshly built request, i.e. tests).
        now: Override for the current time.

    Returns:
        The verified request.

    Raises:
        MeshRequestError: On any verification failure. The message is safe to return
            to the caller; it never distinguishes a wrong signature from an unknown
            token, so it cannot be used to probe for valid credentials.
    """
    if not token:
        # Fail closed, as `verify_node_auth` does: an unconfigured node serves nothing.
        raise MeshRequestError(
            "Node is not configured for network auth. Set NODE_NETWORK_AUTH_TOKEN in "
            "Node/.env (the installer generates one) and restart the node.",
            status=401,
        )

    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MeshRequestError("Malformed mesh request payload.", status=400) from exc
    else:
        text = payload

    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MeshRequestError("Malformed mesh request payload.", status=400) from exc

    if not isinstance(envelope, dict):
        raise MeshRequestError("Malformed mesh request payload.", status=400)

    version = envelope.get("v")
    if version != PROTOCOL_VERSION:
        raise MeshRequestError(f"Unsupported mesh protocol version: {version!r}.", status=400)

    claimed_node = envelope.get("node_id")
    model = envelope.get("model")
    prompt = envelope.get("prompt")
    stream = envelope.get("stream", False)
    nonce = envelope.get("nonce")
    timestamp = envelope.get("timestamp")
    signature = envelope.get("signature")

    if (
        not isinstance(claimed_node, str)
        or not isinstance(model, str)
        or not isinstance(prompt, str)
        or not isinstance(stream, bool)
        or not isinstance(nonce, str)
        or not isinstance(timestamp, (int, float))
        or isinstance(timestamp, bool)
        or not isinstance(signature, str)
    ):
        raise MeshRequestError("Malformed mesh request payload.", status=400)

    if claimed_node != node_id:
        raise MeshRequestError("Mesh request addressed to a different node.", status=401)

    age = (time.time() if now is None else now) - float(timestamp)
    if abs(age) > MAX_CLOCK_SKEW_SECONDS:
        raise MeshRequestError(
            f"Mesh request is outside the {MAX_CLOCK_SKEW_SECONDS:.0f}s freshness window.",
            status=401,
        )

    expected = _signature(
        token, node_id, nonce, float(timestamp), _body_digest(model, prompt, stream)
    )
    if not hmac.compare_digest(signature, expected):
        raise MeshRequestError("Mesh request signature is not valid.", status=401)

    # Claimed only after the signature verifies, so an unauthenticated caller cannot
    # burn a nonce that a legitimate request would later need.
    if nonce_cache is not None and not nonce_cache.claim(nonce, float(timestamp)):
        raise MeshRequestError("Mesh request nonce has already been used.", status=401)

    return MeshInferenceRequest(node_id=node_id, model=model, prompt=prompt, stream=stream)


def encode_result(model: str, response: str) -> bytes:
    """Encode the single reply to a non-streaming request."""
    return json.dumps({"ok": True, "model": model, "response": response}).encode("utf-8")


def encode_chunk(index: int, chunk: str) -> bytes:
    """Encode one chunk of a streaming reply.

    Args:
        index: Position in the stream, from 0. Zenoh gives no ordering guarantee across
            replies, so the receiver uses this to notice reordering rather than assume
            it cannot happen.
        chunk: The token text.
    """
    return json.dumps({"ok": True, "i": index, "chunk": chunk}).encode("utf-8")


def encode_done() -> bytes:
    """Encode the terminator of a streaming reply."""
    return json.dumps({"ok": True, "done": True}).encode("utf-8")


def encode_error(message: str, status: int = 500) -> bytes:
    """Encode a failure the node is reporting deliberately.

    Distinct from sending nothing: a caller that receives this knows the node answered,
    so it must surface the error rather than retry over another transport.
    """
    return json.dumps({"ok": False, "status": status, "error": message}).encode("utf-8")


def decode_reply(payload: bytes | str) -> dict[str, Any]:
    """Decode one reply envelope.

    Raises:
        ValueError: If the payload is not a JSON object.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("Mesh reply is not a JSON object.")
    return decoded
