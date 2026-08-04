"""`mesh_protocol.py` exists twice and must stay one contract.

CLAUDE.md lists four modules already duplicated across Node and Scheduler, and records that
`autonomous_orchestrator.py` drifted because a fix landed on one copy only. `mesh_protocol.py`
is a fifth duplicate -- unavoidable, because the request envelope has to be identical in both
packages and there is no shared installable package to hold it (`src/shared/` is an unimported
third copy of the artifact store, not a dependency of either service).

The difference is that this pair is guarded. This module is in the root suite because that is
the only interpreter where both `node` and `scheduler` import, so it is the only place the two
copies can be compared at all.

Byte equality alone would be satisfied by two files that are identical and both broken, so
this also round-trips a real request signed by one copy against the other.
"""

import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NODE_COPY = REPO_ROOT / "Node" / "src" / "node" / "core" / "mesh_protocol.py"
SCHEDULER_COPY = REPO_ROOT / "Scheduler" / "src" / "scheduler" / "core" / "mesh_protocol.py"

NODE_ID = "node-parity"
TOKEN = "parity-token"


def test_both_copies_exist() -> None:
    assert NODE_COPY.is_file(), f"missing {NODE_COPY}"
    assert SCHEDULER_COPY.is_file(), f"missing {SCHEDULER_COPY}"


def test_copies_are_byte_identical() -> None:
    """If this fails, a change landed on one copy only.

    Fix by making the two files identical again -- not by relaxing this test. A divergence
    here means the Scheduler and the Node disagree about the wire format, which shows up as
    every mesh request being rejected for a bad signature.
    """
    node_bytes = NODE_COPY.read_bytes()
    scheduler_bytes = SCHEDULER_COPY.read_bytes()

    assert hashlib.sha256(node_bytes).hexdigest() == hashlib.sha256(scheduler_bytes).hexdigest(), (
        "mesh_protocol.py has diverged between Node and Scheduler.\n"
        f"  {NODE_COPY.relative_to(REPO_ROOT)}: {len(node_bytes)} bytes\n"
        f"  {SCHEDULER_COPY.relative_to(REPO_ROOT)}: {len(scheduler_bytes)} bytes\n"
        "Copy one over the other; do not edit this test."
    )


def test_a_request_signed_by_the_scheduler_verifies_on_the_node() -> None:
    """The direction that matters in production."""
    from node.core.mesh_protocol import verify_request as node_verify
    from scheduler.core.mesh_protocol import encode_request as scheduler_encode

    payload = scheduler_encode(
        node_id=NODE_ID, model="llama3", prompt="cross-package", stream=False, token=TOKEN
    )
    verified = node_verify(payload, node_id=NODE_ID, token=TOKEN)

    assert verified.model == "llama3"
    assert verified.prompt == "cross-package"


def test_a_request_signed_by_the_node_verifies_on_the_scheduler() -> None:
    """The reverse direction, so the signature function is pinned symmetric."""
    from node.core.mesh_protocol import encode_request as node_encode
    from scheduler.core.mesh_protocol import verify_request as scheduler_verify

    payload = node_encode(
        node_id=NODE_ID, model="llama3", prompt="other way", stream=True, token=TOKEN
    )
    verified = scheduler_verify(payload, node_id=NODE_ID, token=TOKEN)

    assert verified.prompt == "other way"
    assert verified.stream is True


def test_a_wrong_token_is_rejected_across_packages() -> None:
    """Guards against both copies degrading into an accept-everything check."""
    from node.core.mesh_protocol import MeshRequestError, verify_request as node_verify
    from scheduler.core.mesh_protocol import encode_request as scheduler_encode

    payload = scheduler_encode(
        node_id=NODE_ID, model="llama3", prompt="p", stream=False, token="a-different-token"
    )

    with pytest.raises(MeshRequestError):
        node_verify(payload, node_id=NODE_ID, token=TOKEN)


def test_reply_encoders_agree_across_packages() -> None:
    """The node encodes replies; the Scheduler decodes them."""
    from node.core.mesh_protocol import encode_chunk, encode_done, encode_error, encode_result
    from scheduler.core.mesh_protocol import decode_reply

    assert decode_reply(encode_result("llama3", "hi"))["response"] == "hi"
    assert decode_reply(encode_chunk(2, "tok")) == {"ok": True, "i": 2, "chunk": "tok"}
    assert decode_reply(encode_done())["done"] is True
    assert decode_reply(encode_error("nope", status=404))["status"] == 404


def test_key_expressions_agree_across_packages() -> None:
    """A mismatch here means the Scheduler queries a key nothing is serving."""
    from node.core.mesh_protocol import infer_key_expr as node_key
    from scheduler.core.mesh_protocol import infer_key_expr as scheduler_key

    assert node_key(NODE_ID) == scheduler_key(NODE_ID)


def test_protocol_constants_agree_across_packages() -> None:
    """Version and freshness window must match, or one side rejects everything."""
    from node.core import mesh_protocol as node_proto
    from scheduler.core import mesh_protocol as scheduler_proto

    assert node_proto.PROTOCOL_VERSION == scheduler_proto.PROTOCOL_VERSION
    assert node_proto.MAX_CLOCK_SKEW_SECONDS == scheduler_proto.MAX_CLOCK_SKEW_SECONDS
    assert node_proto.INFER_KEY_TEMPLATE == scheduler_proto.INFER_KEY_TEMPLATE
