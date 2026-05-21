"""
Paper-trader for the research pipeline.

When an idea reaches stage='implement', we auto-open a paper position at
the current real-world price. A daily tick fetches updated prices and
closes positions per hardcoded rules (TP/SL/max-hold) per asset class.

Deliberately uses HARDCODED exit rules rather than another LLM:
- The point is to measure whether the *ideas* have edge.
- If an LLM also decides exits, "idea quality" and "exit quality" mix
  in the P&L and we can't isolate which is driving the result.
- Once we know which sources/strategies have edge, an adaptive exit
  can be added on top.

No real money moves. Positions live in data/research_paper_trades.jsonl.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from loguru import logger

from .config import settings

PAPER_PATH = Path(__file__).parent.parent / "data" / "research_paper_trades.jsonl"

# Hardcoded exit rules per asset class. Tuned for "is the idea any good"
# rather than for max alpha. Same rules for everyone → fair comparison.
RULES = {
    "stocks":     {"stake_usd": 100.0, "tp_pct": 0.20, "sl_pct": -0.10, "max_days": 90},
    "crypto":     {"stake_usd": 100.0, "tp_pct": 0.30, "sl_pct": -0.15, "max_days": 60},
    # Polymarket priced 0-1; TP/SL are absolute % moves of position value.
    "polymarket": {"stake_usd": 5.00,  "tp_pct": 0.50, "sl_pct": -0.30, "max_days": 60},
}


# ──────────────────────────────────────────────────────────────────────
# Price resolution per asset class
# ──────────────────────────────────────────────────────────────────────

def _extract_stock_ticker(idea: Dict) -> Optional[str]:
    candidate = (idea.get("ticker_or_event") or "").strip()
    m = re.search(r"\b[A-Z]{1,5}\b", candidate)
    return m.group(0) if m else None


def _extract_crypto_symbol(idea: Dict) -> Optional[str]:
    candidate = (idea.get("ticker_or_event") or "").strip()
    m = re.search(r"\b[A-Z]{2,6}\b", candidate)
    return m.group(0) if m else None


def _stock_price_sync(ticker: str) -> Optional[float]:
    """Blocking yfinance call — wrap with asyncio.to_thread."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="5d", interval="1d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.debug(f"yfinance price failed for {ticker}: {e}")
        return None


async def _stock_price(ticker: str) -> Optional[float]:
    if not ticker:
        return None
    return await asyncio.to_thread(_stock_price_sync, ticker)


async def _crypto_price(symbol: str) -> Optional[float]:
    """CoinGecko spot. Returns USD price or None."""
    if not symbol:
        return None
    sym = symbol.upper().lstrip("$").rstrip("USDT")
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            sr = await c.get("https://api.coingecko.com/api/v3/search", params={"query": sym})
            sr.raise_for_status()
            coins = (sr.json() or {}).get("coins") or []
            if not coins:
                return None
            coin_id = coins[0].get("id")
            pr = await c.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd"},
            )
            pr.raise_for_status()
            data = (pr.json() or {}).get(coin_id) or {}
            return float(data.get("usd") or 0) or None
    except Exception as e:
        logger.debug(f"crypto price failed for {sym}: {e}")
        return None


async def _polymarket_price(idea: Dict) -> Optional[Dict]:
    """Resolve the Polymarket market from the Trader's target URL and return
    {price, token_id, condition_id, slug}. Price is the YES midpoint."""
    url = (idea.get("trader") or {}).get("target_market_url") or ""
    m = re.search(r"/event/([^/?#]+)", url)
    if not m:
        return None
    slug = m.group(1)
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f"{settings.gamma_api_url}/markets",
                params={"slug": slug, "limit": 1},
            )
            r.raise_for_status()
            markets = r.json() or []
            if not markets:
                # fallback via public-search
                sr = await c.get(
                    f"{settings.gamma_api_url}/public-search",
                    params={"q": slug.replace("-", " "), "events_status": "active", "limit_per_type": 1},
                )
                events = (sr.json() or {}).get("events") or []
                if not events or not events[0].get("markets"):
                    return None
                m_obj = events[0]["markets"][0]
            else:
                m_obj = markets[0]
        # Token ids parallel to outcomes; take the first (YES) token by convention.
        tokens_raw = m_obj.get("clobTokenIds", "[]")
        tokens = json.loads(tokens_raw) if isinstance(tokens_raw, str) else (tokens_raw or [])
        prices_raw = m_obj.get("outcomePrices", "[]")
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else (prices_raw or [])
        if not tokens or not prices:
            return None
        return {
            "price": float(prices[0]),
            "token_id": str(tokens[0]),
            "condition_id": m_obj.get("conditionId", ""),
            "slug": slug,
        }
    except Exception as e:
        logger.debug(f"polymarket price failed for {slug}: {e}")
        return None


async def _polymarket_current_price(token_id: str) -> Optional[float]:
    """Live midpoint for an existing position via CLOB book."""
    if not token_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get("https://clob.polymarket.com/book", params={"token_id": token_id})
            r.raise_for_status()
            data = r.json() or {}
            asks = data.get("asks") or []
            bids = data.get("bids") or []
            if not asks or not bids:
                return None
            best_ask = min(float(a["price"]) for a in asks)
            best_bid = max(float(b["price"]) for b in bids)
            return (best_ask + best_bid) / 2
    except Exception as e:
        logger.debug(f"clob midpoint failed for {token_id[:16]}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────

def _read_all() -> List[Dict]:
    if not PAPER_PATH.exists():
        return []
    out = []
    for line in PAPER_PATH.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _write_all(rows: List[Dict]) -> None:
    PAPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PAPER_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _append(row: Dict) -> None:
    PAPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PAPER_PATH, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _has_open_for_idea(idea_id: str) -> bool:
    return any(r.get("idea_id") == idea_id and r.get("status") == "open" for r in _read_all())


# ──────────────────────────────────────────────────────────────────────
# Open / close
# ──────────────────────────────────────────────────────────────────────

async def open_paper_position(idea: Dict) -> Optional[Dict]:
    """Auto-open a paper position when an idea reaches Implement. Idempotent
    on idea_id — re-running won't duplicate."""
    idea_id = idea.get("id")
    if not idea_id:
        return None
    if _has_open_for_idea(idea_id):
        return None

    mt = (idea.get("market_type") or "").lower()
    rules = RULES.get(mt)
    if not rules:
        logger.info(f"paper: skip {idea_id} — no rules for market_type={mt!r}")
        return None

    entry_price: Optional[float] = None
    instrument: Dict = {"market_type": mt}

    if mt == "stocks":
        ticker = _extract_stock_ticker(idea)
        if not ticker:
            return None
        entry_price = await _stock_price(ticker)
        instrument["ticker"] = ticker
    elif mt == "crypto":
        sym = _extract_crypto_symbol(idea)
        if not sym:
            return None
        entry_price = await _crypto_price(sym)
        instrument["symbol"] = sym
    elif mt == "polymarket":
        meta = await _polymarket_price(idea)
        if not meta:
            return None
        entry_price = meta["price"]
        instrument["token_id"] = meta["token_id"]
        instrument["condition_id"] = meta["condition_id"]
        instrument["slug"] = meta["slug"]

    if not entry_price or entry_price <= 0:
        logger.info(f"paper: skip {idea_id} — could not resolve entry price")
        return None

    row = {
        "id": uuid.uuid4().hex[:12],
        "idea_id": idea_id,
        "opened_at": datetime.utcnow().isoformat(),
        "status": "open",
        "market_type": mt,
        "ticker_or_event": idea.get("ticker_or_event"),
        "source": idea.get("source"),
        "source_url": idea.get("source_url"),
        "conviction": idea.get("conviction"),
        "instrument": instrument,
        "entry_price": entry_price,
        "stake_usd": rules["stake_usd"],
        "tp_pct": rules["tp_pct"],
        "sl_pct": rules["sl_pct"],
        "max_days": rules["max_days"],
        "thesis": (idea.get("thesis") or "")[:300],
        "judgement_confidence": (idea.get("judgement") or {}).get("confidence"),
    }
    _append(row)
    logger.info(f"📝 paper-trade opened: {row['id']} {mt} {row['ticker_or_event']} @ {entry_price}")
    return row


async def _current_price(pos: Dict) -> Optional[float]:
    mt = pos.get("market_type")
    inst = pos.get("instrument") or {}
    if mt == "stocks":
        return await _stock_price(inst.get("ticker", ""))
    if mt == "crypto":
        return await _crypto_price(inst.get("symbol", ""))
    if mt == "polymarket":
        return await _polymarket_current_price(inst.get("token_id", ""))
    return None


def _evaluate_exit(pos: Dict, current_price: float, now: datetime) -> Optional[str]:
    """Return an exit reason if the position should close, else None."""
    entry = float(pos.get("entry_price") or 0)
    if entry <= 0:
        return None
    pnl_pct = (current_price - entry) / entry
    if pnl_pct >= pos["tp_pct"]:
        return "take_profit"
    if pnl_pct <= pos["sl_pct"]:
        return "stop_loss"
    try:
        opened = datetime.fromisoformat(str(pos["opened_at"]).replace("Z", ""))
    except Exception:
        return None
    if (now - opened) >= timedelta(days=pos["max_days"]):
        return "max_hold"
    return None


def _close_position(pos: Dict, exit_price: float, reason: str, now: datetime) -> Dict:
    entry = float(pos.get("entry_price") or 0)
    stake = float(pos.get("stake_usd") or 0)
    pnl_pct = ((exit_price - entry) / entry) if entry else 0
    pnl_usd = stake * pnl_pct
    pos["status"] = "closed"
    pos["closed_at"] = now.isoformat()
    pos["exit_price"] = exit_price
    pos["exit_reason"] = reason
    pos["pnl_pct"] = round(pnl_pct, 4)
    pos["pnl_usd"] = round(pnl_usd, 2)
    return pos


async def tick_all_positions() -> Dict:
    """Update every open paper position. Close if exit rules trigger.
    Returns a summary suitable for an API response."""
    rows = _read_all()
    now = datetime.utcnow()
    closed = 0
    updated = 0
    errors: List[str] = []
    sem = asyncio.Semaphore(4)

    async def _one(pos: Dict):
        nonlocal closed, updated
        if pos.get("status") != "open":
            return
        async with sem:
            try:
                price = await _current_price(pos)
            except Exception as e:
                errors.append(f"{pos['id']}: {e}")
                return
        if price is None or price <= 0:
            return
        pos["last_price"] = price
        pos["last_price_at"] = now.isoformat()
        reason = _evaluate_exit(pos, price, now)
        if reason:
            _close_position(pos, price, reason, now)
            closed += 1
        else:
            updated += 1

    await asyncio.gather(*(_one(p) for p in rows))
    _write_all(rows)
    return {"updated": updated, "closed": closed, "open": sum(1 for r in rows if r.get("status") == "open"),
            "total": len(rows), "errors": errors[:5]}


# ──────────────────────────────────────────────────────────────────────
# Read APIs for endpoints
# ──────────────────────────────────────────────────────────────────────

def list_positions(status: Optional[str] = None, limit: int = 500) -> List[Dict]:
    rows = _read_all()
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("opened_at", ""), reverse=True)
    return rows[:limit]


def stats() -> Dict:
    """Aggregate P&L by source / market_type / conviction bucket."""
    rows = _read_all()
    closed = [r for r in rows if r.get("status") == "closed"]
    by_source: Dict[str, Dict] = {}
    by_market: Dict[str, Dict] = {}
    by_conv: Dict[str, Dict] = {}

    def _bucket(d: Dict, key: str, pnl: float, win: bool):
        b = d.setdefault(key, {"trades": 0, "wins": 0, "pnl_usd": 0.0})
        b["trades"] += 1
        if win:
            b["wins"] += 1
        b["pnl_usd"] += pnl

    for r in closed:
        pnl = float(r.get("pnl_usd") or 0)
        win = pnl > 0
        _bucket(by_source, r.get("source") or "?", pnl, win)
        _bucket(by_market, r.get("market_type") or "?", pnl, win)
        conv = r.get("conviction")
        conv_key = f"★{conv}" if conv else "?"
        _bucket(by_conv, conv_key, pnl, win)

    def _round(d: Dict) -> Dict:
        for v in d.values():
            v["pnl_usd"] = round(v["pnl_usd"], 2)
            v["win_rate"] = round(v["wins"] / v["trades"], 2) if v["trades"] else None
        return d

    return {
        "open": sum(1 for r in rows if r.get("status") == "open"),
        "closed": len(closed),
        "net_pnl_usd": round(sum(float(r.get("pnl_usd") or 0) for r in closed), 2),
        "by_source": _round(by_source),
        "by_market": _round(by_market),
        "by_conviction": _round(by_conv),
    }
