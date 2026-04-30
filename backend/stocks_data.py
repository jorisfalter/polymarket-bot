"""
Stocks data feeds — politician trades (House + Senate disclosures) + short
interest scraping from Yahoo. Free public sources, no API keys required.

Drives the /stocks dashboard. The bot doesn't trade stocks directly (yet) —
this is signal-surface only, manual execution by the user.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import httpx
from loguru import logger

# House + Senate Stock Watcher publish raw disclosures to public S3 buckets.
# These are reliable mirrors of the STOCK Act periodic transaction reports.
HOUSE_TRADES_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_TRADES_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"

# Yahoo's unofficial quote summary endpoint. Returns short interest + key stats.
YAHOO_QUOTE_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"

WATCHLIST_PATH = Path(__file__).parent.parent / "data" / "stocks_watchlist.json"

# 12h cache for politician trades — they update slowly and the data is heavy.
_pol_cache: Dict = {"timestamp": None, "trades": []}
_pol_cache_ttl = timedelta(hours=12)


async def fetch_politician_trades(days_back: int = 30) -> List[Dict]:
    """Fetch House + Senate disclosed trades from the last N days."""
    now = datetime.utcnow()
    if (
        _pol_cache["timestamp"]
        and now - _pol_cache["timestamp"] < _pol_cache_ttl
        and _pol_cache["trades"]
    ):
        return _filter_recent(_pol_cache["trades"], days_back)

    trades: List[Dict] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for url, chamber in [(HOUSE_TRADES_URL, "House"), (SENATE_TRADES_URL, "Senate")]:
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                    items = r.json() or []
                    for it in items:
                        trades.append(_normalize_trade(it, chamber))
                except Exception as e:
                    logger.warning(f"Politician trades fetch failed for {chamber}: {e}")
        # Sort by transaction_date desc
        trades.sort(key=lambda x: x.get("transaction_date", ""), reverse=True)
        _pol_cache["trades"] = trades
        _pol_cache["timestamp"] = now
        logger.info(f"Politician trades cached: {len(trades)} total")
    except Exception as e:
        logger.error(f"Politician trades fetch error: {e}")

    return _filter_recent(trades, days_back)


def _normalize_trade(item: Dict, chamber: str) -> Dict:
    """Normalize House/Senate disclosure formats to a common shape."""
    return {
        "chamber": chamber,
        "representative": item.get("representative") or item.get("senator") or "?",
        "ticker": (item.get("ticker") or "").upper(),
        "asset": item.get("asset_description") or item.get("asset_type") or "",
        "type": item.get("type") or item.get("transaction_type") or "?",  # purchase / sale / exchange
        "amount": item.get("amount") or item.get("tx_amount") or "",  # range like "$1,001 - $15,000"
        "transaction_date": item.get("transaction_date") or "",
        "disclosure_date": item.get("disclosure_date") or "",
        "ptr_link": item.get("ptr_link") or "",
    }


def _filter_recent(trades: List[Dict], days_back: int) -> List[Dict]:
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    out = []
    for t in trades:
        d = t.get("transaction_date") or ""
        if d and d >= cutoff:
            out.append(t)
    return out


async def fetch_ticker_stats(ticker: str) -> Optional[Dict]:
    """Pull live price + short interest + key stats for a ticker via Yahoo."""
    if not ticker:
        return None
    ticker = ticker.upper()
    url = YAHOO_QUOTE_URL.format(ticker=ticker)
    params = {"modules": "defaultKeyStatistics,price,summaryDetail,financialData"}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; polymarket-bot/1.0)"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
        result = data.get("quoteSummary", {}).get("result") or []
        if not result:
            return None
        d = result[0]
        ks = d.get("defaultKeyStatistics", {}) or {}
        price = d.get("price", {}) or {}
        summ = d.get("summaryDetail", {}) or {}
        fin = d.get("financialData", {}) or {}
        return {
            "ticker": ticker,
            "name": price.get("shortName") or price.get("longName") or "",
            "price": _raw(price.get("regularMarketPrice")),
            "change_pct": _raw(price.get("regularMarketChangePercent")),
            "market_cap": _raw(price.get("marketCap")),
            "volume": _raw(price.get("regularMarketVolume")),
            "short_interest_pct_float": _raw(ks.get("shortPercentOfFloat")),
            "shares_short": _raw(ks.get("sharesShort")),
            "shares_short_prior": _raw(ks.get("sharesShortPriorMonth")),
            "short_ratio_days_to_cover": _raw(ks.get("shortRatio")),
            "float_shares": _raw(ks.get("floatShares")),
            "held_pct_insiders": _raw(ks.get("heldPercentInsiders")),
            "held_pct_institutions": _raw(ks.get("heldPercentInstitutions")),
            "fifty_two_week_high": _raw(summ.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _raw(summ.get("fiftyTwoWeekLow")),
            "recommendation": fin.get("recommendationKey") or "",
        }
    except Exception as e:
        logger.warning(f"Yahoo fetch failed for {ticker}: {e}")
        return None


def _raw(v):
    """Yahoo wraps numbers in {raw, fmt}. Pull the raw value."""
    if isinstance(v, dict):
        return v.get("raw")
    return v


def get_watchlist() -> List[str]:
    if not WATCHLIST_PATH.exists():
        return []
    try:
        data = json.loads(WATCHLIST_PATH.read_text())
        return data.get("tickers", [])
    except Exception:
        return []


def set_watchlist(tickers: List[str]):
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen = []
    for t in tickers:
        t = (t or "").upper().strip()
        if t and t not in seen:
            seen.append(t)
    WATCHLIST_PATH.write_text(json.dumps({"tickers": seen}, indent=2))


async def fetch_squeeze_setups(min_short_pct: float = 0.20) -> List[Dict]:
    """Cross-reference watchlist tickers with short interest + recent politician
    activity. Returns enriched dicts with squeeze signals."""
    tickers = get_watchlist()
    if not tickers:
        return []
    pol_trades = await fetch_politician_trades(days_back=30)
    pol_by_ticker: Dict[str, List[Dict]] = {}
    for t in pol_trades:
        tk = t.get("ticker", "")
        if tk:
            pol_by_ticker.setdefault(tk, []).append(t)

    setups = []
    for ticker in tickers:
        stats = await fetch_ticker_stats(ticker)
        if not stats:
            continue
        si = stats.get("short_interest_pct_float") or 0
        recent_pol = pol_by_ticker.get(ticker, [])
        # Score: weight SI high. Politician buying adds bonus.
        score = 0
        if si and si >= min_short_pct:
            score += int(si * 100)
        if recent_pol:
            score += min(20, len(recent_pol) * 5)
        stats["politician_trades_30d"] = len(recent_pol)
        stats["politician_recent"] = recent_pol[:3]
        stats["squeeze_score"] = score
        setups.append(stats)

    setups.sort(key=lambda x: x.get("squeeze_score", 0), reverse=True)
    return setups
