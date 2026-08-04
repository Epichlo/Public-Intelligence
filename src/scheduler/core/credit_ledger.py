"""Credit Ledger engine tracking compute provider contribution and requester balances."""

import logging
import time

from pydantic import BaseModel, Field

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
    """Threadsafe Tokenless Fiat Credit Ledger."""

    CREDITS_PER_GB_VRAM_HOUR: float = 100.0

    def __init__(self) -> None:
        """Initialize CreditLedger."""
        self._accounts: dict[str, CreditAccount] = {}

    def get_or_create_account(self, account_id: str) -> CreditAccount:
        """Get or initialize account for given ID.

        Args:
            account_id: Account identifier.

        Returns:
            CreditAccount instance.
        """
        if account_id not in self._accounts:
            self._accounts[account_id] = CreditAccount(account_id=account_id)
        return self._accounts[account_id]

    def record_host_contribution(
        self, node_id: str, vram_gb: float, duration_seconds: float
    ) -> CreditAccount:
        """Accrue earned credits to a compute host based on VRAM-Hours provided.

        Args:
            node_id: Node identifier.
            vram_gb: Total VRAM allocated in GB.
            duration_seconds: Duration hosted in seconds.

        Returns:
            Updated CreditAccount.
        """
        vram_gb = max(0.0, float(vram_gb))
        duration_seconds = max(0.0, float(duration_seconds))
        hours = duration_seconds / 3600.0
        earned = vram_gb * hours * self.CREDITS_PER_GB_VRAM_HOUR
        account = self.get_or_create_account(node_id)
        account.earned_credits += earned
        account.updated_at = time.time()
        logger.info(
            "credit_accrued: node_id=%s earned=%.2f new_balance=%.2f",
            node_id,
            earned,
            account.net_balance,
        )
        return account

    def deduct_usage(self, account_id: str, amount: float) -> CreditAccount:
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
        return account
