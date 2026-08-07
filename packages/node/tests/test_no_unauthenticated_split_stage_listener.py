"""A node must not subscribe to an unauthenticated wildcard tensor topic.

Found while doing ROADMAP C2. `Runtime.start()` called
`_setup_split_stage_listener()` on every node that got a Zenoh session, which
declared a subscriber on `public-intelligence/net/tasks/*/tensors/*` -- a wildcard,
with **no authentication of any kind** -- and on any matching sample:

  * deserialised attacker-controlled bytes via `TensorPayload.from_framed_bytes`,
  * if the payload began `shm://`, called
    `SharedMemoryIPC.read_data(<attacker-supplied name>)` and then `cleanup()`,
    which is an arbitrary shared-memory **read and unlink** on the host,
  * ran the inference backend,
  * and published a reply back onto the mesh.

ROADMAP 2.7 closed the unauthenticated mesh ingress paths by AES-256-GCM enveloping
every message that **changes registry state**. This one changes no registry state,
so it fell outside that scope and survived -- an authenticated telemetry path and an
authenticated inference path sitting next to a completely open one.

It exists to serve split inference, which is cut from v1 and answers 501 at the
gateway (ROADMAP N1). So the fix is removal, not authentication: there is nothing
for an authenticated version of this listener to do.

These tests assert on what the node declares on the wire, not on which function is
present, so re-adding the behaviour under another name still fails.
"""

from typing import Any

import pytest

from node.core.configuration import Settings
from node.runtime import Runtime


class _RecordingSession:
    """Records every subscriber a node declares."""

    def __init__(self) -> None:
        self.subscriptions: list[str] = []

    def declare_subscriber(self, key: str, handler: Any, **kwargs: Any) -> Any:
        self.subscriptions.append(key)
        return type("Sub", (), {"undeclare": lambda self: None})()

    def declare_publisher(self, key: str, **kwargs: Any) -> Any:
        return type(
            "Pub", (), {"put": lambda self, *a, **k: None, "undeclare": lambda self: None}
        )()

    def declare_queryable(self, key: str, handler: Any, **kwargs: Any) -> Any:
        self.subscriptions.append(key)
        return type("Q", (), {"undeclare": lambda self: None})()

    def put(self, key: str, payload: Any, **kwargs: Any) -> None:
        pass


def test_runtime_has_no_split_stage_listener_at_all() -> None:
    """The method is gone, not merely unreferenced.

    Kept as a separate, blunt assertion from the wire-level one below: leaving the
    method behind and unwired is how ROADMAP N1's fabricating code path survived
    for weeks, and the lesson recorded there was to delete rather than to guard.
    """
    assert not hasattr(Runtime, "_setup_split_stage_listener"), (
        "the split-stage listener is back. It is an unauthenticated wildcard "
        "subscriber that reads host shared memory by attacker-supplied name, for a "
        "feature that is cut from v1."
    )


def test_a_node_declares_no_wildcard_tensor_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing the node declares may match the tensor activation topic.

    Asserted against the topic string rather than the method name, so that
    re-introducing the subscription under a different function still fails.
    """
    session = _RecordingSession()
    runtime = Runtime(Settings(node_id="n1", network_auth_token="t" * 64))

    # Drive only the declaration path; the rest of start() needs a Scheduler.
    if hasattr(runtime, "_setup_split_stage_listener"):  # pragma: no cover - fails above
        runtime.zenoh_client.session = session  # type: ignore[union-attr]
        runtime._setup_split_stage_listener()  # type: ignore[attr-defined]

    forbidden = [key for key in session.subscriptions if "tensors" in key]
    assert not forbidden, f"node subscribed to unauthenticated tensor topics: {forbidden}"


def test_the_runtime_no_longer_imports_the_split_transport() -> None:
    """`node.core.transport` must not be reachable from the live runtime module.

    `transport.py` is split-inference plumbing (ROADMAP C2). After this change its
    only remaining importer was the listener above, so the import going away is what
    makes the module genuinely unreferenced by shipping code rather than merely
    unused-looking.
    """
    source = (Runtime.__module__, "node.runtime")
    assert source[0] == source[1]

    import inspect

    text = inspect.getsource(__import__("node.runtime", fromlist=["x"]))
    assert "core.transport" not in text, (
        "node/runtime.py imports node.core.transport again -- that module is cut "
        "from v1 and its last live caller was the unauthenticated tensor listener."
    )
