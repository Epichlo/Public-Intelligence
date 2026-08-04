"""Tests for the mesh inference envelope and its authentication.

This is the credential check on a transport that is reachable by anyone who can join the
mesh, so the rejection cases matter more than the happy path. Each one below is a way an
attacker could try to spend a host's GPU without holding that host's token.
"""

import json
import time

import pytest

from node.core.mesh_protocol import (
    MAX_CLOCK_SKEW_SECONDS,
    MeshRequestError,
    NonceCache,
    build_request,
    decode_reply,
    encode_chunk,
    encode_done,
    encode_error,
    encode_request,
    encode_result,
    infer_key_expr,
    verify_request,
)

NODE_ID = "node-mesh-1"
TOKEN = "a-node-secret-token"


def _signed(**overrides: object) -> bytes:
    """A valid signed request, with fields optionally overridden."""
    kwargs: dict[str, object] = {
        "node_id": NODE_ID,
        "model": "llama3",
        "prompt": "hello",
        "stream": False,
        "token": TOKEN,
    }
    kwargs.update(overrides)
    return encode_request(**kwargs)  # type: ignore[arg-type]


def test_key_expression_is_per_node() -> None:
    """One node's queryable must not match another node's query."""
    assert infer_key_expr(NODE_ID) == f"public-intelligence/net/{NODE_ID}/infer"
    assert infer_key_expr("other") != infer_key_expr(NODE_ID)


def test_valid_request_verifies() -> None:
    """A request signed with the node's token is accepted and returns the body."""
    verified = verify_request(_signed(), node_id=NODE_ID, token=TOKEN)

    assert verified.model == "llama3"
    assert verified.prompt == "hello"
    assert verified.stream is False


def test_token_never_appears_on_the_wire() -> None:
    """The credential is the HMAC key, not a field. It must not be transmitted."""
    payload = _signed()

    assert TOKEN.encode() not in payload, (
        "the node's credential was serialised into the mesh request; Zenoh links are "
        "plaintext TCP by default, so this would expose it to the router operator"
    )


def test_unconfigured_node_serves_nothing() -> None:
    """Fails closed, matching `verify_node_auth`."""
    for token in (None, ""):
        with pytest.raises(MeshRequestError) as excinfo:
            verify_request(_signed(), node_id=NODE_ID, token=token)
        assert excinfo.value.status == 401


def test_wrong_token_is_rejected() -> None:
    """A signature made with a different token must not verify."""
    forged = _signed(token="not-the-right-token")

    with pytest.raises(MeshRequestError) as excinfo:
        verify_request(forged, node_id=NODE_ID, token=TOKEN)
    assert excinfo.value.status == 401


def test_edited_prompt_breaks_the_signature() -> None:
    """The signature binds the body, so a captured request cannot be re-aimed.

    Without body binding, anyone who observed one legitimate request could replace the
    prompt and spend the host's GPU on their own work.
    """
    envelope = json.loads(_signed().decode())
    envelope["prompt"] = "something the signer never authorised"

    with pytest.raises(MeshRequestError):
        verify_request(json.dumps(envelope).encode(), node_id=NODE_ID, token=TOKEN)


def test_edited_model_breaks_the_signature() -> None:
    """`model` is covered by the digest too, not just the prompt."""
    envelope = json.loads(_signed().decode())
    envelope["model"] = "some-other-model"

    with pytest.raises(MeshRequestError):
        verify_request(json.dumps(envelope).encode(), node_id=NODE_ID, token=TOKEN)


def test_request_for_another_node_is_rejected() -> None:
    """A request signed for node A must not be accepted by node B."""
    for_other_node = _signed(node_id="node-somebody-else")

    with pytest.raises(MeshRequestError) as excinfo:
        verify_request(for_other_node, node_id=NODE_ID, token=TOKEN)
    assert excinfo.value.status == 401


def test_stale_request_is_rejected() -> None:
    """Outside the freshness window, in both directions."""
    now = time.time()
    too_old = _signed(timestamp=now - MAX_CLOCK_SKEW_SECONDS - 1)
    too_new = _signed(timestamp=now + MAX_CLOCK_SKEW_SECONDS + 1)

    for payload in (too_old, too_new):
        with pytest.raises(MeshRequestError, match="freshness window"):
            verify_request(payload, node_id=NODE_ID, token=TOKEN, now=now)


def test_fresh_request_inside_the_window_is_accepted() -> None:
    """The window must not be so tight that ordinary clock drift breaks dispatch."""
    now = time.time()
    payload = _signed(timestamp=now - (MAX_CLOCK_SKEW_SECONDS / 2))

    assert verify_request(payload, node_id=NODE_ID, token=TOKEN, now=now).prompt == "hello"


def test_replayed_nonce_is_rejected() -> None:
    """A captured request must not be servable twice inside the freshness window."""
    payload = _signed()
    cache = NonceCache()

    assert (
        verify_request(payload, node_id=NODE_ID, token=TOKEN, nonce_cache=cache).model == "llama3"
    )

    with pytest.raises(MeshRequestError, match="nonce"):
        verify_request(payload, node_id=NODE_ID, token=TOKEN, nonce_cache=cache)


def test_failed_verification_does_not_burn_the_nonce() -> None:
    """An unauthenticated caller must not be able to invalidate a real request.

    If the nonce were claimed before the signature check, anyone could take a nonce from
    an observed request, send it with a junk signature, and have the legitimate request
    rejected as a replay.
    """
    cache = NonceCache()
    envelope = json.loads(_signed().decode())
    nonce = envelope["nonce"]

    tampered = dict(envelope)
    tampered["signature"] = "0" * 64
    with pytest.raises(MeshRequestError):
        verify_request(
            json.dumps(tampered).encode(), node_id=NODE_ID, token=TOKEN, nonce_cache=cache
        )

    # The genuine request carrying that same nonce must still be served.
    verified = verify_request(
        json.dumps(envelope).encode(), node_id=NODE_ID, token=TOKEN, nonce_cache=cache
    )
    assert verified.prompt == "hello"
    assert nonce == envelope["nonce"]


def test_nonce_cache_evicts_without_unbounded_growth() -> None:
    """The cache is bounded, and eviction takes the oldest entry."""
    cache = NonceCache(capacity=2)

    assert cache.claim("first", 1.0)
    assert cache.claim("second", 2.0)
    assert cache.claim("third", 3.0)
    # "first" was the oldest, so it was evicted and can be claimed again.
    assert cache.claim("first", 4.0)
    # "third" is still held.
    assert not cache.claim("third", 5.0)


def test_malformed_payloads_are_rejected_not_crashed() -> None:
    """Garbage on the wire must produce a refusal, not an unhandled exception."""
    for payload in (b"not json", b"[]", b'"a string"', b"\xff\xfe", b"{}"):
        with pytest.raises(MeshRequestError):
            verify_request(payload, node_id=NODE_ID, token=TOKEN)


def test_unknown_protocol_version_is_rejected() -> None:
    """A future envelope shape must be refused rather than half-understood."""
    envelope = json.loads(_signed().decode())
    envelope["v"] = 99

    with pytest.raises(MeshRequestError, match="version"):
        verify_request(json.dumps(envelope).encode(), node_id=NODE_ID, token=TOKEN)


def test_non_bool_stream_is_rejected() -> None:
    """`stream` is part of the signed digest, so its type must be pinned."""
    envelope = json.loads(_signed().decode())
    envelope["stream"] = "yes"

    with pytest.raises(MeshRequestError):
        verify_request(json.dumps(envelope).encode(), node_id=NODE_ID, token=TOKEN)


def test_streaming_flag_survives_verification() -> None:
    """A streaming request must be recognisable as one after verification."""
    verified = verify_request(_signed(stream=True), node_id=NODE_ID, token=TOKEN)
    assert verified.stream is True


def test_reply_encoders_round_trip() -> None:
    """Every reply shape the node can send must decode to what the client expects."""
    assert decode_reply(encode_result("llama3", "hi")) == {
        "ok": True,
        "model": "llama3",
        "response": "hi",
    }
    assert decode_reply(encode_chunk(3, "tok")) == {"ok": True, "i": 3, "chunk": "tok"}
    assert decode_reply(encode_done()) == {"ok": True, "done": True}
    assert decode_reply(encode_error("boom", status=404)) == {
        "ok": False,
        "status": 404,
        "error": "boom",
    }


def test_build_request_generates_a_fresh_nonce_each_time() -> None:
    """Two requests with identical bodies must not collide in the nonce cache."""
    first = build_request(node_id=NODE_ID, model="llama3", prompt="same", stream=False, token=TOKEN)
    second = build_request(
        node_id=NODE_ID, model="llama3", prompt="same", stream=False, token=TOKEN
    )

    assert first["nonce"] != second["nonce"]
    assert first["signature"] != second["signature"]
