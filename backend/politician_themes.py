"""
Politician-trade theme clustering.

Standalone signal type that survives the STOCK Act 30-45d disclosure
lag: when N distinct politicians transact in the SAME theme within a
60-day window, that aggregate movement points at a sector rotation
even if any individual trade is stale by the time we see it.

Doesn't replace the per-trade Top Politicians table — that ranks who
has alpha. This ranks WHAT is being accumulated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Set

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
    """Return all themes a ticker belongs to (can be multiple)."""
    return TICKER_TO_THEMES.get((ticker or "").upper(), [])


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
