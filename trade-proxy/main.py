"""
Trade Proxy — Runs on Fly.io (Dublin) to bypass Polymarket geoblock.

The main app on Hetzner (Germany, blocked) sends trade requests here.
This proxy executes them via the CLOB API from an allowed region.
Protected by a shared secret token.
"""
import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from loguru import logger

app = FastAPI(title="Polymarket Trade Proxy")

# Auth
PROXY_SECRET = os.environ.get("PROXY_SECRET", "")

# Lazy-init CLOB client
_client = None


def get_client():
    global _client
    if _client is not None:
        return _client

    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds

    creds = ApiCreds(
        api_key=os.environ["POLY_API_KEY"],
        api_secret=os.environ["POLY_API_SECRET"],
        api_passphrase=os.environ.get("POLY_PASSPHRASE", ""),
    )

    _client = ClobClient(
        host="https://clob.polymarket.com",
        chain_id=137,
        key=os.environ["POLY_PRIVATE_KEY"],
        creds=creds,
        signature_type=1,  # Proxy wallet (Magic.link)
        funder=os.environ.get("POLY_WALLET_ADDRESS"),
    )

    try:
        _client.set_api_creds(_client.derive_api_key())
    except Exception:
        pass

    logger.info("CLOB client initialized")
    return _client


def verify_auth(authorization: str = Header(None)):
    if not PROXY_SECRET:
        raise HTTPException(500, "PROXY_SECRET not configured")
    if authorization != f"Bearer {PROXY_SECRET}":
        raise HTTPException(401, "Unauthorized")


# Cache neg-risk lookups per token (immutable so safe to cache forever)
_neg_risk_cache: dict = {}


def is_neg_risk(token_id: str) -> bool:
    """Polymarket has two Exchange contracts: regular and Neg-Risk.
    Multi-outcome events use Neg-Risk; binary YES/NO markets use regular.
    Authoritative source is the CLOB itself via client.get_neg_risk()."""
    if token_id in _neg_risk_cache:
        return _neg_risk_cache[token_id]
    try:
        client = get_client()
        result = bool(client.get_neg_risk(token_id))
    except Exception as e:
        logger.warning(f"CLOB neg_risk lookup failed for {token_id[:12]}: {e}")
        result = False
    _neg_risk_cache[token_id] = result
    logger.info(f"neg_risk[{token_id[:12]}] = {result}")
    return result


def check_orderbook_feasibility(token_id: str, expected_price: float) -> tuple:
    """Pre-flight orderbook checks before signing/posting.

    Refuses for two distinct reasons:
    1. **No orderbook** (404 from CLOB) — the market has expired or never had
       one. Polymarket's old short-window crypto markets fall here once their
       resolution window passes.
    2. **Cheapest ask is much worse than displayed price** — the asymmetric-bet
       thesis only works if you can actually buy at the displayed cheap price.
       If only expensive asks exist, the trade isn't the bet the agent thinks
       it is, and CLOB usually rejects with order_version_mismatch anyway.
    """
    try:
        client = get_client()
        book = client.get_order_book(token_id)
    except Exception as e:
        # Distinguish 404 ("no orderbook") from generic API failures.
        msg = str(e).lower()
        if "404" in msg or "no orderbook" in msg or "not found" in msg:
            return False, "no orderbook exists (market likely expired/closed)"
        logger.debug(f"orderbook feasibility check failed (proceeding): {e}")
        return True, "orderbook unreachable"

    if not book or not getattr(book, "asks", None):
        return False, "empty orderbook (no asks available)"

    # py-clob-client returns asks high→low; cheapest ask = last entry.
    try:
        first_ask = float(book.asks[0].price)
        last_ask = float(book.asks[-1].price)
        best_ask = min(first_ask, last_ask)
    except Exception:
        return True, "could not parse asks"

    if expected_price <= 0:
        return True, "no expected price to compare"
    # For sub-10c tokens (asymmetric bets): refuse if ask > 5x displayed price.
    if expected_price < 0.10 and best_ask > expected_price * 5:
        return False, f"orderbook too thin: best ask {best_ask*100:.2f}¢ vs displayed {expected_price*100:.3f}¢ ({best_ask/expected_price:.0f}× worse)"
    # For mid-range tokens: refuse if ask is >50% above displayed.
    if expected_price >= 0.10 and best_ask > expected_price * 1.5:
        return False, f"orderbook too thin: best ask {best_ask*100:.1f}¢ vs displayed {expected_price*100:.1f}¢"
    return True, "ok"


def check_market_tradeable(token_id: str, amount_usd: float = 0) -> tuple:
    """Pre-flight check: is the market actually tradeable AND does our order
    meet its minimum size?

    Returns (ok, reason). False reasons include: disputed UMA resolution,
    closed/inactive/archived market, OR amount below the market-specific
    `orderMinSize` (which Polymarket exposes per-market and varies from $1
    on standard binaries to $5+ on multi-outcome events with 0.001 ticks).

    Polymarket's CLOB rejects size-violations with the same confusing
    'order_version_mismatch' error as version mismatches — checking up
    front gives us a clean diagnostic."""
    import httpx
    try:
        r = httpx.get(
            "https://gamma-api.polymarket.com/markets",
            params={"clob_token_ids": token_id},
            timeout=10.0,
        )
        r.raise_for_status()
        markets = r.json() or []
        if not markets:
            return True, "no metadata, proceeding"
        m = markets[0]
        if m.get("closed"):
            return False, "market closed"
        if m.get("archived"):
            return False, "market archived"
        if not m.get("active", True):
            return False, "market inactive"
        # acceptingOrders=False is the most authoritative tradeability signal.
        if m.get("acceptingOrders") is False:
            return False, "market not accepting orders"
        # UMA states that block trading: 'proposed' (in liveness window),
        # 'disputed' / 'challenged' (under dispute), 'resolved' (final, no
        # more trading). 'None' / 'pending' / 'open' / 'unproposed' are fine.
        uma_status = (m.get("umaResolutionStatus") or "").lower()
        if uma_status in ("disputed", "challenged", "proposed", "resolved"):
            return False, f"UMA {uma_status} (no orders accepted)"
        # Order minimum (in USD-equivalent). Multi-outcome neg_risk markets
        # typically require $5+; standard binaries accept $1.
        order_min = float(m.get("orderMinSize") or 0)
        if amount_usd and order_min and amount_usd < order_min:
            return False, f"order below market minimum (need ≥${order_min:.2f}, got ${amount_usd:.2f})"
        return True, "ok"
    except Exception as e:
        logger.debug(f"tradeable check failed (proceeding anyway): {e}")
        return True, "metadata unreachable"


class BuyRequest(BaseModel):
    token_id: str
    amount_usd: float
    max_price: Optional[float] = None


class SellRequest(BaseModel):
    token_id: str
    shares: float
    min_price: Optional[float] = None


@app.get("/health")
async def health():
    return {"status": "ok", "region": os.environ.get("FLY_REGION", "unknown")}


@app.get("/version")
async def version():
    """Return installed py-clob-client version. Useful when Polymarket bumps
    their order schema and we get order_version_mismatch errors."""
    try:
        import importlib.metadata as md
        clob_v = md.version("py-clob-client")
    except Exception as e:
        clob_v = f"unknown ({e})"
    return {"py_clob_client": clob_v}


@app.post("/buy")
async def buy(req: BuyRequest, authorization: str = Header(None)):
    verify_auth(authorization)
    client = get_client()

    try:
        from py_clob_client.clob_types import MarketOrderArgs, OrderType, PartialCreateOrderOptions
        from py_clob_client.order_builder.constants import BUY

        # Pre-flight: skip clearly untradeable markets so callers see a
        # useful error rather than Polymarket's confusing version_mismatch.
        ok, reason = check_market_tradeable(req.token_id, amount_usd=req.amount_usd)
        if not ok:
            logger.warning(f"Buy refused: {reason} ({req.token_id[:12]})")
            return {"success": False, "error": f"market not tradeable: {reason}"}

        try:
            midpoint = float(client.get_midpoint(req.token_id))
        except Exception:
            midpoint = 0

        # Pre-flight orderbook check: if the displayed price is far from the
        # cheapest available ask, buying makes no sense (asymmetric bet thesis
        # collapses, and CLOB usually rejects with order_version_mismatch).
        ok, reason = check_orderbook_feasibility(req.token_id, midpoint)
        if not ok:
            logger.warning(f"Buy refused: {reason} ({req.token_id[:12]})")
            return {"success": False, "error": f"orderbook unfavorable: {reason}"}

        neg_risk = is_neg_risk(req.token_id)
        options = PartialCreateOrderOptions(neg_risk=neg_risk)

        order_args = MarketOrderArgs(
            token_id=req.token_id,
            amount=req.amount_usd,
            side=BUY,
        )
        signed_order = client.create_market_order(order_args, options)
        response = client.post_order(signed_order, OrderType.FOK)
        logger.info(f"Buy response: success={response.get('success') if response else 'no-response'} full={response}")

        if response and response.get("success"):
            order_id = response.get("orderID") or response.get("order_id")
            shares = req.amount_usd / midpoint if midpoint > 0 else 0
            return {
                "success": True,
                "order_id": order_id,
                "price": midpoint,
                "shares": shares,
                "neg_risk": neg_risk,
            }
        else:
            # Surface the FULL response so we can diagnose ambiguous errors
            error = response.get("errorMsg") or response.get("error") or "Unknown"
            return {
                "success": False,
                "error": error,
                "price": midpoint,
                "neg_risk": neg_risk,
                "full_response": response,
            }

    except Exception as e:
        logger.error(f"Buy error: {e}")
        return {"success": False, "error": str(e), "exception_type": type(e).__name__}


@app.post("/sell")
async def sell(req: SellRequest, authorization: str = Header(None)):
    verify_auth(authorization)
    client = get_client()

    try:
        from py_clob_client.clob_types import MarketOrderArgs, OrderType, PartialCreateOrderOptions
        from py_clob_client.order_builder.constants import SELL

        ok, reason = check_market_tradeable(req.token_id)
        if not ok:
            logger.warning(f"Sell refused: {reason} ({req.token_id[:12]})")
            return {"success": False, "error": f"market not tradeable: {reason}"}

        try:
            midpoint = float(client.get_midpoint(req.token_id))
        except Exception:
            midpoint = 0

        amount_usd = req.shares * midpoint if midpoint > 0 else req.shares

        neg_risk = is_neg_risk(req.token_id)
        options = PartialCreateOrderOptions(neg_risk=neg_risk)

        order_args = MarketOrderArgs(
            token_id=req.token_id,
            amount=amount_usd,
            side=SELL,
        )
        signed_order = client.create_market_order(order_args, options)
        response = client.post_order(signed_order, OrderType.FOK)

        if response and response.get("success"):
            order_id = response.get("orderID") or response.get("order_id")
            return {
                "success": True,
                "order_id": order_id,
                "price": midpoint,
                "shares": req.shares,
                "neg_risk": neg_risk,
            }
        else:
            error = response.get("errorMsg") or response.get("error") or "Unknown"
            return {"success": False, "error": error, "price": midpoint, "neg_risk": neg_risk}

    except Exception as e:
        logger.error(f"Sell error: {e}")
        return {"success": False, "error": str(e)}


@app.get("/reddit/{subreddit}/{sort}")
async def reddit_proxy(subreddit: str, sort: str, limit: int = 50, authorization: str = Header(None)):
    """Reddit blocks Hetzner / data-center IPs. Proxy through Tokyo."""
    verify_auth(authorization)
    if sort not in ("hot", "new", "top", "rising"):
        raise HTTPException(400, "bad sort")
    import httpx
    headers = {"User-Agent": "polymarket-bot/1.0 (proxy; research@jorisfalter.com)"}
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            r = await client.get(url, params={"limit": limit})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"error": str(e), "data": {"children": []}}


@app.get("/balance")
async def balance(authorization: str = Header(None)):
    verify_auth(authorization)
    client = get_client()

    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=1)
        result = client.get_balance_allowance(params)
        raw = result.get("balance", 0) if isinstance(result, dict) else 0
        return {"balance": float(raw) / 1e6}
    except Exception as e:
        return {"balance": 0, "error": str(e)}
