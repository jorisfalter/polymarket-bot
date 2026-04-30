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


# Cache neg-risk lookups so we don't hit Gamma on every order.
_neg_risk_cache: dict = {}


def is_neg_risk(token_id: str) -> bool:
    """Polymarket has two Exchange contracts: regular and Neg-Risk.
    Multi-outcome events (Will-X-or-Y-or-Z, election outcomes, etc.) use
    Neg-Risk; binary YES/NO markets use regular. Submitting an order to
    the wrong contract → order_version_mismatch.

    Best signal: Gamma API's `negRisk` field per market."""
    if token_id in _neg_risk_cache:
        return _neg_risk_cache[token_id]
    import httpx
    try:
        r = httpx.get(
            "https://gamma-api.polymarket.com/markets",
            params={"clob_token_ids": token_id},
            timeout=10.0,
        )
        r.raise_for_status()
        markets = r.json() or []
        result = bool(markets[0].get("negRisk")) if markets else False
    except Exception as e:
        logger.warning(f"neg_risk lookup failed for {token_id[:12]}: {e}")
        result = False
    _neg_risk_cache[token_id] = result
    return result


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

        # Get the midpoint price for reporting
        try:
            midpoint = float(client.get_midpoint(req.token_id))
        except Exception:
            midpoint = 0

        # Determine which Exchange contract to sign for
        neg_risk = is_neg_risk(req.token_id)
        options = PartialCreateOrderOptions(neg_risk=neg_risk)

        order_args = MarketOrderArgs(
            token_id=req.token_id,
            amount=req.amount_usd,
            side=BUY,
        )
        signed_order = client.create_market_order(order_args, options)
        response = client.post_order(signed_order, OrderType.FOK)

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
            error = response.get("errorMsg") or response.get("error") or "Unknown"
            return {"success": False, "error": error, "price": midpoint, "neg_risk": neg_risk}

    except Exception as e:
        logger.error(f"Buy error: {e}")
        return {"success": False, "error": str(e)}


@app.post("/sell")
async def sell(req: SellRequest, authorization: str = Header(None)):
    verify_auth(authorization)
    client = get_client()

    try:
        from py_clob_client.clob_types import MarketOrderArgs, OrderType, PartialCreateOrderOptions
        from py_clob_client.order_builder.constants import SELL

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
