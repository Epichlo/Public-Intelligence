"""Authenticated envelopes for everything a node publishes on the Zenoh mesh.

Zenoh links are plaintext and the bootstrap router is public, so "can reach the
mesh" is not a privilege. Every message that changes Scheduler state has to prove
it came from the node it claims to be.

**Keys are derived from that node's own `NODE_NETWORK_AUTH_TOKEN`**, which
`install.sh` generates per install and the Scheduler stores at registration. The
predecessor was a single fleet-wide `TELEMETRY_SECRET_KEY` whose default was a
constant published in this repository -- and even with a secret value, a shared
symmetric key can only stop outsiders, because every host holds it and could forge
for every other host. See specs/authenticated-mesh-ingress.md.

THIS FILE EXISTS TWICE, byte-identically, at:

    packages/node/src/node/core/mesh_auth.py
    packages/scheduler/src/scheduler/core/mesh_auth.py

`tests/test_mesh_protocol_parity.py` holds them identical at a drift budget of 0
and round-trips a real envelope built by one copy through the other. Change one,
change both. The duplication exists because there is still no shared installable
package; `packages/shared/` is the recorded end state.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Bumped if the envelope format or key derivation changes. Both sides compare it,
# so a version skew is a clean rejection rather than a confusing MAC failure.
ENVELOPE_VERSION = 1

# Purposes get separate keys so an envelope minted for one topic cannot be
# verified on another even before the node-id binding is considered.
PURPOSE_TELEMETRY = "telemetry"
PURPOSE_HEARTBEAT = "heartbeat"


class MeshAuthError(Exception):
    """An envelope could not be verified, or could not be built."""


def derive_key(token: str, purpose: str) -> bytes:
    """Derive the AES-256-GCM key for one purpose from a node's credential.

    Never the raw token: the same string authenticates the node's HTTP control API,
    and a key that is also a bearer credential leaks one use into the other. The
    context pins the protocol, the version and the purpose, so a key minted for
    telemetry cannot open a heartbeat.

    Args:
        token: The node's `NODE_NETWORK_AUTH_TOKEN`.
        purpose: `PURPOSE_TELEMETRY` or `PURPOSE_HEARTBEAT`.

    Returns:
        A 32-byte key.
    """
    context = f"public-intelligence|mesh|v{ENVELOPE_VERSION}|{purpose}".encode()
    return hashlib.sha256(token.encode("utf-8") + b"|" + context).digest()


def _associated_data(node_id: str, purpose: str) -> bytes:
    """The context AES-GCM authenticates alongside the ciphertext.

    Passing the node id as AEAD associated data binds an envelope to the topic it
    was minted for. Stated precisely, because it is easy to overclaim: the control
    that actually stops a cross-topic replay today is that the Scheduler derives the
    key from the node OWNING THE TOPIC, so another node's envelope cannot open at
    all. This binding is defence in depth behind that -- confirmed by mutation, in
    that removing it changes no test outcome. It earns its place by making the
    property hold even if keys were ever shared again, not by doing the work now.

    The predecessor carried a separate SHA-256 HMAC over the ciphertext. That was
    redundant -- AES-GCM is an AEAD and already authenticates -- and the redundancy
    was demonstrable: removing the HMAC verification changed no test outcome,
    because the GCM tag rejected the same envelopes on its own. One mechanism that
    is load-bearing beats two where only one does the work.
    """
    return f"public-intelligence|mesh|v{ENVELOPE_VERSION}|{purpose}|{node_id}".encode()


def seal(payload: dict[str, Any], *, node_id: str, token: str, purpose: str) -> str:
    """Build a signed, encrypted envelope for `payload`, as a JSON string.

    Args:
        payload: The message body.
        node_id: The publishing node. Bound into the signature.
        token: That node's credential.
        purpose: `PURPOSE_TELEMETRY` or `PURPOSE_HEARTBEAT`.

    Returns:
        A JSON string ready to `put` on the node's own topic.
    """
    key = derive_key(token, purpose)

    iv = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(
        iv, json.dumps(payload).encode("utf-8"), _associated_data(node_id, purpose)
    )

    return json.dumps(
        {
            "v": ENVELOPE_VERSION,
            "node_id": node_id,
            "iv": base64.b64encode(iv).decode("utf-8"),
            "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
        }
    )


def open_envelope(raw: str, *, node_id: str, token: str, purpose: str) -> dict[str, Any]:
    """Verify and decrypt an envelope claimed to be from `node_id`.

    Args:
        raw: The JSON string received on the mesh.
        node_id: The node the TOPIC belongs to -- not a value read out of the
            message. The caller derives the key from the topic owner, so replaying
            a valid envelope onto someone else's topic fails here.
        token: That node's stored credential.
        purpose: `PURPOSE_TELEMETRY` or `PURPOSE_HEARTBEAT`.

    Returns:
        The decrypted payload.

    Raises:
        MeshAuthError: On malformed JSON, a missing field, a version mismatch, a
            node-id mismatch, or a failed AEAD verification. One exception type,
            because a caller that treats "forged" differently from "corrupt" is a
            caller that can be probed for the difference.
    """
    try:
        envelope = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MeshAuthError(f"envelope is not JSON: {exc}") from exc

    if not isinstance(envelope, dict):
        raise MeshAuthError("envelope is not an object")

    if envelope.get("v") != ENVELOPE_VERSION:
        raise MeshAuthError(f"unsupported envelope version: {envelope.get('v')!r}")

    iv_b64 = envelope.get("iv")
    ct_b64 = envelope.get("ciphertext")
    if not isinstance(iv_b64, str) or not isinstance(ct_b64, str):
        raise MeshAuthError("envelope is missing iv or ciphertext")

    # Checked for a clear error message only. It is NOT what stops a replay -- the
    # node id is authenticated as associated data below, so a mismatch fails the
    # GCM tag whether or not this field agrees with it.
    if envelope.get("node_id") != node_id:
        raise MeshAuthError(
            f"envelope claims node_id {envelope.get('node_id')!r} on {node_id!r}'s topic"
        )

    try:
        plaintext = AESGCM(derive_key(token, purpose)).decrypt(
            base64.b64decode(iv_b64),
            base64.b64decode(ct_b64),
            _associated_data(node_id, purpose),
        )
    except (InvalidTag, ValueError, TypeError) as exc:
        raise MeshAuthError(f"verification failed: {exc}") from exc

    try:
        payload = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise MeshAuthError(f"decrypted payload is not JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise MeshAuthError("decrypted payload is not an object")
    return payload
