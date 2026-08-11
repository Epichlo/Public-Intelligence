"""Credit Ledger engine tracking compute provider contribution and requester balances."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from scheduler.persistence import SchedulerStore

logger = logging.getLogger(__name__)


class CreditAccount(BaseModel):
    """Account entry tracking earned and consumed credits."""

    account_id: str = Field(description="Tenant or Node identifier")
    earned_credits: float = Field(
        default=0.0, ge=0.0, description="Total credits earned from hosting compute"
    )
    consumed_credits: float = Field(
        default=0.0, ge=0.0, description="Total credits consumed for inference"
    )
    updated_at: float = Field(default_factory=time.time, description="Last update epoch timestamp")

    @property
    def net_balance(self) -> float:
        """Net credit balance."""
        return self.earned_credits - self.consumed_credits


class CreditLedger:
    """Threadsafe Tokenless Fiat Credit Ledger.

    **This is the state that nothing else can re-tell the Scheduler.** A node that
    outlives a Scheduler restart re-registers itself and restates its hardware; a
    balance has no such source, because the node never knew what it had earned.
    That asymmetry is why ROADMAP 2.1 exists, and why the store here matters more
    than the one on `NodeRegistry`.

    Attaching a store makes balances durable. It does **not** make them accrue --
    nothing in the running Scheduler calls `record_host_contribution` yet. Wiring
    accrual to real usage is ROADMAP 3.2/3.3.
    """

    CREDITS_PER_GB_VRAM_HOUR: float = 100.0

    # Fallback rate for hosts with no GPU, whose scarce resource is memory.
    #
    # Without it a CPU-only host accrues EXACTLY zero forever: the VRAM term is a
    # product, and `vram_total_gb` is 0.0 for such a node. That was not a rounding
    # artefact, it was the whole formula -- found on the machine that first served a
    # real request over the mesh, which was recorded as having contributed nothing.
    # ROADMAP 1.2 deliberately made these nodes dispatchable; 3.3 then measured
    # contribution in a unit they can never have.
    #
    # **One tenth is a guess.** Nobody has measured what a GPU-hour is worth against
    # a CPU-hour on this network, because there is no network (D6) -- the same
    # honesty the watcher's thresholds carry. Only the DIRECTION is defensible: a
    # GPU-hour is the scarce thing being shared, so crediting CPU work at parity
    # would make contributing no GPU the cheapest way to earn.
    CREDITS_PER_GB_RAM_HOUR: float = 10.0

    def __init__(self, store: SchedulerStore | None = None) -> None:
        """Initialize CreditLedger.

        Args:
            store: Where to write balances so they survive a restart. `None` means
                in-memory only, which is the behaviour this class had before
                ROADMAP 2.1.
        """
        self._accounts: dict[str, CreditAccount] = {}
        self._store = store

    async def load(self) -> None:
        """Refill balances from the store. Call once, at startup.

        A no-op without a store.
        """
        if self._store is None:
            return
        accounts = await self._store.load_accounts()
        for account in accounts:
            self._accounts[account.account_id] = account
        logger.info("credit_ledger_loaded: accounts=%d", len(accounts))

    def balances(self) -> dict[str, float]:
        """Return each account's net balance, for status and test assertions."""
        return {account_id: account.net_balance for account_id, account in self._accounts.items()}

    def get_or_create_account(self, account_id: str) -> CreditAccount:
        """Get or initialize account for given ID.

        Stays synchronous, and deliberately does **not** persist. A zeroed account
        is not a fact about anything -- it is the answer to a question someone
        asked. Writing one would let any caller that merely *enquired* about an
        account grow the database, which matters once account ids arrive from
        requester credentials (ROADMAP 3.1). The two methods below persist, because
        those change a balance.

        Args:
            account_id: Account identifier.

        Returns:
            CreditAccount instance.
        """
        if account_id not in self._accounts:
            self._accounts[account_id] = CreditAccount(account_id=account_id)
        return self._accounts[account_id]

    async def record_host_contribution(
        self, node_id: str, vram_gb: float, duration_seconds: float, ram_gb: float = 0.0
    ) -> CreditAccount:
        """Accrue credits to a host for work it actually did.

        VRAM-hours where there is a GPU, RAM-hours where there is not. The RAM term
        is a **fallback, not an addition**: a GPU host's credit is unchanged by
        declaring its RAM, because crediting both would quietly raise what every
        existing host earns -- a repricing dressed as a bug fix, which D2 settled is
        not something to do by accident.

        Args:
            node_id: Node identifier.
            vram_gb: Total VRAM in GB. 0.0 on a CPU-only host.
            duration_seconds: Duration hosted in seconds.
            ram_gb: Total system RAM in GB, used only when `vram_gb` is zero.
                Defaults to 0.0 so existing callers keep the previous behaviour.

        Returns:
            Updated CreditAccount.
        """
        vram_gb = max(0.0, float(vram_gb))
        ram_gb = max(0.0, float(ram_gb))
        duration_seconds = max(0.0, float(duration_seconds))
        hours = duration_seconds / 3600.0
        if vram_gb > 0.0:
            earned = vram_gb * hours * self.CREDITS_PER_GB_VRAM_HOUR
        else:
            earned = ram_gb * hours * self.CREDITS_PER_GB_RAM_HOUR
        account = self.get_or_create_account(node_id)
        account.earned_credits += earned
        account.updated_at = time.time()
        if self._store is not None:
            await self._store.save_account(account)
        logger.info(
            "credit_accrued: node_id=%s earned=%.2f new_balance=%.2f",
            node_id,
            earned,
            account.net_balance,
        )
        return account

    async def deduct_usage(self, account_id: str, amount: float) -> CreditAccount:
        """Deduct credits consumed for inference.

        Args:
            account_id: Account identifier.
            amount: Number of credits to deduct. Renamed from `credits`, which
                shadowed the Python builtin.

        Returns:
            Updated CreditAccount.
        """
        account = self.get_or_create_account(account_id)
        account.consumed_credits += max(0.0, amount)
        account.updated_at = time.time()
        if self._store is not None:
            await self._store.save_account(account)
        return account
