"""SQLite-backed `SchedulerStore`.

Uses the standard library's `sqlite3`, so this adds no dependency. That matters
more than it sounds: the Scheduler ships to a free-tier container and to whatever
machine a host runs it on, and the alternative to "no dependency" here was an
async driver plus a connection pool for a workload of tens of rows.

**The calls in this file are synchronous and are not offloaded to a thread.** They
run on the event loop, inside the registry's lock. That is a judgement about
volume, not an oversight: with `journal_mode=WAL` and `synchronous=NORMAL` a
single-row upsert of a few hundred bytes does not fsync, and the fleet is tens of
nodes with a heartbeat every few seconds. `asyncio.to_thread` would hold the
registry lock across a thread hop -- more contention, for the same work. It is
also *unmeasured under load*; if the fleet grows by orders of magnitude this is
the assumption to revisit first.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from scheduler.core.credit_ledger import CreditAccount
from scheduler.core.invites import InviteCode
from scheduler.core.metering import UsageRecord
from scheduler.models.node import Node

if TYPE_CHECKING:
    from os import PathLike

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# `nodes.payload` is JSON, `credit_accounts` is real columns, and that difference is
# intentional. `Node` is nested (`GPUInfo`, a list of model names) and its shape moves
# with the roadmap, so exploding it into columns would mean a migration per field and
# would re-implement validation pydantic already does. A `CreditAccount` is four flat
# scalars and it is *money*: real columns mean an operator can audit balances with one
# `sqlite3 scheduler.db 'select * from credit_accounts'` instead of parsing blobs.
#
# `node_tokens` is its own table rather than a column on `nodes` because a token is
# written before the node row exists -- see `save_node_token` in store.py.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS node_tokens (
    node_id TEXT PRIMARY KEY,
    token   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credit_accounts (
    account_id       TEXT PRIMARY KEY,
    earned_credits   REAL NOT NULL,
    consumed_credits REAL NOT NULL,
    updated_at       REAL NOT NULL
);
-- Real columns, not a JSON blob, for the same reason credit_accounts uses them: an
-- operator has to be able to audit this with one `sqlite3 ... 'select ...'`. It is
-- also the table that must be inspectable when someone asks what a node actually
-- did, which is ROADMAP 3.4's whole purpose.
--
-- There is deliberately NO column that can hold prompt or completion text. That is
-- the schema half of the guarantee `UsageRecord` makes in Python, and
-- `tests/test_metering_privacy.py` is the enforcement of both.
CREATE TABLE IF NOT EXISTS usage_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id        TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    node_id           TEXT NOT NULL,
    model             TEXT NOT NULL,
    prompt_tokens     INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    duration_seconds  REAL NOT NULL,
    succeeded         INTEGER NOT NULL,
    recorded_at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_by_node ON usage_records (node_id, recorded_at);
-- Only the HASH is stored. An invite code is a bearer credential, so keeping it at
-- rest would mean the database leaks admission along with everything else.
CREATE TABLE IF NOT EXISTS invites (
    code_hash  TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    max_uses   INTEGER NOT NULL,
    uses       INTEGER NOT NULL,
    revoked    INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SQLiteStore:
    """A `SchedulerStore` backed by one SQLite file.

    One process owns the file. WAL tolerates concurrent readers, but nothing here
    coordinates two Schedulers writing the same database, and multi-instance
    deployment is explicitly out of v1.

    The connection is opened eagerly in `__init__` so that a bad path (an
    unwritable directory, a file that is not a database) fails where the operator
    configured it rather than on the first node registration an hour later.
    """

    def __init__(self, path: str | PathLike[str]) -> None:
        """Record where the database lives. Nothing touches the disk until first use.

        **Construction is deliberately side-effect-free.** ROADMAP C3 turned
        persistence on by default, which made `build_store()` return a real store --
        and `scheduler/main.py` builds the ASGI `app` at module scope, so opening the
        file here meant *importing the module* created a database wherever the
        process happened to be running. Six test modules import `scheduler.main.app`,
        so the suite dropped a file in the working directory and two concurrent runs
        would have shared one SQLite file.

        Args:
            path: Filesystem location of the SQLite file. Parent directories are
                created on connect -- `.env.example` suggests `./data/scheduler.db`,
                and a container whose `./data` does not exist yet must not fail
                startup on a missing directory.
        """
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None

    @property
    def _conn(self) -> sqlite3.Connection:
        """Connect on first use, creating the file and schema if needed."""
        if self._connection is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False: the event loop is one thread today, but
            # TestClient and any future to_thread offload are not, and the
            # alternative failure is an opaque ProgrammingError rather than anything
            # a reader could act on.
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_SCHEMA)
            self._connection = conn
            self._check_schema_version()
            conn.commit()
        return self._connection

    def _check_schema_version(self) -> None:
        """Record the schema version, or complain loudly if the file has another.

        There is no migration machinery. A mismatch is logged at ERROR and the
        stored version is left alone rather than overwritten, so the evidence of
        what wrote the file survives for whoever writes the migration.
        """
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            return
        if row["value"] != str(SCHEMA_VERSION):
            logger.error(
                "persistence_schema_mismatch: file=%s stored=%s expected=%s -- "
                "no migration path exists; rows that fail to validate will be skipped",
                self.path,
                row["value"],
                SCHEMA_VERSION,
            )

    # --- nodes -------------------------------------------------------------

    async def load_nodes(self) -> list[Node]:
        """Return every stored node, skipping any row that no longer validates."""
        nodes: list[Node] = []
        for row in self._conn.execute("SELECT node_id, payload FROM nodes ORDER BY rowid"):
            try:
                nodes.append(Node.model_validate_json(row["payload"]))
            except ValidationError:
                # One unreadable row must not cost the whole fleet. The node it
                # belonged to re-registers on its own within
                # registration_retry_max_seconds (ROADMAP 1.6).
                logger.exception("persistence_skipped_unreadable_node: node_id=%s", row["node_id"])
        return nodes

    async def save_node(self, node: Node) -> None:
        """Insert or replace the stored record for `node`."""
        self._conn.execute(
            "INSERT INTO nodes (node_id, payload) VALUES (?, ?) "
            "ON CONFLICT(node_id) DO UPDATE SET payload = excluded.payload",
            (node.node_id, node.model_dump_json()),
        )
        self._conn.commit()

    async def delete_node(self, node_id: str) -> None:
        """Remove a node and its credential."""
        self._conn.execute("DELETE FROM nodes WHERE node_id = ?", (node_id,))
        self._conn.execute("DELETE FROM node_tokens WHERE node_id = ?", (node_id,))
        self._conn.commit()

    async def clear_nodes(self) -> None:
        """Remove every node and every credential."""
        self._conn.execute("DELETE FROM nodes")
        self._conn.execute("DELETE FROM node_tokens")
        self._conn.commit()

    # --- credentials -------------------------------------------------------

    async def load_node_tokens(self) -> dict[str, str]:
        """Return the stored credential for each node that has one."""
        return {
            row["node_id"]: row["token"]
            for row in self._conn.execute("SELECT node_id, token FROM node_tokens")
        }

    async def save_node_token(self, node_id: str, token: str | None) -> None:
        """Store a node's credential, or remove it when `token` is falsy."""
        if token:
            self._conn.execute(
                "INSERT INTO node_tokens (node_id, token) VALUES (?, ?) "
                "ON CONFLICT(node_id) DO UPDATE SET token = excluded.token",
                (node_id, token),
            )
        else:
            self._conn.execute("DELETE FROM node_tokens WHERE node_id = ?", (node_id,))
        self._conn.commit()

    # --- credit accounts ---------------------------------------------------

    async def load_accounts(self) -> list[CreditAccount]:
        """Return every stored credit account."""
        return [
            CreditAccount(
                account_id=row["account_id"],
                earned_credits=row["earned_credits"],
                consumed_credits=row["consumed_credits"],
                updated_at=row["updated_at"],
            )
            for row in self._conn.execute(
                "SELECT account_id, earned_credits, consumed_credits, updated_at "
                "FROM credit_accounts"
            )
        ]

    async def save_account(self, account: CreditAccount) -> None:
        """Insert or replace a credit account's balances.

        The three numbers are bound as Python floats into REAL columns, so SQLite
        stores the same IEEE 754 doubles the ledger computed. Nothing here formats
        them into text, which is what would quietly shave credits off every host.
        """
        self._conn.execute(
            "INSERT INTO credit_accounts "
            "(account_id, earned_credits, consumed_credits, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(account_id) DO UPDATE SET "
            "earned_credits = excluded.earned_credits, "
            "consumed_credits = excluded.consumed_credits, "
            "updated_at = excluded.updated_at",
            (
                account.account_id,
                account.earned_credits,
                account.consumed_credits,
                account.updated_at,
            ),
        )
        self._conn.commit()

    # --- lifecycle ---------------------------------------------------------

    # --- invites -----------------------------------------------------------

    async def load_invites(self) -> list[InviteCode]:
        """Every stored invite, spent and revoked ones included."""
        rows = self._conn.execute(
            "SELECT code_hash, label, max_uses, uses, revoked, created_at FROM invites"
        ).fetchall()

        invites: list[InviteCode] = []
        for row in rows:
            try:
                invites.append(
                    InviteCode(
                        code_hash=row["code_hash"],
                        label=row["label"],
                        max_uses=row["max_uses"],
                        uses=row["uses"],
                        revoked=bool(row["revoked"]),
                        created_at=row["created_at"],
                    )
                )
            except ValidationError:
                # Skipping here is NOT the same trade as skipping a node row. An
                # unparseable invite fails OPEN -- the code it represents stops
                # being enforced -- so it is logged at ERROR rather than WARNING.
                logger.error("persistence_skipped_unparseable_invite_row")
        return invites

    async def save_invite(self, invite: InviteCode) -> None:
        """Insert or replace an invite, keyed on its hash."""
        self._conn.execute(
            "INSERT INTO invites (code_hash, label, max_uses, uses, revoked, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(code_hash) DO UPDATE SET "
            "label=excluded.label, max_uses=excluded.max_uses, uses=excluded.uses, "
            "revoked=excluded.revoked",
            (
                invite.code_hash,
                invite.label,
                invite.max_uses,
                invite.uses,
                int(invite.revoked),
                invite.created_at,
            ),
        )
        self._conn.commit()

    # --- usage -------------------------------------------------------------

    async def load_usage(self, limit: int = 500) -> list[UsageRecord]:
        """Most recent records, returned oldest-first so a tail append is natural."""
        rows = self._conn.execute(
            "SELECT request_id, tenant_id, node_id, model, prompt_tokens, "
            "completion_tokens, duration_seconds, succeeded, recorded_at "
            "FROM usage_records ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

        records: list[UsageRecord] = []
        for row in reversed(rows):
            try:
                records.append(
                    UsageRecord(
                        request_id=row["request_id"],
                        tenant_id=row["tenant_id"],
                        node_id=row["node_id"],
                        model=row["model"],
                        prompt_tokens=row["prompt_tokens"],
                        completion_tokens=row["completion_tokens"],
                        duration_seconds=row["duration_seconds"],
                        succeeded=bool(row["succeeded"]),
                        recorded_at=row["recorded_at"],
                    )
                )
            except ValidationError:
                # Skip, do not raise: same rule as load_nodes. One unparseable row
                # must not stop the Scheduler starting, and usage history is the
                # least load-bearing thing here -- unlike a balance, nobody is owed
                # it.
                logger.warning("persistence_skipped_unparseable_usage_row")
        return records

    async def save_usage(self, usage: UsageRecord) -> None:
        """Append one served request. There is no update path, by design."""
        self._conn.execute(
            "INSERT INTO usage_records (request_id, tenant_id, node_id, model, "
            "prompt_tokens, completion_tokens, duration_seconds, succeeded, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                usage.request_id,
                usage.tenant_id,
                usage.node_id,
                usage.model,
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.duration_seconds,
                int(usage.succeeded),
                usage.recorded_at,
            ),
        )
        self._conn.commit()

    async def close(self) -> None:
        """Close the connection. Safe to call more than once.

        Reads `_connection` directly rather than the `_conn` property: going through
        the property would OPEN the database in order to close it, which is how a
        store that was never used ends up creating a file on shutdown.
        """
        if self._connection is not None:
            self._connection.close()
            self._connection = None
