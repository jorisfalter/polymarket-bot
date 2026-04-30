"""
Crypto data feeds — funding rates, perp/spot basis, cross-exchange spreads.
All from free public APIs (Binance, OKX, Bybit, Coinbase). No auth needed.

Drives the /btc dashboard. Manual execution by user; the bot does not auto-
trade crypto.
"""
import asyncio
from typing import Dict, List, Optional
import httpx
from loguru import logger

# Public endpoints — no auth required for any of these.
BINANCE_PERP_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
BINANCE_SPOT_URL = "https://api.binance.com/api/v3/ticker/24hr"
OKX_FUNDING_URL = "https://www.okx.com/api/v5/public/funding-rate"
OKX_TICKER_URL = "https://www.okx.com/api/v5/market/ticker"
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"
COINBASE_TICKER_URL = "https://api.exchange.coinbase.com/products/{pair}/ticker"
KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"

ASSETS = ["BTC", "ETH", "SOL"]


async def fetch_funding_rates() -> List[Dict]:
    """Fetch perp funding rates from Binance, OKX, Bybit. Annualized for
    comparability (raw rates are per 8h)."""
    results: List[Dict] = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Binance — single call returns all symbols
        try:
            r = await client.get(BINANCE_PERP_URL)
            r.raise_for_status()
            data = r.json() or []
            wanted = {f"{a}USDT" for a in ASSETS}
            for item in data:
                if item.get("symbol") in wanted:
                    rate = float(item.get("lastFundingRate", 0))
                    asset = item["symbol"].replace("USDT", "")
                    results.append({
                        "exchange": "Binance",
                        "asset": asset,
                        "symbol": item["symbol"],
                        "funding_rate": rate,
                        "annualized_pct": rate * 3 * 365 * 100,  # 3 fundings/day × 365
                        "mark_price": float(item.get("markPrice", 0)),
                        "index_price": float(item.get("indexPrice", 0)),
                    })
        except Exception as e:
            logger.warning(f"Binance funding fetch failed: {e}")

        # OKX — one call per asset
        for asset in ASSETS:
            try:
                r = await client.get(OKX_FUNDING_URL, params={"instId": f"{asset}-USDT-SWAP"})
                r.raise_for_status()
                items = (r.json() or {}).get("data") or []
                if items:
                    item = items[0]
                    rate = float(item.get("fundingRate", 0))
                    results.append({
                        "exchange": "OKX",
                        "asset": asset,
                        "symbol": item.get("instId"),
                        "funding_rate": rate,
                        "annualized_pct": rate * 3 * 365 * 100,
                    })
            except Exception as e:
                logger.warning(f"OKX funding fetch failed for {asset}: {e}")

        # Bybit — single call per category
        try:
            r = await client.get(BYBIT_TICKERS_URL, params={"category": "linear"})
            r.raise_for_status()
            data = (r.json() or {}).get("result", {}).get("list", []) or []
            wanted = {f"{a}USDT" for a in ASSETS}
            for item in data:
                if item.get("symbol") in wanted:
                    rate = float(item.get("fundingRate", 0))
                    asset = item["symbol"].replace("USDT", "")
                    results.append({
                        "exchange": "Bybit",
                        "asset": asset,
                        "symbol": item["symbol"],
                        "funding_rate": rate,
                        "annualized_pct": rate * 3 * 365 * 100,
                        "mark_price": float(item.get("markPrice", 0)),
                        "index_price": float(item.get("indexPrice", 0)),
                    })
        except Exception as e:
            logger.warning(f"Bybit funding fetch failed: {e}")

    return results


async def fetch_btc_basis() -> Dict:
    """Compare Binance perp mark price to spot price → annualized basis."""
    out = {"asset": "BTC", "spot": None, "perp": None, "basis_pct": None, "annualized_basis_pct": None}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            spot_r = await client.get(BINANCE_SPOT_URL, params={"symbol": "BTCUSDT"})
            spot_r.raise_for_status()
            out["spot"] = float(spot_r.json().get("lastPrice", 0))
        except Exception as e:
            logger.warning(f"BTC spot fetch failed: {e}")
        try:
            perp_r = await client.get(BINANCE_PERP_URL, params={"symbol": "BTCUSDT"})
            perp_r.raise_for_status()
            out["perp"] = float(perp_r.json().get("markPrice", 0))
        except Exception as e:
            logger.warning(f"BTC perp fetch failed: {e}")

    if out["spot"] and out["perp"] and out["spot"] > 0:
        diff_pct = (out["perp"] - out["spot"]) / out["spot"] * 100
        out["basis_pct"] = diff_pct
        # Funding settles every 8h, so annualize by 3*365 ≈ 1095 fundings
        # But basis itself is a snapshot — annualization is just descriptive.
    return out


async def fetch_exchange_spread() -> List[Dict]:
    """Compare BTC-USD (spot) across major exchanges to spot arb gaps."""
    quotes: List[Dict] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Binance
        try:
            r = await client.get(BINANCE_SPOT_URL, params={"symbol": "BTCUSDT"})
            r.raise_for_status()
            quotes.append({"exchange": "Binance", "pair": "BTCUSDT", "price": float(r.json().get("lastPrice", 0))})
        except Exception as e:
            logger.warning(f"Binance ticker fetch failed: {e}")

        # Coinbase
        try:
            r = await client.get(COINBASE_TICKER_URL.format(pair="BTC-USD"))
            r.raise_for_status()
            quotes.append({"exchange": "Coinbase", "pair": "BTC-USD", "price": float(r.json().get("price", 0))})
        except Exception as e:
            logger.warning(f"Coinbase ticker fetch failed: {e}")

        # Kraken (XBTUSD)
        try:
            r = await client.get(KRAKEN_TICKER_URL, params={"pair": "XBTUSD"})
            r.raise_for_status()
            data = (r.json() or {}).get("result") or {}
            for k, v in data.items():
                last = (v.get("c") or [None])[0]
                if last:
                    quotes.append({"exchange": "Kraken", "pair": k, "price": float(last)})
                    break
        except Exception as e:
            logger.warning(f"Kraken ticker fetch failed: {e}")

        # OKX
        try:
            r = await client.get(OKX_TICKER_URL, params={"instId": "BTC-USDT"})
            r.raise_for_status()
            items = (r.json() or {}).get("data") or []
            if items:
                quotes.append({"exchange": "OKX", "pair": "BTC-USDT", "price": float(items[0].get("last", 0))})
        except Exception as e:
            logger.warning(f"OKX ticker fetch failed: {e}")

    if quotes:
        prices = [q["price"] for q in quotes if q["price"] > 0]
        if prices:
            mid = sum(prices) / len(prices)
            for q in quotes:
                q["spread_pct"] = ((q["price"] - mid) / mid * 100) if mid else 0
    return quotes


async def fetch_all_crypto_signals() -> Dict:
    """Aggregate everything for the /btc dashboard in one round-trip."""
    funding, basis, spread = await asyncio.gather(
        fetch_funding_rates(),
        fetch_btc_basis(),
        fetch_exchange_spread(),
    )
    return {
        "funding_rates": funding,
        "btc_basis": basis,
        "exchange_spread": spread,
    }
