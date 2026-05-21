"""
Politician-trade theme clustering.

Standalone signal type that survives the STOCK Act 30-45d disclosure
lag: when N distinct politicians transact in the SAME theme within a
60-day window, that aggregate movement points at a sector rotation
even if any individual trade is stale by the time we see it.

Doesn't replace the per-trade Top Politicians table — that ranks who
has alpha. This ranks WHAT is being accumulated.

Two-tier classification:
  1. Hardcoded THEMES dict (curated, narrow — "ai-semis", "nuclear-uranium")
  2. yfinance fallback for unmapped tickers — derives a broader theme
     from sector + industry, cached on disk (1 week TTL).
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

from loguru import logger

# ──────────────────────────────────────────────────────────────────────
# Theme map — ticker → list of themes. One ticker can belong to multiple
# (e.g. PLTR is AI software AND defense). Curated, not GICS — GICS lumps
# unrelated names together while we care about narrower edges.
# ──────────────────────────────────────────────────────────────────────

THEMES: Dict[str, List[str]] = {
    # AI / semis (the "picks-and-shovels" 2nd-derivative trade)
    "ai-semis": [
        "NVDA", "AMD", "AVGO", "MU", "TSM", "ARM", "ASML", "MRVL", "ON",
        "ADI", "QCOM", "LRCX", "AMAT", "KLAC", "MCHP", "INTC", "ALAB",
        "SMCI", "MPWR", "ENTG", "MKSI", "ONTO", "TER", "COHR",
    ],
    "ai-software": [
        "PLTR", "AI", "SNOW", "CRM", "NOW", "DDOG", "MDB", "ANET",
        "MSFT", "GOOGL", "GOOG", "META", "ORCL", "ADBE", "INTU",
    ],
    # Energy / power for AI infra
    "nuclear-uranium": [
        "SMR", "OKLO", "CCJ", "NRG", "VST", "ETR", "BWXT", "URA", "URNM",
        "LEU", "UEC", "CEG", "TLN", "PEG",
    ],
    "oil-gas": [
        "XOM", "CVX", "COP", "OXY", "EOG", "PSX", "MPC", "VLO", "SLB",
        "HAL", "BKR", "DVN", "FANG", "WMB",
    ],
    # Crypto exposure via equities (no direct crypto in politician filings)
    "crypto-adjacent": [
        "COIN", "MSTR", "RIOT", "MARA", "CIFR", "WULF", "IREN", "HUT",
        "CLSK", "BITF", "HOOD", "BLOK",
    ],
    # Defense / aerospace (war/conflict beneficiaries)
    "defense": [
        "RTX", "LMT", "NOC", "GD", "BA", "RKLB", "AVAV", "LDOS", "PLTR",
        "TXT", "HII", "LHX", "KTOS", "BWXT", "MRCY",
    ],
    # Pharma / biotech
    "pharma": [
        "PFE", "MRK", "LLY", "BIIB", "REGN", "AMGN", "GILD", "BMY", "NVO",
        "ABBV", "JNJ", "VRTX", "BMRN", "MRNA", "INCY", "NBIX",
    ],
    # GLP-1 / obesity (subset of pharma but a distinct trade)
    "glp1": ["LLY", "NVO", "AMGN", "ZLDPF"],
    # Big tech (mega-cap)
    "mega-tech": [
        "AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "NFLX", "TSLA",
    ],
    # Banking / financials
    "banks": [
        "JPM", "BAC", "GS", "MS", "C", "WFC", "BLK", "SCHW", "AXP",
        "USB", "PNC", "TFC", "COF",
    ],
    # EV / auto (separate from mega-tech TSLA bucket)
    "ev-auto": ["TSLA", "RIVN", "LCID", "F", "GM", "STLA", "TM"],
    # China exposure
    "china": ["BABA", "JD", "PDD", "BIDU", "NIO", "LI", "XPEV", "TCEHY"],
    # Real estate / REITs (rate-sensitive)
    "reits": [
        "PLD", "AMT", "EQIX", "DLR", "SPG", "O", "CCI", "PSA", "WELL",
        "ARE", "VLO",
    ],
    # Consumer discretionary "everyone shops there"
    "consumer-discretionary": [
        "AMZN", "HD", "NKE", "MCD", "SBUX", "LOW", "TJX", "BKNG", "ORLY",
        "AZO", "DPZ",
    ],
}

# Inverse map: ticker → list of themes it belongs to
TICKER_TO_THEMES: Dict[str, List[str]] = defaultdict(list)
for theme, tickers in THEMES.items():
    for tk in tickers:
        TICKER_TO_THEMES[tk.upper()].append(theme)
TICKER_TO_THEMES = dict(TICKER_TO_THEMES)


def themes_for_ticker(ticker: str) -> List[str]:
    """Return all themes a ticker belongs to (can be multiple).
    Reads from hardcoded map first, then the yfinance-derived dynamic cache.
    Returns [] for tickers we've never classified — call enrich_dynamic_themes()
    first to populate."""
    tk = (ticker or "").upper()
    static = TICKER_TO_THEMES.get(tk, [])
    if static:
        return static
    return _dynamic_map.get(tk, [])


# ──────────────────────────────────────────────────────────────────────
# Dynamic classification via yfinance — for tickers not in the static map
# ──────────────────────────────────────────────────────────────────────

_DYNAMIC_CACHE_PATH = Path(__file__).parent.parent / "data" / "ticker_themes_cache.json"
_DYNAMIC_TTL_DAYS = 14  # sector/industry don't change weekly
_dynamic_map: Dict[str, List[str]] = {}
_dynamic_meta: Dict[str, str] = {}  # ticker -> ISO date last refreshed


def _load_dynamic_cache() -> None:
    if not _DYNAMIC_CACHE_PATH.exists():
        return
    try:
        data = json.loads(_DYNAMIC_CACHE_PATH.read_text())
        for tk, entry in data.items():
            if isinstance(entry, dict):
                _dynamic_map[tk] = entry.get("themes") or []
                _dynamic_meta[tk] = entry.get("refreshed_at", "")
            elif isinstance(entry, list):  # legacy shape
                _dynamic_map[tk] = entry
                _dynamic_meta[tk] = ""
    except Exception as e:
        logger.debug(f"dynamic theme cache load failed: {e}")


def _save_dynamic_cache() -> None:
    _DYNAMIC_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {tk: {"themes": _dynamic_map[tk], "refreshed_at": _dynamic_meta.get(tk, "")}
               for tk in _dynamic_map}
    try:
        _DYNAMIC_CACHE_PATH.write_text(json.dumps(payload, indent=1))
    except Exception as e:
        logger.debug(f"dynamic theme cache save failed: {e}")


# Map yfinance sector → our theme buckets. Used when industry doesn't match
# any of the narrower INDUSTRY_KEYWORDS below.
_SECTOR_TO_THEMES = {
    "Technology": ["mega-tech"],
    "Financial Services": ["banks"],
    "Healthcare": ["pharma"],
    "Consumer Cyclical": ["consumer-discretionary"],
    "Consumer Defensive": ["consumer-staples"],
    "Industrials": ["industrials"],
    "Energy": ["oil-gas"],
    "Communication Services": ["telecom"],
    "Utilities": ["utilities"],
    "Basic Materials": ["materials"],
    "Real Estate": ["reits"],
}

# Industry-name substrings → specific themes. These override the sector
# default (a Technology stock with industry "Semiconductors" goes to
# ai-semis, not the generic mega-tech).
_INDUSTRY_KEYWORDS = {
    "ai-semis": ["semiconductor"],
    "ai-software": ["software—application", "software-application",
                     "software—infrastructure", "software-infrastructure"],
    "nuclear-uranium": ["uranium", "nuclear"],
    "defense": ["aerospace & defense", "aerospace and defense", "defense"],
    "ev-auto": ["auto manufacturers"],
    "crypto-adjacent": ["crypto", "blockchain"],
    "banks": ["bank—diversified", "banks—diversified", "banks—regional"],
    "oil-gas": ["oil & gas", "oil and gas"],
    "pharma": ["drug manufacturers", "biotechnology"],
    "reits": ["reit"],
    "ai-software": ["information technology services"],  # broad coverage
}


def _classify_from_yfinance(sector: str, industry: str) -> List[str]:
    """Map yfinance sector + industry to our internal themes."""
    out: List[str] = []
    i = (industry or "").lower()
    if i:
        for theme, keywords in _INDUSTRY_KEYWORDS.items():
            if any(k in i for k in keywords) and theme not in out:
                out.append(theme)
    if not out and sector in _SECTOR_TO_THEMES:
        out = list(_SECTOR_TO_THEMES[sector])
    return out


def _fetch_yfinance_classification_sync(ticker: str) -> List[str]:
    """Blocking yfinance call — wrap with asyncio.to_thread."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        sector = info.get("sector") or ""
        industry = info.get("industry") or ""
        themes = _classify_from_yfinance(sector, industry)
        logger.debug(f"yfinance theme: {ticker} sector={sector!r} industry={industry!r} → {themes}")
        return themes
    except Exception as e:
        logger.debug(f"yfinance theme classify failed for {ticker}: {e}")
        return []


async def enrich_dynamic_themes(tickers: List[str], concurrency: int = 4) -> int:
    """For every ticker not in the hardcoded map and not in a fresh dynamic
    cache entry, fetch yfinance and classify. Updates the on-disk cache.
    Returns count of tickers newly classified this call.
    """
    if not _dynamic_map and _DYNAMIC_CACHE_PATH.exists():
        _load_dynamic_cache()

    now = datetime.utcnow()
    cutoff = (now - timedelta(days=_DYNAMIC_TTL_DAYS)).isoformat()
    todo: List[str] = []
    seen: Set[str] = set()
    for raw in tickers:
        tk = (raw or "").strip().upper()
        if not tk or tk in seen or tk in TICKER_TO_THEMES:
            continue
        seen.add(tk)
        # Skip if cached recently
        last = _dynamic_meta.get(tk, "")
        if last and last >= cutoff:
            continue
        todo.append(tk)

    if not todo:
        return 0

    sem = asyncio.Semaphore(concurrency)
    async def _one(tk: str) -> None:
        async with sem:
            themes = await asyncio.to_thread(_fetch_yfinance_classification_sync, tk)
        _dynamic_map[tk] = themes
        _dynamic_meta[tk] = now.isoformat()

    await asyncio.gather(*(_one(tk) for tk in todo))
    _save_dynamic_cache()
    logger.info(f"theme cache: classified {len(todo)} new tickers via yfinance")
    return len(todo)


# Auto-load cache on module import so the first call is fast
_load_dynamic_cache()


# ──────────────────────────────────────────────────────────────────────
# Cluster detection
# ──────────────────────────────────────────────────────────────────────

def detect_theme_clusters(
    trades: List[Dict],
    window_days: int = 60,
    min_politicians: int = 3,
) -> List[Dict]:
    """For trades within `window_days`, group by theme and identify
    clusters where ≥`min_politicians` distinct politicians transacted.

    Each cluster reports:
      - theme, distinct politicians, sample tickers
      - net_direction: 'accumulating' if purchases > 1.5× sales,
        'distributing' if sales > 1.5× purchases, else 'mixed'
      - total volume (sum of amount_usd where known)
      - sample trades (newest 3) for context

    A ticker counted in multiple themes contributes to each — that's
    by design (PLTR buying = both AI-software and defense signal).
    """
    if not trades:
        return []
    cutoff = (datetime.utcnow() - timedelta(days=window_days)).strftime("%Y-%m-%d")

    # theme -> {pols set, tickers set, purchase_count, sale_count, volume, sample_trades}
    by_theme: Dict[str, Dict] = defaultdict(lambda: {
        "politicians": set(),
        "tickers": set(),
        "purchase_count": 0,
        "sale_count": 0,
        "volume_usd": 0.0,
        "sample_trades": [],
    })

    for t in trades:
        tx_date = t.get("transaction_date") or ""
        if not tx_date or tx_date < cutoff:
            continue
        ticker = (t.get("ticker") or "").upper()
        themes = themes_for_ticker(ticker)
        if not themes:
            continue
        rep = t.get("representative") or "?"
        type_norm = (t.get("type") or "").lower()
        amt = float(t.get("amount_usd") or 0)

        for theme in themes:
            b = by_theme[theme]
            b["politicians"].add(rep)
            b["tickers"].add(ticker)
            if type_norm == "purchase":
                b["purchase_count"] += 1
            elif type_norm == "sale":
                b["sale_count"] += 1
            b["volume_usd"] += amt
            if len(b["sample_trades"]) < 3:
                b["sample_trades"].append({
                    "date": tx_date,
                    "rep": rep,
                    "ticker": ticker,
                    "type": type_norm,
                    "amount": t.get("amount") or "",
                })

    out: List[Dict] = []
    for theme, b in by_theme.items():
        n_pols = len(b["politicians"])
        if n_pols < min_politicians:
            continue
        purchases = b["purchase_count"]
        sales = b["sale_count"]
        if purchases > sales * 1.5:
            direction = "accumulating"
        elif sales > purchases * 1.5:
            direction = "distributing"
        else:
            direction = "mixed"
        # Conviction score: more politicians + more skewed direction = higher
        skew = abs(purchases - sales) / max(purchases + sales, 1)
        score = n_pols * (1 + skew)
        out.append({
            "theme": theme,
            "politicians_count": n_pols,
            "politicians": sorted(b["politicians"]),
            "tickers": sorted(b["tickers"]),
            "purchase_count": purchases,
            "sale_count": sales,
            "net_direction": direction,
            "volume_usd": round(b["volume_usd"], 2),
            "conviction_score": round(score, 2),
            "sample_trades": sorted(
                b["sample_trades"], key=lambda x: x["date"], reverse=True
            )[:3],
            "window_days": window_days,
        })
    out.sort(key=lambda x: x["conviction_score"], reverse=True)
    return out
