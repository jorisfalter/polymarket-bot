"""
Idea Judge — second LLM pass that decides if an idea is actionable now.

Reads each idea surfaced by research_agent and enriches it with live
context (Polymarket market state, stock price, crypto funding, bot
journal), then asks an LLM:
    "Is this actionable RIGHT NOW? What specific trade? Why? Risks?"

Output is advisory — the user clicks Take Action in the UI, this module
never executes a trade. That separation is deliberate: the research +
judge pipeline runs 2× per day, but trades only happen on user click
(or via the autonomous AI agent's own cycle, which already has its own
risk controls).

Cost: ~$0.02 per idea (DeepSeek), so ~$0.20 per research run with 10 ideas.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from loguru import logger

from .config import settings


# ──────────────────────────────────────────────────────────────────────
# Market data lookups (per asset class)
# ──────────────────────────────────────────────────────────────────────

async def _polymarket_search(query: str, limit: int = 3) -> List[Dict]:
    """Search Polymarket Gamma for markets matching the idea. Returns
    open markets only, with question + price + end date + token IDs."""
    if not query:
        return []
    url = f"{settings.gamma_api_url}/markets"
    # Take the most informative ~4 words from the query
    cleaned = re.sub(r"[^a-zA-Z0-9 ]", " ", query)[:80]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params={
                "q": cleaned,
                "active": "true",
                "closed": "false",
                "limit": limit,
            })
            r.raise_for_status()
            markets = r.json() or []
    except Exception as e:
        logger.debug(f"polymarket search failed for '{cleaned}': {e}")
        return []
    out = []
    for m in markets[:limit]:
        # Gamma sometimes returns price as JSON string '[0.04,0.96]'
        prices = m.get("outcomePrices") or m.get("outcome_prices") or "[]"
        try:
            prices = json.loads(prices) if isinstance(prices, str) else prices
        except Exception:
            prices = []
        out.append({
            "question": m.get("question") or m.get("title") or "",
            "slug": m.get("slug", ""),
            "url": f"https://polymarket.com/event/{m.get('slug','')}",
            "outcomes": m.get("outcomes"),
            "outcome_prices": prices,
            "end_date": m.get("endDate") or m.get("endDateIso") or "",
            "volume": m.get("volume") or 0,
            "accepting_orders": m.get("acceptingOrders", True),
        })
    return out


def _stock_quote_sync(ticker: str) -> Optional[Dict]:
    """Blocking yfinance call — wrap with asyncio.to_thread."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info  # lightweight, no full info() call needed
        hist = t.history(period="1mo", interval="1d")
        if hist.empty:
            return None
        last = float(hist["Close"].iloc[-1])
        wk52_low = float(getattr(info, "year_low", 0)) or float(hist["Close"].min())
        wk52_high = float(getattr(info, "year_high", 0)) or float(hist["Close"].max())
        d1_change = float((hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100) if len(hist) >= 2 else 0
        return {
            "ticker": ticker.upper(),
            "price": round(last, 2),
            "year_low": round(wk52_low, 2),
            "year_high": round(wk52_high, 2),
            "1d_change_pct": round(d1_change, 2),
            "from_52w_high_pct": round((last / wk52_high - 1) * 100, 1) if wk52_high else None,
        }
    except Exception as e:
        logger.debug(f"yfinance fetch failed for {ticker}: {e}")
        return None


async def _stock_quote(ticker: str) -> Optional[Dict]:
    if not ticker:
        return None
    return await asyncio.to_thread(_stock_quote_sync, ticker)


async def _crypto_quote(symbol: str) -> Optional[Dict]:
    """CoinGecko free spot + Binance perp funding. Both keyless."""
    if not symbol:
        return None
    sym = symbol.upper().lstrip("$").rstrip("USDT")
    out: Dict = {"symbol": sym}
    try:
        # Spot via CoinGecko search → id → price
        async with httpx.AsyncClient(timeout=8.0) as client:
            sr = await client.get(
                "https://api.coingecko.com/api/v3/search",
                params={"query": sym},
            )
            sr.raise_for_status()
            coins = (sr.json() or {}).get("coins") or []
            if coins:
                coin_id = coins[0].get("id")
                pr = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"},
                )
                pr.raise_for_status()
                data = (pr.json() or {}).get(coin_id) or {}
                out["spot_usd"] = data.get("usd")
                out["change_24h_pct"] = round(data.get("usd_24h_change") or 0, 2)
                out["coingecko_id"] = coin_id
    except Exception as e:
        logger.debug(f"coingecko fetch failed for {sym}: {e}")
    try:
        # Perp funding via Binance public premiumIndex
        async with httpx.AsyncClient(timeout=6.0) as client:
            fr = await client.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": f"{sym}USDT"},
            )
            if fr.status_code == 200:
                fd = fr.json() or {}
                rate = float(fd.get("lastFundingRate") or 0)
                out["funding_rate_pct"] = round(rate * 100, 4)
    except Exception as e:
        logger.debug(f"binance funding fetch failed for {sym}: {e}")
    return out if out.get("spot_usd") or out.get("funding_rate_pct") else None


def _bot_state_snapshot() -> Dict:
    """Compact view of the bot's current state for the LLM."""
    try:
        from . import trade_journal as journal
        open_positions = journal.get_open_positions()
        exposure = sum(p.get("amount_usd") or 0 for p in open_positions)
        return {
            "open_positions": len(open_positions),
            "total_exposure_usd": round(exposure, 2),
            "max_total_exposure_usd": settings.agent_max_total_exposure,
            "max_per_trade_usd": settings.agent_max_per_trade,
            "open_market_questions": [p.get("market_question", "")[:80] for p in open_positions[:8]],
        }
    except Exception as e:
        logger.debug(f"bot state snapshot failed: {e}")
        return {}


# ──────────────────────────────────────────────────────────────────────
# LLM judgement
# ──────────────────────────────────────────────────────────────────────

JUDGE_SYSTEM = (
    "Je bent een hedge-fund risk officer. Voor ELK idee dat je krijgt, "
    "samen met live market data + de bot's huidige state, beslis je of "
    "het idee NU actionable is. Wees streng:\n"
    "- 'actionable': er is een concrete trade te doen vandaag/deze week, "
    "het idee matcht echte market data, risk is acceptabel binnen de bot's "
    "limieten.\n"
    "- 'monitor': het idee is interessant maar prijs is verkeerd / event ligt "
    "nog ver weg / setup nog niet rijp. Notitie maken, niet handelen.\n"
    "- 'dismiss': idee is niet actionable — geen markt, te speculatief, "
    "bot's risk-budget zit vol, of de thesis is al ingeprijsd.\n\n"
    "Bot policy: $10 max per trade, $100 max total exposure, $1.05 minimum "
    "order. Voor Polymarket-trades: alleen mainstream markten (skip sports, "
    "skip BTC/ETH-prijs bingo).\n\n"
    "Geef ALLEEN valid JSON terug, exact dit schema:\n"
    "{\"verdict\":\"actionable\"|\"monitor\"|\"dismiss\","
    "\"confidence\":0.0-1.0,"
    "\"suggested_action\":\"specifieke 1-lijn actie\","
    "\"target_market_url\":string|null,"
    "\"entry_price\":float|null,"
    "\"stake_usd\":float|null,"
    "\"why\":\"1-2 zin onderbouwing\","
    "\"risks\":\"1-2 specifieke risico's\"}"
)


def _call_llm_sync(system: str, user: str, max_tokens: int = 500) -> str:
    """Sync LLM call. Mirrors research_agent._call_llm."""
    try:
        from openai import OpenAI
    except ImportError:
        return ""
    key = settings.openrouter_api_key or settings.anthropic_api_key
    if not key:
        return ""
    base_url = (
        "https://openrouter.ai/api/v1"
        if settings.openrouter_api_key
        else "https://api.anthropic.com/v1"
    )
    try:
        client = OpenAI(api_key=key, base_url=base_url)
        resp = client.chat.completions.create(
            model=settings.agent_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning(f"judge LLM call failed: {e}")
        return ""


# ──────────────────────────────────────────────────────────────────────
# Per-asset-class context builders
# ──────────────────────────────────────────────────────────────────────

async def _build_context(idea: Dict) -> Dict:
    """Pull live data relevant to this idea's market_type."""
    mt = (idea.get("market_type") or "").lower()
    target = (idea.get("ticker_or_event") or "") + " " + (idea.get("thesis") or "")[:200]
    ctx: Dict = {"market_type": mt}

    if mt == "polymarket":
        ctx["polymarket_matches"] = await _polymarket_search(target, limit=3)
    elif mt == "stocks":
        # Try to extract a ticker from ticker_or_event
        candidate = (idea.get("ticker_or_event") or "").strip()
        # Pick first all-caps 1-5 letter token as the ticker
        m = re.search(r"\b[A-Z]{1,5}\b", candidate)
        ticker = m.group(0) if m else None
        if ticker:
            ctx["stock_quote"] = await _stock_quote(ticker)
        # Also search Polymarket — many stock-themed events have markets there
        ctx["polymarket_matches"] = await _polymarket_search(target, limit=2)
    elif mt == "crypto":
        candidate = (idea.get("ticker_or_event") or "").strip()
        m = re.search(r"\b[A-Z]{2,6}\b", candidate)
        sym = m.group(0) if m else None
        if sym:
            ctx["crypto_quote"] = await _crypto_quote(sym)
        ctx["polymarket_matches"] = await _polymarket_search(target, limit=2)
    # macro: no market lookup needed

    ctx["bot_state"] = _bot_state_snapshot()
    return ctx


# ──────────────────────────────────────────────────────────────────────
# Public entry points
# ──────────────────────────────────────────────────────────────────────

async def judge_idea(idea: Dict) -> Dict:
    """Build context, call LLM, return verdict dict.

    Verdict schema is appended to the idea row by research_agent.
    """
    ctx = await _build_context(idea)
    user_msg = (
        "IDEA:\n"
        f"{json.dumps({k: idea.get(k) for k in ['market_type','ticker_or_event','thesis','conviction','why_now','resolves_when','source']}, ensure_ascii=False)}\n\n"
        "LIVE CONTEXT:\n"
        f"{json.dumps(ctx, ensure_ascii=False)[:6000]}"
    )
    raw = await asyncio.to_thread(_call_llm_sync, JUDGE_SYSTEM, user_msg, 500)
    if not raw:
        return _fallback_verdict("LLM call returned empty")
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        verdict = json.loads(cleaned)
    except json.JSONDecodeError:
        return _fallback_verdict(f"invalid JSON: {raw[:120]}")
    # Normalize / cap
    verdict["verdict"] = (verdict.get("verdict") or "monitor").lower()
    if verdict["verdict"] not in {"actionable", "monitor", "dismiss"}:
        verdict["verdict"] = "monitor"
    if verdict.get("stake_usd") is not None:
        try:
            verdict["stake_usd"] = min(float(verdict["stake_usd"]), settings.agent_max_per_trade)
        except Exception:
            verdict["stake_usd"] = None
    verdict["judged_at"] = datetime.utcnow().isoformat()
    # If polymarket and we found a market but the LLM didn't include URL, fill it
    if not verdict.get("target_market_url"):
        matches = ctx.get("polymarket_matches") or []
        if matches and matches[0].get("url"):
            verdict["target_market_url"] = matches[0]["url"]
    return verdict


def _fallback_verdict(reason: str) -> Dict:
    return {
        "verdict": "monitor",
        "confidence": 0.0,
        "suggested_action": "(judge failed — review manually)",
        "target_market_url": None,
        "entry_price": None,
        "stake_usd": None,
        "why": reason,
        "risks": "judge offline",
        "judged_at": datetime.utcnow().isoformat(),
    }


async def judge_many(ideas: List[Dict], concurrency: int = 3) -> List[Dict]:
    """Judge ideas sequentially-ish (low concurrency to be API-friendly).
    Returns the same list with a 'judgement' key added per item."""
    sem = asyncio.Semaphore(concurrency)
    async def _bound(it: Dict) -> Dict:
        async with sem:
            verdict = await judge_idea(it)
            return {**it, "judgement": verdict}
    return await asyncio.gather(*(_bound(it) for it in ideas))
