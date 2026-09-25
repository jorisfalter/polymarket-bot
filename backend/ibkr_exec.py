"""
IBKR execution infra — built 2026-09-25, ARMED BUT SAFE.

Decision 2026-09-17 stands: NO real money until the promotion criteria in
CLAUDE.md are met. This module is the ready-to-go rails for that moment:

  - get_quote()      : live bid/ask/last via IB Gateway
  - preview_order()  : IBKR whatIf order — REAL commission + margin numbers
                       from IBKR's own engine, nothing is placed. This is
                       "echte quotes, echte fees zien, niet traden".
  - place_order()    : hard-gated behind settings.ibkr_dry_run (default True).
                       In dry-run it journals what it WOULD have done.

Gateway: docker compose --profile ibkr up -d ib-gateway (needs IBKR_USERNAME/
IBKR_PASSWORD in .env + an IB Key 2FA approval on Joris' phone at login).
Connection is lazy and per-call; the app runs fine with the gateway down.

Journal: data/ibkr_exec.jsonl (PREVIEW / DRY_RUN_ORDER / ORDER records).
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path("data/ibkr_exec.jsonl")

try:
    from ib_async import IB, Stock, MarketOrder, LimitOrder  # noqa: F401
    HAS_IB = True
except Exception as e:  # broad on purpose — a broken lib must not kill the app
    HAS_IB = False
    logger.warning(f"ib_async unavailable ({e}) — IBKR exec disabled")


def _journal(record: dict):
    record["ts"] = datetime.now(timezone.utc).isoformat()
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


class IBKRExecutor:
    """Thin, connection-per-call wrapper around IB Gateway."""

    async def _connect(self) -> Optional["IB"]:
        if not (HAS_IB and settings.ibkr_enabled):
            return None
        ib = IB()
        try:
            await ib.connectAsync(settings.ibkr_gateway_host,
                                  settings.ibkr_gateway_port,
                                  clientId=settings.ibkr_client_id, timeout=10)
            return ib
        except Exception as e:
            logger.warning(f"IB Gateway unreachable: {e}")
            return None

    async def get_quote(self, symbol: str) -> Optional[dict]:
        ib = await self._connect()
        if not ib:
            return None
        try:
            contract = Stock(symbol, "SMART", "USD")
            await ib.qualifyContractsAsync(contract)
            tick = await ib.reqTickersAsync(contract)
            t = tick[0]
            return {"symbol": symbol, "bid": t.bid, "ask": t.ask,
                    "last": t.last, "close": t.close,
                    "ts": datetime.now(timezone.utc).isoformat()}
        finally:
            ib.disconnect()

    async def preview_order(self, symbol: str, qty: float,
                            side: str = "BUY") -> Optional[dict]:
        """IBKR whatIf: real commission/margin estimate, nothing placed."""
        ib = await self._connect()
        if not ib:
            return None
        try:
            contract = Stock(symbol, "SMART", "USD")
            await ib.qualifyContractsAsync(contract)
            order = MarketOrder(side, qty)
            state = await ib.whatIfOrderAsync(contract, order)
            preview = {
                "symbol": symbol, "side": side, "qty": qty,
                "commission": getattr(state, "maxCommission", None) or state.commission,
                "commission_currency": state.commissionCurrency,
                "init_margin_change": state.initMarginChange,
                "equity_with_loan_after": state.equityWithLoanAfter,
            }
            _journal({"event": "PREVIEW", **preview})
            return preview
        finally:
            ib.disconnect()

    async def place_order(self, symbol: str, qty: float, side: str = "BUY",
                          limit: Optional[float] = None,
                          reason: str = "") -> dict:
        """HARD-GATED: dry-run journals and returns without touching IBKR."""
        intent = {"symbol": symbol, "side": side, "qty": qty,
                  "limit": limit, "reason": reason}
        if settings.ibkr_dry_run:
            _journal({"event": "DRY_RUN_ORDER", **intent,
                      "note": "ibkr_dry_run=True — order NOT placed (by design)"})
            return {"status": "dry_run", **intent}
        # Live path — only reachable after the user flips ibkr_dry_run in
        # config, which per CLAUDE.md requires explicit approval from Joris.
        ib = await self._connect()
        if not ib:
            return {"status": "error", "error": "gateway unreachable"}
        try:
            contract = Stock(symbol, "SMART", "USD")
            await ib.qualifyContractsAsync(contract)
            order = LimitOrder(side, qty, limit) if limit else MarketOrder(side, qty)
            trade = ib.placeOrder(contract, order)
            await trade.orderStatusEvent
            result = {"status": trade.orderStatus.status, **intent,
                      "order_id": trade.order.orderId}
            _journal({"event": "ORDER", **result})
            return result
        finally:
            ib.disconnect()


ibkr = IBKRExecutor()
