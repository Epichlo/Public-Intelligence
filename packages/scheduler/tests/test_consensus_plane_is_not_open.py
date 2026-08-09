"""The Scheduler must not run an unauthenticated Raft plane (ROADMAP C2 + 2.7).

`ZenohRouter.start()` constructed a `RaftConsensusEngine` and called `start()` on it
unconditionally, on every Scheduler boot. That opened a **second Zenoh session** and
declared a subscriber on `public-intelligence/net/consensus/*` — a wildcard key, with
**no authentication of any kind** — whose handler parses JSON from anyone and
dispatches on a `type` field.

Two of those branches reach registry state:

* **`AppendEntries` with a higher term** makes this Scheduler a FOLLOWER of the
  sender and appends the sender's entries to its log. `_apply_log_entries` then
  executes them: `action: "unregister_node"` calls `registry.local_unregister_node`,
  and `action: "register"` calls `Node(**data)` and `registry.local_register`.
* **Injection is worse than eviction.** An injected node is dispatched to, which
  means it receives other people's prompts.

ROADMAP 2.7 closed precisely this shape for the other three mesh inputs, and its
own summary named the worst one: *"liveliness, where a DELETE took the node id from
a key expression the publisher chose and called `unregister_node`, so anyone could
evict any host."* The consensus plane has the same hole plus a node-injection path,
and 2.7 did not touch it.

`docs/decisions/D5-decentralisation-claim.md` decided the deployment is a single
instance and Raft is out of v1, so there is nothing for an authenticated version of
this plane to do. The engine is no longer constructed or started, and the module
moved to `experimental/`.
"""

from __future__ import annotations

import inspect

from scheduler.core import zenoh_router
from scheduler.main import create_app


def test_the_router_does_not_construct_a_consensus_engine() -> None:
    """Not constructed, not started, no second Zenoh session.

    Asserted against the source rather than by booting a router, because starting
    one opens a real session -- and the property under test is precisely that it no
    longer does.
    """
    import ast

    tree = ast.parse(inspect.getsource(zenoh_router))
    # Names and imports, NOT comments -- the comments in that module explain what
    # was removed and why, which is the fifth time in this session a check would
    # otherwise have fired on its own account of the bug.
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    for module in ast.walk(tree):
        if isinstance(module, ast.ImportFrom) and module.module:
            referenced.add(module.module)
            referenced.update(alias.name for alias in module.names)

    assert "RaftConsensusEngine" not in referenced, (
        "ZenohRouter constructs a Raft engine again. Starting it declares an "
        "UNAUTHENTICATED wildcard subscriber on public-intelligence/net/consensus/*, "
        "whose handler can evict any node and inject new ones."
    )
    assert not any("consensus" in name.lower() for name in referenced), (
        f"zenoh_router still references the consensus plane in code: "
        f"{sorted(n for n in referenced if 'consensus' in n.lower())}"
    )


def test_no_shipping_module_subscribes_to_the_consensus_plane() -> None:
    """The key expression itself must be gone from shipping code.

    An import ban would not catch this: the subscription is a STRING, and the hole
    was a wildcard key, not a symbol.
    """
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    offenders = []
    for path in (repo_root / "packages").rglob("*.py"):
        if "tests" in path.parts or "node_modules" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "net/consensus" in node.value
            ):
                offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, f"the consensus key expression is back in shipping code: {offenders}"


def test_the_registry_no_longer_routes_writes_through_a_consensus_engine() -> None:
    """The `is_active()` branches were live, not dead.

    Because `start()` succeeded on every boot, `is_active()` returned True and
    registry mutations really did go through the Raft proposal path — on a
    single-node "cluster". Removing the engine without removing these would leave
    branches that can only ever be reached by re-introducing the hole.
    """
    from scheduler.registry import node_registry

    source = inspect.getsource(node_registry)
    assert "consensus_engine" not in source, (
        "NodeRegistry still branches on a consensus engine that is no longer built"
    )


def test_the_app_still_starts_and_serves_without_it() -> None:
    """The removal must not take the Scheduler with it."""
    app = create_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert paths, "the app has no routes at all"
