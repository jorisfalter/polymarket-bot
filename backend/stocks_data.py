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

# Quiver's public live endpoint is the most reliable free feed for STOCK Act
# disclosures. Returns recent congressional trades with ExcessReturn vs SPY
# already calculated.
QUIVER_CONGRESS_URL = "https://api.quiverquant.com/beta/live/congresstrading"

WATCHLIST_PATH = Path(__file__).parent.parent / "data" / "stocks_watchlist.json"

# 12h cache for politician trades — they update slowly and the data is heavy.
_pol_cache: Dict = {"timestamp": None, "trades": []}
_pol_cache_ttl = timedelta(hours=12)


async def fetch_politician_trades(days_back: int = 30) -> List[Dict]:
    """Fetch recent congressional disclosures from Quiver Quantitative's public
    live endpoint. Includes ExcessReturn vs SPY which lets us rank by who's
    actually outperforming."""
    now = datetime.utcnow()
    if (
        _pol_cache["timestamp"]
        and now - _pol_cache["timestamp"] < _pol_cache_ttl
        and _pol_cache["trades"]
    ):
        return _filter_recent(_pol_cache["trades"], days_back)

    trades: List[Dict] = []
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(QUIVER_CONGRESS_URL, headers=headers)
            r.raise_for_status()
            items = r.json() or []
            for it in items:
                trades.append(_normalize_quiver(it))
        trades.sort(key=lambda x: x.get("transaction_date", ""), reverse=True)
        _pol_cache["trades"] = trades
        _pol_cache["timestamp"] = now
        logger.info(f"Politician trades cached: {len(trades)} total")
    except Exception as e:
        logger.error(f"Politician trades fetch error: {e}")

    return _filter_recent(trades, days_back)


def _normalize_quiver(item: Dict) -> Dict:
    """Quiver's live shape → our common shape."""
    return {
        "chamber": item.get("House") or "?",
        "representative": item.get("Representative") or "?",
        "party": item.get("Party") or "",
        "ticker": (item.get("Ticker") or "").upper(),
        "asset": item.get("Description") or "",
        "type": (item.get("Transaction") or "").lower(),  # purchase / sale
        "amount": item.get("Range") or "",
        "amount_usd": float(item.get("Amount") or 0),
        "transaction_date": item.get("TransactionDate") or "",
        "disclosure_date": item.get("ReportDate") or "",
        "excess_return": item.get("ExcessReturn"),
        "price_change": item.get("PriceChange"),
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
    """Pull live price + short interest + key stats via yfinance (which handles
    Yahoo's auth quirks). yfinance is sync; we offload to a thread."""
    if not ticker:
        return None
    ticker = ticker.upper()
    try:
        import asyncio
        info = await asyncio.to_thread(_yf_info, ticker)
        if not info:
            return None
        return {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName") or "",
            "price": info.get("regularMarketPrice") or info.get("currentPrice"),
            "change_pct": info.get("regularMarketChangePercent"),
            "market_cap": info.get("marketCap"),
            "volume": info.get("regularMarketVolume") or info.get("volume"),
            "short_interest_pct_float": info.get("shortPercentOfFloat"),
            "shares_short": info.get("sharesShort"),
            "shares_short_prior": info.get("sharesShortPriorMonth"),
            "short_ratio_days_to_cover": info.get("shortRatio"),
            "float_shares": info.get("floatShares"),
            "held_pct_insiders": info.get("heldPercentInsiders"),
            "held_pct_institutions": info.get("heldPercentInstitutions"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    except Exception as e:
        logger.warning(f"yfinance fetch failed for {ticker}: {e}")
        return None


def _yf_info(ticker: str) -> Optional[Dict]:
    """Sync yfinance call. Runs in a thread."""
    try:
        import yfinance as yf
        return yf.Ticker(ticker).info or {}
    except Exception as e:
        logger.debug(f"yfinance error for {ticker}: {e}")
        return None


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


async def top_politicians_by_alpha(min_trades: int = 5) -> List[Dict]:
    """Aggregate the politician trade feed by representative and rank by mean
    excess return. The Pelosi-tracker move: who's actually outperforming?"""
    trades = await fetch_politician_trades(days_back=180)
    by_rep: Dict[str, Dict] = {}
    for t in trades:
        rep = t.get("representative", "?")
        if rep == "?":
            continue
        d = by_rep.setdefault(rep, {
            "representative": rep,
            "party": t.get("party") or "",
            "chamber": t.get("chamber") or "",
            "trades": 0,
            "purchases": 0,
            "sales": 0,
            "excess_returns": [],
            "total_volume_min": 0,
        })
        d["trades"] += 1
        if t.get("type") == "purchase":
            d["purchases"] += 1
        elif t.get("type") == "sale":
            d["sales"] += 1
        if t.get("excess_return") is not None:
            try:
                d["excess_returns"].append(float(t["excess_return"]))
            except Exception:
                pass
        d["total_volume_min"] += t.get("amount_usd") or 0

    out = []
    for d in by_rep.values():
        if d["trades"] < min_trades:
            continue
        ers = d.pop("excess_returns")
        d["avg_excess_return"] = sum(ers) / len(ers) if ers else 0
        d["beats_spy_count"] = sum(1 for r in ers if r > 0)
        d["beats_spy_pct"] = (d["beats_spy_count"] / len(ers)) if ers else 0
        out.append(d)
    out.sort(key=lambda x: x["avg_excess_return"], reverse=True)
    return out


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
