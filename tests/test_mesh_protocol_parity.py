"""`mesh_protocol.py` exists twice and must stay one contract.

CLAUDE.md lists four modules already duplicated across Node and Scheduler, and records that
`autonomous_orchestrator.py` drifted because a fix landed on one copy only. `mesh_protocol.py`
is a fifth duplicate -- unavoidable, because the request envelope has to be identical in both
packages and there is no shared installable package to hold it (`src/shared/` is an unimported
third copy of the artifact store, not a dependency of either service; the monorepo
migration makes `packages/shared/` possible, which is the follow-up that removes
this duplication entirely).

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
NODE_COPY = (
    REPO_ROOT / "packages" / "node" / "src" / "node" / "core" / "mesh_protocol.py"
)
SCHEDULER_COPY = (
    REPO_ROOT
    / "packages"
    / "scheduler"
    / "src"
    / "scheduler"
    / "core"
    / "mesh_protocol.py"
)

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

    assert (
        hashlib.sha256(node_bytes).hexdigest()
        == hashlib.sha256(scheduler_bytes).hexdigest()
    ), (
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
        node_id=NODE_ID,
        model="llama3",
        prompt="cross-package",
        stream=False,
        token=TOKEN,
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
        node_id=NODE_ID,
        model="llama3",
        prompt="p",
        stream=False,
        token="a-different-token",
    )

    with pytest.raises(MeshRequestError):
        node_verify(payload, node_id=NODE_ID, token=TOKEN)


def test_reply_encoders_agree_across_packages() -> None:
    """The node encodes replies; the Scheduler decodes them."""
    from node.core.mesh_protocol import (
        encode_chunk,
        encode_done,
        encode_error,
        encode_result,
    )
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


# --- mesh_auth.py: the second byte-identical pair (ROADMAP 2.7) ---------------
#
# Same argument as `mesh_protocol.py`, and a sharper one: this pair decides whether
# a message is authentic. If the two copies drift, the Scheduler silently stops
# accepting real nodes -- a failure that looks like a network problem, not a bug.

NODE_AUTH_COPY = (
    REPO_ROOT / "packages" / "node" / "src" / "node" / "core" / "mesh_auth.py"
)
SCHEDULER_AUTH_COPY = (
    REPO_ROOT / "packages" / "scheduler" / "src" / "scheduler" / "core" / "mesh_auth.py"
)


def test_both_mesh_auth_copies_exist() -> None:
    assert NODE_AUTH_COPY.is_file(), f"missing {NODE_AUTH_COPY}"
    assert SCHEDULER_AUTH_COPY.is_file(), f"missing {SCHEDULER_AUTH_COPY}"


def test_mesh_auth_copies_are_byte_identical() -> None:
    """Budget 0. Fix by making them identical, never by relaxing this."""
    node_digest = hashlib.sha256(NODE_AUTH_COPY.read_bytes()).hexdigest()
    scheduler_digest = hashlib.sha256(SCHEDULER_AUTH_COPY.read_bytes()).hexdigest()

    assert node_digest == scheduler_digest, (
        "mesh_auth.py copies have diverged. A change landed on one side only, and "
        "the two ends of the mesh no longer agree on what a valid envelope is."
    )


def test_an_envelope_sealed_by_the_node_opens_on_the_scheduler() -> None:
    """Byte equality would be satisfied by two identical, broken files.

    This is the direction that matters in production: the node seals, the Scheduler
    opens.
    """
    from node.core.mesh_auth import PURPOSE_TELEMETRY, seal
    from scheduler.core.mesh_auth import open_envelope

    raw = seal({"cpu": 12.5}, node_id=NODE_ID, token=TOKEN, purpose=PURPOSE_TELEMETRY)

    assert open_envelope(
        raw, node_id=NODE_ID, token=TOKEN, purpose=PURPOSE_TELEMETRY
    ) == {"cpu": 12.5}


def test_the_scheduler_rejects_an_envelope_sealed_with_another_nodes_token() -> None:
    """The property the whole change rests on, checked across the real pair."""
    from node.core.mesh_auth import PURPOSE_HEARTBEAT, seal
    from scheduler.core.mesh_auth import MeshAuthError, open_envelope

    raw = seal(
        {"x": 1},
        node_id=NODE_ID,
        token="someone-elses-token",
        purpose=PURPOSE_HEARTBEAT,
    )

    with pytest.raises(MeshAuthError):
        open_envelope(raw, node_id=NODE_ID, token=TOKEN, purpose=PURPOSE_HEARTBEAT)


def test_mesh_auth_constants_agree_across_packages() -> None:
    """A version or purpose-string skew makes one side reject everything."""
    from node.core import mesh_auth as node_auth
    from scheduler.core import mesh_auth as scheduler_auth

    assert node_auth.ENVELOPE_VERSION == scheduler_auth.ENVELOPE_VERSION
    assert node_auth.PURPOSE_TELEMETRY == scheduler_auth.PURPOSE_TELEMETRY
    assert node_auth.PURPOSE_HEARTBEAT == scheduler_auth.PURPOSE_HEARTBEAT
