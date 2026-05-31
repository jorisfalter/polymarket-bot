"""
Thin async wrapper around the Fly.io trade-proxy's maker-mode endpoints.

The trade-proxy (trade-proxy/main.py on Fly Tokyo) exposes /limit, /orders,
DELETE /orders/{id} for GTC limit-order workflows. This module is the only
place backend/market_maker.py talks to those endpoints — keeping all the
auth + retry + parsing concerns in one spot.

For market orders (FAK buys/sells, emergency exits) we still go through
backend/auto_seller.py's existing /buy and /sell calls.
"""
from __future__ import annotations
import httpx
from loguru import logger
from typing import Optional

from .config import settings


def _enabled() -> bool:
    return bool(settings.trade_proxy_url and settings.trade_proxy_secret)


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {settings.trade_proxy_secret}"}


async def place_limit(
    token_id: str,
    price: float,
    size: float,
    side: str,
    condition_id: Optional[str] = None,
    timeout: float = 30.0,
) -> Optional[dict]:
    """Post a GTC limit order. Returns the proxy response dict, or None if
    the proxy is unconfigured. Caller checks response['success'].

    size is in SHARES (NOT usd). For a BUY at price p with $S stake,
    pass size = S / p.
    """
    if not _enabled():
        logger.warning("place_limit called but trade_proxy not configured")
        return None
    payload = {
        "token_id": token_id,
        "price": round(float(price), 4),
        "size": round(float(size), 4),
        "side": side.upper(),
        "condition_id": condition_id,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as cx:
            r = await cx.post(
                f"{settings.trade_proxy_url}/limit",
                json=payload,
                headers=_auth_headers(),
            )
        return r.json()
    except Exception as e:
        logger.error(f"place_limit error: {e}")
        return {"success": False, "error": str(e)}


async def list_open_orders(
    token_id: Optional[str] = None,
    timeout: float = 15.0,
) -> list[dict]:
    """List open limit orders on our wallet. Optional token_id filter.
    Returns the orders list (empty on error or no proxy)."""
    if not _enabled():
        return []
    params = {"token_id": token_id} if token_id else None
    try:
        async with httpx.AsyncClient(timeout=timeout) as cx:
            r = await cx.get(
                f"{settings.trade_proxy_url}/orders",
                params=params,
                headers=_auth_headers(),
            )
        data = r.json()
        return data.get("orders", []) if isinstance(data, dict) else []
    except Exception as e:
        logger.error(f"list_open_orders error: {e}")
        return []


async def cancel_order(order_id: str, timeout: float = 15.0) -> bool:
    """Cancel an open order. Returns True if Polymarket confirms cancellation.

    The proxy returns {"success": True, "response": {"canceled": [...],
    "not_canceled": {...}}}. We treat the order_id appearing in `canceled`
    as success; appearing in `not_canceled` as failure (already filled
    or already cancelled).
    """
    if not _enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout) as cx:
            r = await cx.delete(
                f"{settings.trade_proxy_url}/orders/{order_id}",
                headers=_auth_headers(),
            )
        data = r.json()
        if not data.get("success"):
            return False
        inner = data.get("response") or {}
        canceled = inner.get("canceled") or []
        return order_id in canceled
    except Exception as e:
        logger.error(f"cancel_order error for {order_id}: {e}")
        return False
