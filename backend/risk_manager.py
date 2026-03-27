"""
Risk Manager — Hard safety gate for all strategy trades.

Every trade must pass through approve_trade() before execution.
Limits are hard-coded and cannot be overridden by config.
"""
from typing import Tuple
from loguru import logger

from .config import settings
from .trade_journal import journal
from .auto_seller import auto_seller


class RiskManager:
    """Central risk gate. All strategy trades must be approved here."""

    # Hard limits — these are the absolute maximums
    HARD_MAX_EXPOSURE = 100.0    # $100 total across all positions
    HARD_MAX_PER_TRADE = 25.0    # $25 per trade
    HARD_BALANCE_FLOOR = 840.0   # Never let balance drop below $840
    HARD_MAX_POSITIONS = 5       # Max 5 concurrent positions

    async def approve_trade(
        self, strategy: str, amount_usd: float, market_slug: str, token_id: str
    ) -> Tuple[bool, str]:
        """
        Check all risk limits before allowing a trade.
        Returns (approved, reason).
        """
        # 1. Check per-trade limit
        max_per_trade = min(self.HARD_MAX_PER_TRADE, settings.strategy_max_per_trade)
        if amount_usd > max_per_trade:
            return False, f"Amount ${amount_usd:.2f} exceeds per-trade limit ${max_per_trade:.2f}"

        # 2. Check open positions count
        open_positions = journal.get_open_positions()
        max_positions = min(self.HARD_MAX_POSITIONS, settings.strategy_max_open_positions)
        if len(open_positions) >= max_positions:
            return False, f"Already at max positions ({len(open_positions)}/{max_positions})"

        # 3. Check for duplicate market
        if journal.has_open_position(token_id):
            return False, f"Already have open position for token {token_id[:16]}"

        # 4. Check total exposure
        current_exposure = journal.get_total_exposure()
        max_exposure = min(self.HARD_MAX_EXPOSURE, settings.strategy_max_total_exposure)
        if current_exposure + amount_usd > max_exposure:
            return False, f"Exposure ${current_exposure + amount_usd:.2f} would exceed limit ${max_exposure:.2f}"

        # 5. Check real USDC balance (most important check)
        try:
            balance = await get_usdc_balance()
            balance_floor = max(self.HARD_BALANCE_FLOOR, settings.strategy_balance_floor)
            if balance - amount_usd < balance_floor:
                return False, f"Balance ${balance:.2f} - ${amount_usd:.2f} would drop below floor ${balance_floor:.2f}"
            logger.info(f"💰 Balance check: ${balance:.2f} - ${amount_usd:.2f} = ${balance - amount_usd:.2f} (floor: ${balance_floor:.2f})")
        except Exception as e:
            return False, f"Could not verify balance: {e}"

        logger.info(f"✅ Risk approved: {strategy} ${amount_usd:.2f} on {market_slug[:30]}")
        return True, "approved"


async def get_usdc_balance() -> float:
    """Fetch current USDC balance from the Polymarket account."""
    if not auto_seller.is_ready():
        raise RuntimeError("Auto-seller not initialized — cannot check balance")
    balance = auto_seller.get_usdc_balance()
    if balance is None:
        raise RuntimeError("Could not fetch USDC balance")
    return balance


# Singleton
risk_manager = RiskManager()
