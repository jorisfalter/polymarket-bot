"""
Reddit feed — primarily r/wallstreetbets, the canonical retail-flow leading
indicator. Pulls hot/new posts, extracts ticker mentions, and ranks tickers
by total upvotes/comments mentioning them.

Free public Reddit JSON API. Reddit asks for a real User-Agent identifying
the script + author. No auth required for read-only access.

Includes spike detection: previous buzz scores per ticker are persisted to
disk so we can detect when a ticker explodes (typical squeeze setup).
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
import httpx
from loguru import logger

WSB_STATE_PATH = Path(__file__).parent.parent / "data" / "wsb_buzz_state.json"

REDDIT_UA = "polymarket-bot/1.0 (research; joris@jorisfalter.com)"
REDDIT_BASE = "https://www.reddit.com"

# 10-min cache — WSB updates fast but we don't need real-time.
_cache: Dict[str, Dict] = {}
_cache_ttl = timedelta(minutes=10)

# Words that look like tickers but almost always aren't. Filtering these
# kills 90%+ of false positives in WSB titles.
TICKER_STOPWORDS: Set[str] = {
    "A", "AI", "AM", "AN", "ARE", "AS", "AT", "BE", "BY", "CEO", "CFO", "CTO",
    "DD", "DO", "DTC", "EOD", "EOM", "EOY", "EU", "FED", "FOMO", "FY", "GDP",
    "GO", "HOLD", "I", "IF", "II", "IIRC", "IMO", "IN", "INC", "IPO", "IRA",
    "IS", "IT", "ITM", "JPOW", "JUST", "LFG", "LLC", "LMAO", "LOL", "LP",
    "MM", "MY", "NEW", "NO", "NOT", "NOW", "OF", "ON", "OP", "OR", "OTC",
    "OTM", "PE", "PR", "Q", "Q1", "Q2", "Q3", "Q4", "QE", "QQQ", "RIP", "RH",
    "SEC", "SO", "SP", "SPY", "TA", "THE", "TIL", "TO", "TOO", "TS", "UP",
    "US", "USA", "USD", "VIX", "VS", "WAY", "WE", "WSB", "WTF", "YES", "YOLO",
    "ATH", "ATM", "API", "ASAP", "ATL", "BRB", "BTC", "BTW", "DM", "ETH",
    "EV", "EVS", "FBI", "FOMC", "GG", "GTFO", "HFT", "IMHO", "L", "M",
    "MOASS", "OG", "OS", "PA", "PT", "RIPPED", "TLDR", "TLDR;", "TY", "UK",
    "UR", "UV", "VC", "WW", "X", "Y", "Z",
    # Common WSB false positives
    "RATES", "RATE", "POS", "COVID", "EPS", "ROI", "TLDR", "EOD", "EOM",
    "PMI", "CPI", "GDP", "BLS", "DOJ", "DOD", "LMT", "POW", "JPOW", "FUD",
    "SHALL", "WORK", "JUSTICE", "TRUMP", "BIDEN", "NEWS", "SOLD", "BOUGHT",
    "BUY", "SELL", "PUT", "CALL", "CALLS", "PUTS", "LONG", "SHORT", "FOR",
    "FROM", "WITH", "WILL", "HAS", "WAS", "BUT", "ALL", "NOT", "MAY", "CAN",
    "DAY", "WEEK", "YEAR", "SUE", "CEO", "CFO", "RISK", "BIG", "TOP",
    "BAD", "GOOD", "OUT", "ANY", "GET", "ONE", "TWO", "TEN", "WAR", "WIN",
}

# These ARE tickers commonly mentioned but ambiguous. Whitelist: include
# them despite being short.
TICKER_WHITELIST: Set[str] = {"NVDA", "AMD", "TSM", "MSTR", "PLTR", "GME", "AMC"}


def _extract_tickers(text: str) -> List[str]:
    """Pull ticker symbols from text. Prefers $TICKER notation (high
    confidence) but also catches bare ALL-CAPS 2-5 char tokens after
    stopword filtering."""
    tickers: List[str] = []
    # $TICKER mentions — very high confidence
    for m in re.finditer(r"\$([A-Z]{1,5})\b", text):
        t = m.group(1)
        if t not in TICKER_STOPWORDS:
            tickers.append(t)
    # Bare ALL-CAPS tokens — lower confidence but still useful in WSB
    for m in re.finditer(r"\b([A-Z]{2,5})\b", text):
        t = m.group(1)
        if t in TICKER_WHITELIST:
            tickers.append(t)
            continue
        if t in TICKER_STOPWORDS:
            continue
        tickers.append(t)
    return tickers


async def fetch_subreddit_posts(subreddit: str = "wallstreetbets", sort: str = "hot",
                                  limit: int = 50) -> List[Dict]:
    """Pull hot/new/top posts from a subreddit's JSON endpoint.
    Reddit blocks Hetzner / data-center IPs. If TRADE_PROXY_URL is set we
    route through the Tokyo Fly.io proxy."""
    cache_key = f"{subreddit}:{sort}:{limit}"
    cached = _cache.get(cache_key)
    if cached and datetime.utcnow() - cached["timestamp"] < _cache_ttl:
        return cached["posts"]

    from .config import settings
    use_proxy = bool(settings.trade_proxy_url)
    if use_proxy:
        url = f"{settings.trade_proxy_url}/reddit/{subreddit}/{sort}"
        headers = {"Authorization": f"Bearer {settings.trade_proxy_secret}"}
    else:
        url = f"{REDDIT_BASE}/r/{subreddit}/{sort}.json"
        headers = {"User-Agent": REDDIT_UA}

    posts: List[Dict] = []
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            r = await client.get(url, params={"limit": limit})
            r.raise_for_status()
            data = r.json() or {}
        children = data.get("data", {}).get("children", []) or []
        for c in children:
            d = c.get("data", {}) or {}
            posts.append({
                "id": d.get("id"),
                "title": d.get("title", "") or "",
                "score": d.get("score", 0),
                "num_comments": d.get("num_comments", 0),
                "author": d.get("author", "?"),
                "flair": d.get("link_flair_text") or "",
                "created_utc": d.get("created_utc", 0),
                "url": f"{REDDIT_BASE}{d.get('permalink', '')}",
                "is_pinned": d.get("stickied", False),
                "selftext_preview": (d.get("selftext", "") or "")[:300],
            })
    except Exception as e:
        logger.warning(f"Reddit fetch failed for r/{subreddit}/{sort}: {e}")
        return cached["posts"] if cached else []

    _cache[cache_key] = {"timestamp": datetime.utcnow(), "posts": posts}
    return posts


async def get_wsb_pulse() -> Dict:
    """Combined WSB feed: hot posts + ranked ticker mentions across hot+new."""
    hot, new = await _gather_two("wallstreetbets")

    # Filter out daily/weekly mod-pinned threads from "hot"
    skip_flairs = {"Daily Discussion", "Weekend Discussion", "Earnings Thread"}
    real_hot = [p for p in hot if not p.get("is_pinned") and p.get("flair") not in skip_flairs][:20]

    # Ticker scan across hot+new combined
    ticker_score: Dict[str, int] = defaultdict(int)
    ticker_posts: Dict[str, List[Dict]] = defaultdict(list)
    for p in (hot + new):
        if p.get("is_pinned"):
            continue
        title = p["title"]
        flair = p.get("flair", "")
        # Skip noise threads
        if flair in skip_flairs:
            continue
        tickers = set(_extract_tickers(title + " " + (p.get("selftext_preview") or "")))
        for t in tickers:
            # Score = upvotes + comment count, weighted toward post score
            ticker_score[t] += p["score"] + p["num_comments"] // 2
            ticker_posts[t].append({
                "title": p["title"][:90],
                "url": p["url"],
                "score": p["score"],
            })

    ticker_ranking = [
        {
            "ticker": t,
            "buzz_score": s,
            "posts": ticker_posts[t][:3],
        }
        for t, s in sorted(ticker_score.items(), key=lambda x: -x[1])
        if s >= 100  # filter dust
    ][:20]

    return {
        "hot_posts": real_hot,
        "ticker_buzz": ticker_ranking,
    }


async def _gather_two(subreddit: str):
    import asyncio
    return await asyncio.gather(
        fetch_subreddit_posts(subreddit, "hot", 50),
        fetch_subreddit_posts(subreddit, "new", 50),
    )


def _load_wsb_state() -> Dict:
    if not WSB_STATE_PATH.exists():
        return {}
    try:
        return json.loads(WSB_STATE_PATH.read_text())
    except Exception:
        return {}


def _save_wsb_state(state: Dict):
    WSB_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    WSB_STATE_PATH.write_text(json.dumps(state, indent=2))


async def detect_buzz_spikes(
    spike_multiplier: float = 3.0,
    spike_min_buzz: int = 3000,
    new_min_buzz: int = 5000,
) -> List[Dict]:
    """Detect tickers whose buzz has spiked vs the last observation.

    A spike fires when:
    - The ticker was previously seen with buzz > 100 AND current buzz ≥ multiplier × prior, OR
    - The ticker is brand-new in the buzz list AND current buzz ≥ new_min_buzz.

    State is persisted to data/wsb_buzz_state.json so spikes only fire once per
    move — the next observation overwrites the baseline.
    """
    pulse = await get_wsb_pulse()
    current = {t["ticker"]: t["buzz_score"] for t in pulse.get("ticker_buzz", [])}
    state = _load_wsb_state()
    prior = state.get("buzz", {})

    spikes: List[Dict] = []
    for ticker, buzz in current.items():
        prev = prior.get(ticker, 0)
        if prev > 100 and buzz >= prev * spike_multiplier and buzz >= spike_min_buzz:
            spikes.append({
                "ticker": ticker,
                "buzz": buzz,
                "prior_buzz": prev,
                "multiple": round(buzz / prev, 1),
                "kind": "spike",
                "posts": [t["posts"] for t in pulse["ticker_buzz"] if t["ticker"] == ticker][0][:2],
            })
        elif prev == 0 and buzz >= new_min_buzz:
            spikes.append({
                "ticker": ticker,
                "buzz": buzz,
                "prior_buzz": 0,
                "multiple": None,
                "kind": "new",
                "posts": [t["posts"] for t in pulse["ticker_buzz"] if t["ticker"] == ticker][0][:2],
            })

    # Always update state to current (so we see fresh deltas next cycle)
    state["buzz"] = current
    state["last_check"] = datetime.utcnow().isoformat()
    _save_wsb_state(state)
    return spikes


async def cross_reference_watchlist(stock_watchlist: List[str]) -> List[Dict]:
    """Return WSB-buzz tickers that ALSO sit on the user's stock watchlist —
    the strongest combo signal we have."""
    if not stock_watchlist:
        return []
    watchlist_upper = {t.upper() for t in stock_watchlist}
    pulse = await get_wsb_pulse()
    overlaps = []
    for t in pulse.get("ticker_buzz", []):
        if t["ticker"] in watchlist_upper:
            overlaps.append(t)
    return overlaps
