"""The durable-storage interface the Scheduler writes through.

Named `persistence` rather than `storage` on purpose: `src/shared/storage/` already
exists (in three copies) and is an *artifact* store for blobs. This is control-plane
state. Two things called "storage" in one control plane is how the duplicated-module
problem this repo is already unwinding got started.

Nothing in this Protocol mentions SQLite. The whole reason it is a Protocol is that
the SQLite backend is the *development and single-host* answer -- an operator who
actually needs durability (see the Render caveat in
specs/scheduler-persistence.md) needs a Postgres backend, and it must be possible
to add one without touching `NodeRegistry` or `CreditLedger`.

Every method is async even though the SQLite implementation does no awaiting. That
is deliberate: a driver that *does* await is the expected second implementation, and
making these async later would mean changing every call site inside the registry's
locked sections.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from scheduler.core.credit_ledger import CreditAccount
    from scheduler.models.node import Node


class SchedulerStore(Protocol):
    """Durable home for the state that must outlive the Scheduler process.

    Deliberately narrow. It stores what cannot be reconstructed (credit balances)
    and what is expensive to wait for (the node fleet). It does **not** store live
    observations -- heartbeats, telemetry, mesh reachability, scheduling dampeners
    -- because restoring a measurement from a moment that has passed presents stale
    data as current. The reasoning per field is tabulated in
    specs/scheduler-persistence.md.
    """

    async def load_nodes(self) -> list[Node]:
        """Return every stored node.

        A row that no longer validates must be skipped, not raised: refusing to
        start over one bad row turns schema drift into a total outage, while the
        node it belonged to would have re-registered on its own (ROADMAP 1.6).
        """
        ...

    async def save_node(self, node: Node) -> None:
        """Insert or replace the stored record for `node`."""
        ...

    async def delete_node(self, node_id: str) -> None:
        """Remove a node and its credential. Silent if the node is not stored."""
        ...

    async def clear_nodes(self) -> None:
        """Remove every node and every credential."""
        ...

    async def load_node_tokens(self) -> dict[str, str]:
        """Return the stored control-API credential for each node that has one."""
        ...

    async def save_node_token(self, node_id: str, token: str | None) -> None:
        """Store a node's credential, or remove it when `token` is falsy.

        Written separately from the node itself because registration records the
        token *before* it attempts the create -- so a re-registering node with a
        rotated token refreshes it even on the 409 path -- and at that moment there
        may be no node row to attach it to.
        """
        ...

    async def load_accounts(self) -> list[CreditAccount]:
        """Return every stored credit account."""
        ...

    async def save_account(self, account: CreditAccount) -> None:
        """Insert or replace a credit account's balances."""
        ...

    async def close(self) -> None:
        """Release the backend's resources. Safe to call more than once."""
        ...
