"""
Auto-Sell Module

Executes sell orders on Polymarket using py-clob-client SDK.
Requires private key and API credentials in .env.
"""
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from loguru import logger

from .config import settings

# Try to import py-clob-client
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL
    HAS_CLOB_CLIENT = True
except ImportError:
    HAS_CLOB_CLIENT = False
    logger.warning("py-clob-client not installed. Auto-sell disabled. Run: pip install py-clob-client")


@dataclass
class SellResult:
    """Result of a sell order attempt."""
    success: bool
    trade_id: str
    token_id: str
    shares_sold: float
    price: float
    order_id: Optional[str] = None
    tx_hash: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()


class AutoSeller:
    """
    Handles automatic selling of positions on Polymarket.
    Uses py-clob-client SDK for order execution.
    """

    # Polygon mainnet chain ID
    CHAIN_ID = 137

    def __init__(self):
        self.client: Optional[ClobClient] = None
        self.initialized = False
        self._init_client()

    def _init_client(self):
        """Initialize the CLOB client with credentials."""
        if not HAS_CLOB_CLIENT:
            logger.error("py-clob-client not available")
            return

        if not settings.poly_private_key:
            logger.warning("POLY_PRIVATE_KEY not set - auto-sell disabled")
            return

        if not settings.poly_api_key or not settings.poly_api_secret:
            logger.warning("POLY_API_KEY/SECRET not set - auto-sell disabled")
            return

        try:
            # Create API credentials
            creds = ApiCreds(
                api_key=settings.poly_api_key,
                api_secret=settings.poly_api_secret,
                api_passphrase=settings.poly_passphrase or "",
            )

            # Initialize client
            self.client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=self.CHAIN_ID,
                key=settings.poly_private_key,
                creds=creds,
            )

            # Derive API credentials if needed (links wallet to API key)
            # This is needed on first use
            try:
                self.client.set_api_creds(self.client.derive_api_key())
                logger.info("Derived new API credentials for wallet")
            except Exception:
                # Already have valid creds
                pass

            self.initialized = True
            wallet_addr = settings.poly_wallet_address or "unknown"
            logger.info(f"✅ Auto-seller initialized for wallet {wallet_addr[:16]}...")

        except Exception as e:
            logger.error(f"Failed to initialize auto-seller: {e}")
            self.client = None

    def is_ready(self) -> bool:
        """Check if auto-seller is ready to execute trades."""
        return self.initialized and self.client is not None

    def get_status(self) -> Dict[str, Any]:
        """Get auto-seller status."""
        return {
            "ready": self.is_ready(),
            "has_clob_client": HAS_CLOB_CLIENT,
            "has_private_key": bool(settings.poly_private_key),
            "has_api_credentials": bool(settings.poly_api_key and settings.poly_api_secret),
            "wallet_address": settings.poly_wallet_address[:16] + "..." if settings.poly_wallet_address else None,
        }

    async def execute_sell(
        self,
        trade_id: str,
        token_id: str,
        shares: float,
        min_price: Optional[float] = None,
    ) -> SellResult:
        """
        Execute a market sell order.

        Args:
            trade_id: Internal trade tracking ID
            token_id: Polymarket CLOB token ID
            shares: Number of shares to sell
            min_price: Minimum acceptable price (0-1 scale), or None for market order

        Returns:
            SellResult with order details or error
        """
        if not self.is_ready():
            return SellResult(
                success=False,
                trade_id=trade_id,
                token_id=token_id,
                shares_sold=0,
                price=0,
                error="Auto-seller not initialized. Check credentials.",
            )

        try:
            logger.info(f"Executing sell: {shares} shares of {token_id[:20]}...")

            # Get current market price for the sell side
            book = self.client.get_order_book(token_id)
            if not book or not book.bids:
                return SellResult(
                    success=False,
                    trade_id=trade_id,
                    token_id=token_id,
                    shares_sold=0,
                    price=0,
                    error="No bids available in order book",
                )

            # Best bid is what we'll get for a market sell
            best_bid = float(book.bids[0].price)

            # Check minimum price if specified
            if min_price is not None and best_bid < min_price:
                return SellResult(
                    success=False,
                    trade_id=trade_id,
                    token_id=token_id,
                    shares_sold=0,
                    price=best_bid,
                    error=f"Price {best_bid:.4f} below minimum {min_price:.4f}",
                )

            # Create and execute the sell order
            # Using a limit order at best bid for better execution
            order_args = OrderArgs(
                token_id=token_id,
                price=best_bid,
                size=shares,
                side=SELL,
            )

            # Create signed order
            signed_order = self.client.create_order(order_args)

            # Submit order
            response = self.client.post_order(signed_order, OrderType.GTC)

            if response and response.get("success"):
                order_id = response.get("orderID") or response.get("order_id")
                logger.info(f"✅ Sell order placed: {order_id}")

                return SellResult(
                    success=True,
                    trade_id=trade_id,
                    token_id=token_id,
                    shares_sold=shares,
                    price=best_bid,
                    order_id=order_id,
                )
            else:
                error_msg = response.get("errorMsg") or response.get("error") or "Unknown error"
                return SellResult(
                    success=False,
                    trade_id=trade_id,
                    token_id=token_id,
                    shares_sold=0,
                    price=best_bid,
                    error=f"Order rejected: {error_msg}",
                )

        except Exception as e:
            logger.error(f"Sell execution error: {e}")
            return SellResult(
                success=False,
                trade_id=trade_id,
                token_id=token_id,
                shares_sold=0,
                price=0,
                error=str(e),
            )

    async def execute_market_sell(
        self,
        trade_id: str,
        token_id: str,
        shares: float,
    ) -> SellResult:
        """
        Execute a market sell (best available price).
        Wrapper around execute_sell with no min_price.
        """
        return await self.execute_sell(trade_id, token_id, shares, min_price=None)

    def get_position(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Get current position for a token."""
        if not self.is_ready():
            return None

        try:
            # Get positions for this asset
            positions = self.client.get_positions()
            for pos in positions:
                if pos.get("asset_id") == token_id or pos.get("token_id") == token_id:
                    return pos
            return None
        except Exception as e:
            logger.error(f"Error getting position: {e}")
            return None

    def get_balances(self) -> Dict[str, Any]:
        """Get wallet balances."""
        if not self.is_ready():
            return {"error": "Not initialized"}

        try:
            # Get USDC balance and positions
            return {
                "positions": self.client.get_positions() or [],
            }
        except Exception as e:
            logger.error(f"Error getting balances: {e}")
            return {"error": str(e)}


# Singleton instance
auto_seller = AutoSeller()
