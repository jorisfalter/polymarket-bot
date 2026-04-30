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

# Quiver's public live endpoint flipped to auth-required in 2026, so we now
# use Finnhub which has a free tier (60 calls/min) for congressional trading.
# Set FINNHUB_API_KEY in .env to enable.
QUIVER_CONGRESS_URL = "https://api.quiverquant.com/beta/live/congresstrading"
FINNHUB_BASE = "https://finnhub.io/api/v1"

WATCHLIST_PATH = Path(__file__).parent.parent / "data" / "stocks_watchlist.json"
POLITICIAN_WATCHLIST_PATH = Path(__file__).parent.parent / "data" / "politicians_watchlist.json"
POLITICIAN_SEEN_PATH = Path(__file__).parent.parent / "data" / "politicians_seen.json"
POLITICIAN_CACHE_PATH = Path(__file__).parent.parent / "data" / "politician_trades_cache.json"

# 12h cache for politician trades — they update slowly and the data is heavy.
_pol_cache: Dict = {"timestamp": None, "trades": []}
_pol_cache_ttl = timedelta(hours=12)


def _load_disk_cache() -> Optional[Dict]:
    """Load the disk-persisted cache. Politician disclosures move slowly
    (30-45 day filing window), so a 1-7 day stale snapshot is still useful."""
    if not POLITICIAN_CACHE_PATH.exists():
        return None
    try:
        return json.loads(POLITICIAN_CACHE_PATH.read_text())
    except Exception:
        return None


def _save_disk_cache(trades: List[Dict]):
    POLITICIAN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLITICIAN_CACHE_PATH.write_text(json.dumps({
        "fetched_at": datetime.utcnow().isoformat(),
        "trades": trades,
    }, indent=2))


def get_politician_cache_age_hours() -> Optional[float]:
    """Return how stale the disk cache is, for UI display."""
    disk = _load_disk_cache()
    if not disk:
        return None
    try:
        fetched = datetime.fromisoformat(disk["fetched_at"])
        return (datetime.utcnow() - fetched).total_seconds() / 3600
    except Exception:
        return None


async def fetch_politician_trades(days_back: int = 30) -> List[Dict]:
    """Fetch congressional disclosures. Source priority:
    1. Quiver paid (QUIVER_API_KEY) — best
    2. Finnhub paid (FINNHUB_API_KEY for /stock/congressional-trading)
    3. Quiver public (rare; gated since 2026)
    4. Disk-persisted snapshot (stale but useful — disclosures move slowly)
    """
    from .config import settings
    now = datetime.utcnow()

    # In-memory cache hit (fresh)
    if (
        _pol_cache["timestamp"]
        and now - _pol_cache["timestamp"] < _pol_cache_ttl
        and _pol_cache["trades"]
    ):
        return _filter_recent(_pol_cache["trades"], days_back)

    trades: List[Dict] = []

    if settings.quiver_api_key:
        trades = await _fetch_quiver_authed(settings.quiver_api_key, days_back=days_back)
    if not trades and settings.finnhub_api_key:
        trades = await _fetch_finnhub_congress(settings.finnhub_api_key, days_back=180)
    if not trades:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(QUIVER_CONGRESS_URL, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200:
                    items = r.json() or []
                    if isinstance(items, list):
                        for it in items:
                            trades.append(_normalize_quiver(it))
        except Exception as e:
            logger.debug(f"Quiver public fallback failed (expected): {e}")

    if trades:
        trades.sort(key=lambda x: x.get("transaction_date", ""), reverse=True)
        _pol_cache["trades"] = trades
        _pol_cache["timestamp"] = now
        _save_disk_cache(trades)
        logger.info(f"Politician trades fetched + persisted: {len(trades)}")
        return _filter_recent(trades, days_back)

    # All live sources failed → use disk snapshot if available
    disk = _load_disk_cache()
    if disk and disk.get("trades"):
        cached = disk["trades"]
        try:
            fetched = datetime.fromisoformat(disk["fetched_at"])
            age_hours = (now - fetched).total_seconds() / 3600
        except Exception:
            age_hours = -1
        # Hydrate in-memory so subsequent calls in this process don't re-try
        _pol_cache["trades"] = cached
        _pol_cache["timestamp"] = now  # treat as fresh-enough this run
        logger.warning(f"Live sources failed — serving disk snapshot ({len(cached)} trades, {age_hours:.1f}h old)")
        return _filter_recent(cached, days_back)

    logger.info("Politician trades cached: 0 total (no live + no disk)")
    return []


async def _fetch_quiver_authed(api_key: str, days_back: int = 180) -> List[Dict]:
    """Quiver Quantitative authenticated feed. Their /beta/live/congresstrading
    works with a Bearer token even on the cheapest plan. Returns ExcessReturn
    pre-calculated which is the killer feature."""
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    out: List[Dict] = []
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            r = await client.get(QUIVER_CONGRESS_URL)
            r.raise_for_status()
            items = r.json() or []
        for it in items:
            out.append(_normalize_quiver(it))
    except Exception as e:
        logger.warning(f"Quiver authed fetch failed: {e}")
    return out


async def _fetch_finnhub_congress(api_key: str, days_back: int = 180) -> List[Dict]:
    """Fetch from Finnhub. Their endpoint is per-symbol — but they also have an
    overall feed under stock/congressional-trading?from=...&to=...&symbol=
    Without symbol it returns recent across all members. Free tier handles this."""
    from_dt = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_dt = datetime.utcnow().strftime("%Y-%m-%d")
    out: List[Dict] = []
    headers = {"X-Finnhub-Token": api_key}
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            r = await client.get(
                f"{FINNHUB_BASE}/stock/congressional-trading",
                params={"from": from_dt, "to": to_dt},
            )
            r.raise_for_status()
            data = r.json() or {}
        items = data.get("data") or []
        for it in items:
            out.append(_normalize_finnhub(it))
    except Exception as e:
        logger.warning(f"Finnhub congress fetch failed: {e}")
    return out


def _normalize_finnhub(item: Dict) -> Dict:
    """Finnhub shape → common shape."""
    raw_type = (item.get("transactionType") or "").lower()
    type_norm = "purchase" if "purchase" in raw_type else "sale" if "sale" in raw_type else raw_type
    return {
        "chamber": "?",  # Finnhub doesn't always include chamber
        "representative": item.get("name") or "?",
        "party": "",
        "ticker": (item.get("symbol") or "").upper(),
        "asset": item.get("assetName") or "",
        "type": type_norm,
        "amount": item.get("ownerType") or "",
        "amount_usd": float(item.get("amountFrom") or 0),
        "amount_to_usd": float(item.get("amountTo") or 0),
        "transaction_date": item.get("transactionDate") or "",
        "disclosure_date": item.get("filingDate") or "",
        "excess_return": None,
        "price_change": None,
    }


def _normalize_quiver(item: Dict) -> Dict:
    """Quiver's live shape → our common shape (kept for fallback)."""
    return {
        "chamber": item.get("House") or "?",
        "representative": item.get("Representative") or "?",
        "party": item.get("Party") or "",
        "ticker": (item.get("Ticker") or "").upper(),
        "asset": item.get("Description") or "",
        "type": (item.get("Transaction") or "").lower(),
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


async def top_politicians_by_alpha(min_trades: int = 2) -> List[Dict]:
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

    watched = set(n.lower().strip() for n in get_politician_watchlist())
    out = []
    for d in by_rep.values():
        if d["trades"] < min_trades:
            continue
        ers = d.pop("excess_returns")
        d["avg_excess_return"] = sum(ers) / len(ers) if ers else 0
        d["beats_spy_count"] = sum(1 for r in ers if r > 0)
        d["beats_spy_pct"] = (d["beats_spy_count"] / len(ers)) if ers else 0
        d["reliability"] = reliability_tier(d["trades"], d["beats_spy_pct"])
        d["watched"] = d["representative"].lower().strip() in watched
        out.append(d)
    out.sort(key=lambda x: (x["watched"], x["avg_excess_return"]), reverse=True)
    return out


def get_politician_watchlist() -> List[str]:
    if not POLITICIAN_WATCHLIST_PATH.exists():
        return []
    try:
        return json.loads(POLITICIAN_WATCHLIST_PATH.read_text()).get("politicians", [])
    except Exception:
        return []


def set_politician_watchlist(names: List[str]):
    POLITICIAN_WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    deduped = []
    for n in names:
        n = (n or "").strip()
        if n and n not in deduped:
            deduped.append(n)
    POLITICIAN_WATCHLIST_PATH.write_text(json.dumps({"politicians": deduped}, indent=2))


def reliability_tier(trades: int, beats_spy_pct: float) -> str:
    """Classify a politician's track-record reliability based on sample size.
    The dashboard surfaces this so users don't chase 2-trade outliers."""
    if trades >= 20 and beats_spy_pct >= 0.55:
        return "high"
    if trades >= 10:
        return "moderate"
    if trades >= 5:
        return "weak"
    return "noise"


async def detect_new_politician_trades() -> List[Dict]:
    """Compare current politician trades against last-seen state.
    Returns NEW disclosures from watched politicians since last check."""
    watchlist = get_politician_watchlist()
    if not watchlist:
        return []

    # Load last-seen state — keyed by representative name → set of "ticker:date" strings
    seen: Dict[str, set] = {}
    if POLITICIAN_SEEN_PATH.exists():
        try:
            raw = json.loads(POLITICIAN_SEEN_PATH.read_text())
            seen = {k: set(v) for k, v in raw.items()}
        except Exception:
            pass

    trades = await fetch_politician_trades(days_back=30)
    new_trades: List[Dict] = []
    watch_lower = {w.lower().strip() for w in watchlist}

    for t in trades:
        rep = t.get("representative", "")
        if not rep or rep.lower().strip() not in watch_lower:
            continue
        key = f"{t.get('ticker','')}:{t.get('transaction_date','')}:{t.get('type','')}"
        seen_set = seen.setdefault(rep, set())
        if key in seen_set:
            continue
        new_trades.append(t)
        seen_set.add(key)

    # Persist updated state
    POLITICIAN_SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLITICIAN_SEEN_PATH.write_text(
        json.dumps({k: list(v) for k, v in seen.items()}, indent=2)
    )
    return new_trades


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
