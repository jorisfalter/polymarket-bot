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


@app.post("/buy")
async def buy(req: BuyRequest, authorization: str = Header(None)):
    verify_auth(authorization)
    client = get_client()

    try:
        from py_clob_client.clob_types import MarketOrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY

        # Get the midpoint price for reporting
        try:
            midpoint = float(client.get_midpoint(req.token_id))
        except Exception:
            midpoint = 0

        # Use market order — handles complementary token matching correctly
        order_args = MarketOrderArgs(
            token_id=req.token_id,
            amount=req.amount_usd,
            side=BUY,
        )
        signed_order = client.create_market_order(order_args)
        response = client.post_order(signed_order, OrderType.FOK)

        if response and response.get("success"):
            order_id = response.get("orderID") or response.get("order_id")
            shares = req.amount_usd / midpoint if midpoint > 0 else 0
            return {
                "success": True,
                "order_id": order_id,
                "price": midpoint,
                "shares": shares,
            }
        else:
            error = response.get("errorMsg") or response.get("error") or "Unknown"
            return {"success": False, "error": error, "price": midpoint}

    except Exception as e:
        logger.error(f"Buy error: {e}")
        return {"success": False, "error": str(e)}


@app.post("/sell")
async def sell(req: SellRequest, authorization: str = Header(None)):
    verify_auth(authorization)
    client = get_client()

    try:
        from py_clob_client.clob_types import MarketOrderArgs, OrderType
        from py_clob_client.order_builder.constants import SELL

        # Get the midpoint price for reporting
        try:
            midpoint = float(client.get_midpoint(req.token_id))
        except Exception:
            midpoint = 0

        # Calculate USD value of the position
        amount_usd = req.shares * midpoint if midpoint > 0 else req.shares

        # Use market order for correct price execution
        order_args = MarketOrderArgs(
            token_id=req.token_id,
            amount=amount_usd,
            side=SELL,
        )
        signed_order = client.create_market_order(order_args)
        response = client.post_order(signed_order, OrderType.FOK)

        if response and response.get("success"):
            order_id = response.get("orderID") or response.get("order_id")
            return {
                "success": True,
                "order_id": order_id,
                "price": midpoint,
                "shares": req.shares,
            }
        else:
            error = response.get("errorMsg") or response.get("error") or "Unknown"
            return {"success": False, "error": error, "price": midpoint}

    except Exception as e:
        logger.error(f"Sell error: {e}")
        return {"success": False, "error": str(e)}


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
