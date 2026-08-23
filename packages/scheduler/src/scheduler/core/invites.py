"""Invite codes: who is allowed to register a node (decision D4).

Registration was gated by `SCHEDULER_NETWORK_AUTH_TOKEN` alone -- one fleet-wide
secret every node presents. That is admission control, but it answers neither of the
questions an operator actually has:

* **Who vouched for this host?** A shared secret records nothing. Every node looks
  identical to every other, so "which of these did I mean to admit" is unanswerable.
* **How do I remove one host?** Rotating the fleet token removes *all* of them and
  requires reconfiguring every legitimate node at the same time. There is no
  proportionate response between "do nothing" and "break the fleet".

`docs/decisions/D4-sybil-resistance.md` chose invite codes over proof-of-work
(punishes the honest low-power host most), stake (needs a token, needs law), and
hardware attestation (excludes consumer GPUs, which are the entire supply).

## Design points that carry weight

**Hashed at rest.** A code is a bearer credential, so the store holds SHA-256 and
never the code itself. An operator who loses one reissues rather than looks it up --
the same trade a password hash makes, for the same reason.

**Single-use by default, with an explicit `max_uses`.** A code that admits N nodes is
a deliberate choice someone typed, not an accident of the schema.

**Revoking does not evict.** Revocation stops *future* registrations under a code and
leaves nodes already admitted alone. Conflating the two would make revocation too
dangerous to reach for, and eviction already exists as `DELETE /nodes/{id}`.

**Open registration stays possible and is LOUD.** With no codes configured the
Scheduler admits anyone, and says so at startup. A silent fallback would recreate
exactly the hole this closes -- and this is not hypothetical: the fallback is the
state every existing deployment is already in, so it has to keep working while being
impossible to be in unknowingly.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from scheduler.persistence import SchedulerStore

logger = logging.getLogger(__name__)

# 32 bytes of urandom, hex. Long enough that guessing is not a strategy, short enough
# to paste into an installer prompt without wrapping.
_CODE_BYTES = 32


def hash_code(code: str) -> str:
    """SHA-256 of an invite code.

    Plain SHA-256 rather than a password KDF on purpose: a code is 32 bytes of
    urandom, not a human-chosen secret, so there is no dictionary to slow down and
    the only attack is brute force over a 256-bit space. Argon2 here would buy
    nothing and cost a dependency.
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def generate_code() -> str:
    """A fresh invite code. Returned once; only its hash is ever stored."""
    return secrets.token_hex(_CODE_BYTES)


class InviteCode(BaseModel):
    """One issued invite, as persisted. Never holds the code itself."""

    model_config = ConfigDict(extra="forbid")

    code_hash: str = Field(description="SHA-256 of the code. The code is not recoverable.")
    label: str = Field(default="", description="Operator's note: who this was issued to")
    max_uses: int = Field(default=1, ge=1, description="How many nodes this may admit")
    uses: int = Field(default=0, ge=0, description="How many it has admitted")
    revoked: bool = Field(default=False)
    created_at: float = Field(default_factory=time.time)

    @property
    def spent(self) -> bool:
        return self.uses >= self.max_uses

    @property
    def usable(self) -> bool:
        return not self.revoked and not self.spent


class InviteRegistry:
    """Issue, verify, reserve and revoke invite codes."""

    def __init__(self, store: SchedulerStore | None = None) -> None:
        self._invites: dict[str, InviteCode] = {}
        self._store = store
        # Serialises check-and-consume (`reserve`) and give-back (`refund`). Each
        # has awaits inside (the store write), so without the lock two concurrent
        # registrations could interleave between reading a code's state and
        # updating it -- which is precisely the hole reserve exists to close.
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        """Refill from the store. Call once, at startup."""
        if self._store is None:
            return
        for invite in await self._store.load_invites():
            self._invites[invite.code_hash] = invite
        logger.info("invite_registry_loaded: invites=%d", len(self._invites))

    @property
    def enforcing(self) -> bool:
        """True once the operator has issued ANY code, spent and revoked included.

        Admission is enforced only when the operator has issued something. With no
        codes at all, requiring one would lock every existing deployment out of its
        own fleet on upgrade -- so the fallback is open registration, and
        `warn_if_open` makes sure nobody is in that state by accident.

        **This deliberately does NOT mean "a usable code exists right now."** That
        was the first implementation and it is a hole: redeeming the last single-use
        code leaves zero usable invites, `enforcing` flips back to False, and
        registration silently reopens to anyone holding the fleet token -- so the
        admission control switches itself off at precisely the moment it has finished
        being used. Caught by
        `test_a_single_use_code_admits_exactly_one_node`.

        Once you are in invite mode you stay in it. Getting back to open registration
        means deleting the invite records, which is a deliberate act.
        """
        return bool(self._invites)

    def warn_if_open(self) -> None:
        """Say loudly, at startup, that anyone may register."""
        if not self.enforcing:
            logger.warning(
                "invite_admission_disabled: no usable invite codes are configured, so "
                "ANY caller holding the network auth token may register a node. Issue "
                "one with scripts/mint_invite.py to enforce per-node admission. "
                "See docs/decisions/D4-sybil-resistance.md."
            )

    async def issue(self, label: str = "", max_uses: int = 1) -> tuple[str, InviteCode]:
        """Create a code. Returns `(code, record)` -- the code is shown once."""
        code = generate_code()
        invite = InviteCode(code_hash=hash_code(code), label=label, max_uses=max_uses)
        self._invites[invite.code_hash] = invite
        if self._store is not None:
            await self._store.save_invite(invite)
        logger.info("invite_issued: label=%s max_uses=%d", label or "(none)", max_uses)
        return code, invite

    def verify(self, code: str | None) -> InviteCode | None:
        """The usable invite matching `code`, or None.

        Constant-time comparison is not needed and is not used: the lookup is by
        hash of the presented value, so there is no secret-dependent comparison to
        leak timing through -- the dictionary probe reveals only whether a hash
        exists, which is what the caller is being told anyway.
        """
        if not code:
            return None
        invite = self._invites.get(hash_code(code))
        if invite is None or not invite.usable:
            return None
        return invite

    async def reserve(self, code: str | None, node_id: str) -> InviteCode | None:
        """Atomically check AND consume one use of `code` for `node_id`.

        This replaces the old verify-then-redeem split, and the split was the
        bug: admission verified the code before registration, redemption happened
        after it -- two awaits apart, with the redeem result discarded -- so two
        concurrent registrations could both pass admission on one single-use code.
        Reserve is one critical section under `self._lock`: a use is spent the
        moment it is checked, so of two racing registrations exactly one sees a
        usable invite. `refund` gives the use back if admission then fails, which
        keeps the property ROADMAP 1.6 needs -- a node re-registering after a 409
        does not burn its operator's invite.

        Persisted inside the critical section, as redemption was: a crash after
        admitting a node must not leave the use unrecorded for a second one.

        Returns the invite whose use was reserved, or None when the code is not
        usable (unknown, revoked, or spent). The return value is what `refund`
        refunds against -- pass it through, do not re-verify.
        """
        async with self._lock:
            invite = self.verify(code)
            if invite is None:
                return None
            invite.uses += 1
            if self._store is not None:
                await self._store.save_invite(invite)
        logger.info(
            "invite_reserved: node_id=%s label=%s uses=%d/%d",
            node_id,
            invite.label or "(none)",
            invite.uses,
            invite.max_uses,
        )
        return invite

    async def refund(self, invite: InviteCode, node_id: str) -> None:
        """Give back the use `reserve` consumed, because admission then failed."""
        async with self._lock:
            if invite.uses > 0:
                invite.uses -= 1
            if self._store is not None:
                await self._store.save_invite(invite)
        logger.info(
            "invite_refunded: node_id=%s label=%s uses=%d/%d",
            node_id,
            invite.label or "(none)",
            invite.uses,
            invite.max_uses,
        )

    async def revoke(self, code: str) -> bool:
        """Stop future registrations under `code`. Already-admitted nodes stay.

        Returns whether anything changed, so a caller can tell "revoked" from "there
        was nothing to revoke" -- the same distinction ROADMAP 2.5 made eviction
        report.
        """
        invite = self._invites.get(hash_code(code))
        if invite is None or invite.revoked:
            return False
        invite.revoked = True
        if self._store is not None:
            await self._store.save_invite(invite)
        logger.info("invite_revoked: label=%s", invite.label or "(none)")
        return True

    def summary(self) -> list[dict[str, object]]:
        """Operator view. Deliberately never includes a code or a hash."""
        return [
            {
                "label": invite.label,
                "max_uses": invite.max_uses,
                "uses": invite.uses,
                "revoked": invite.revoked,
                "usable": invite.usable,
                "created_at": invite.created_at,
            }
            for invite in self._invites.values()
        ]
