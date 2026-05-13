"""
Idea pipeline — 4 stages run sequentially after the Scout (research_agent):

    Scout       → produces raw ideas with thesis + conviction (existing code).
    Skeptic     → devil's advocate, validates thesis against live market.
    Stakes      → sizing + risk allocation for validated ideas.
    Trader      → concrete trade plan: market URL, entry, exits, stop.

Each AI role is a focused short prompt (cheaper than a single big judge)
and produces a typed JSON blob that lives alongside the idea record:

    idea.stage             ∈ raw / validated / staked / implement / rejected
    idea.skeptic           = {pass, score, strong_thesis, rejected_reason}
    idea.stakes            = {stake_usd, max_exposure_pct, rationale}
    idea.trader            = {target_market_url, entry_price, exit_triggers,
                              stop_loss, time_to_resolution}

Advisory only — no auto-execution. The Implement column is a tray of
ready-to-execute plans; the user clicks to act.

Cost budget: ~$0.10/run with DeepSeek (3 LLM calls per surviving idea).
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
# Shared LLM helper
# ──────────────────────────────────────────────────────────────────────

_llm = None


def _get_llm():
    """Lazy OpenAI-compatible client, OpenRouter preferred."""
    global _llm
    if _llm is not None:
        return _llm
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai SDK not available; pipeline disabled")
        return None
    key = settings.openrouter_api_key or settings.anthropic_api_key
    if not key:
        logger.warning("No LLM key configured; pipeline disabled")
        return None
    base_url = (
        "https://openrouter.ai/api/v1"
        if settings.openrouter_api_key
        else "https://api.anthropic.com/v1"
    )
    _llm = OpenAI(api_key=key, base_url=base_url)
    return _llm


def _call_llm_sync(system: str, user: str, max_tokens: int = 500) -> str:
    client = _get_llm()
    if not client:
        return ""
    try:
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
        logger.warning(f"pipeline LLM call failed: {e}")
        return ""


def _parse_json(raw: str) -> Optional[Dict]:
    """Parse LLM output expecting JSON. Tolerant of ```json fences."""
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


# ──────────────────────────────────────────────────────────────────────
# Live market context (re-used by Skeptic + Stakes + Trader)
# ──────────────────────────────────────────────────────────────────────

async def _polymarket_search(query: str, limit: int = 3) -> List[Dict]:
    if not query:
        return []
    cleaned = re.sub(r"[^a-zA-Z0-9 ]", " ", query)[:80]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{settings.gamma_api_url}/markets",
                params={"q": cleaned, "active": "true", "closed": "false", "limit": limit},
            )
            r.raise_for_status()
            markets = r.json() or []
    except Exception as e:
        logger.debug(f"polymarket search failed: {e}")
        return []
    out = []
    for m in markets[:limit]:
        prices = m.get("outcomePrices") or "[]"
        try:
            prices = json.loads(prices) if isinstance(prices, str) else prices
        except Exception:
            prices = []
        out.append({
            "question": m.get("question", "")[:120],
            "slug": m.get("slug", ""),
            "url": f"https://polymarket.com/event/{m.get('slug','')}",
            "outcomes": m.get("outcomes"),
            "outcome_prices": prices,
            "end_date": m.get("endDate", "")[:19],
            "volume": m.get("volume") or 0,
        })
    return out


def _stock_quote_sync(ticker: str) -> Optional[Dict]:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        hist = t.history(period="1mo", interval="1d")
        if hist.empty:
            return None
        last = float(hist["Close"].iloc[-1])
        wk52_low = float(getattr(info, "year_low", 0)) or float(hist["Close"].min())
        wk52_high = float(getattr(info, "year_high", 0)) or float(hist["Close"].max())
        return {
            "ticker": ticker.upper(),
            "price": round(last, 2),
            "year_low": round(wk52_low, 2),
            "year_high": round(wk52_high, 2),
            "from_52w_high_pct": round((last / wk52_high - 1) * 100, 1) if wk52_high else None,
        }
    except Exception as e:
        logger.debug(f"yfinance failed for {ticker}: {e}")
        return None


async def _stock_quote(ticker: str) -> Optional[Dict]:
    if not ticker:
        return None
    return await asyncio.to_thread(_stock_quote_sync, ticker)


async def _crypto_quote(symbol: str) -> Optional[Dict]:
    if not symbol:
        return None
    sym = symbol.upper().lstrip("$").rstrip("USDT")
    out: Dict = {"symbol": sym}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            sr = await client.get("https://api.coingecko.com/api/v3/search", params={"query": sym})
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
    except Exception as e:
        logger.debug(f"coingecko failed: {e}")
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            fr = await client.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": f"{sym}USDT"},
            )
            if fr.status_code == 200:
                rate = float((fr.json() or {}).get("lastFundingRate") or 0)
                out["funding_rate_pct"] = round(rate * 100, 4)
    except Exception as e:
        logger.debug(f"binance funding failed: {e}")
    return out if out.get("spot_usd") or out.get("funding_rate_pct") else None


def _bot_state() -> Dict:
    try:
        from . import trade_journal as journal
        open_positions = journal.get_open_positions()
        exposure = sum(p.get("amount_usd") or 0 for p in open_positions)
        return {
            "open_positions": len(open_positions),
            "total_exposure_usd": round(exposure, 2),
            "max_total_exposure_usd": settings.agent_max_total_exposure,
            "max_per_trade_usd": settings.agent_max_per_trade,
        }
    except Exception:
        return {}


async def _build_market_context(idea: Dict) -> Dict:
    """Pull live data based on the idea's market_type. Shared between roles."""
    mt = (idea.get("market_type") or "").lower()
    target = (idea.get("ticker_or_event") or "") + " " + (idea.get("thesis") or "")[:200]
    ctx: Dict = {"market_type": mt, "bot_state": _bot_state()}
    if mt == "polymarket":
        ctx["polymarket_matches"] = await _polymarket_search(target, limit=3)
    elif mt == "stocks":
        m = re.search(r"\b[A-Z]{1,5}\b", idea.get("ticker_or_event") or "")
        if m:
            ctx["stock_quote"] = await _stock_quote(m.group(0))
        ctx["polymarket_matches"] = await _polymarket_search(target, limit=2)
    elif mt == "crypto":
        m = re.search(r"\b[A-Z]{2,6}\b", idea.get("ticker_or_event") or "")
        if m:
            ctx["crypto_quote"] = await _crypto_quote(m.group(0))
        ctx["polymarket_matches"] = await _polymarket_search(target, limit=2)
    return ctx


# ──────────────────────────────────────────────────────────────────────
# Role 1: Skeptic — devil's advocate
# ──────────────────────────────────────────────────────────────────────

SKEPTIC_SYSTEM = (
    "Je bent een hedge-fund skeptic. Voor elk trading idea: zoek WAAROM het "
    "WAARSCHIJNLIJK NIET zal werken. Verdedig het tegendeel. Een goed idea "
    "moet jouw kritiek overleven. Wees streng — afwijzen is de default.\n\n"
    "Check op:\n"
    "- Is de thesis al ingeprijsd? (kijk naar polymarket_matches / stock_quote / crypto_quote)\n"
    "- Is dit een hot-take of een gefundeerde claim?\n"
    "- Mist er een why-now? (vage 'wordt groot' zonder catalyst = reject)\n"
    "- Is het event/marktbeweging te ver weg om actionable te zijn?\n"
    "- Is er een fade-side (insider die juist het tegenovergestelde koopt)?\n\n"
    "Pass = idea overleeft kritisch onderzoek. Reject = te zwak.\n\n"
    "Geef ALLEEN valid JSON terug, exact dit schema:\n"
    "{\"pass\": bool, \"score\": 0.0-1.0, "
    "\"strong_thesis\": \"1-zin verbeterde thesis als pass, anders null\", "
    "\"rejected_reason\": \"1-zin waarom niet als reject, anders null\", "
    "\"devils_advocate\": \"1-zin sterkste tegen-argument je vond\"}"
)


async def run_skeptic(idea: Dict, ctx: Optional[Dict] = None) -> Dict:
    """Pass: idea moves to 'validated'. Reject: idea ends in 'rejected'."""
    ctx = ctx or await _build_market_context(idea)
    user = (
        "IDEA:\n" + json.dumps({k: idea.get(k) for k in
            ["market_type", "ticker_or_event", "thesis", "conviction", "why_now", "source"]},
            ensure_ascii=False)
        + "\n\nLIVE MARKET CONTEXT:\n" + json.dumps(ctx, ensure_ascii=False)[:5500]
    )
    raw = await asyncio.to_thread(_call_llm_sync, SKEPTIC_SYSTEM, user, 350)
    data = _parse_json(raw) or {}
    return {
        "pass": bool(data.get("pass", False)),
        "score": float(data.get("score") or 0),
        "strong_thesis": data.get("strong_thesis"),
        "rejected_reason": data.get("rejected_reason"),
        "devils_advocate": data.get("devils_advocate"),
        "at": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────
# Role 2: Stakes — sizing + risk allocation
# ──────────────────────────────────────────────────────────────────────

STAKES_SYSTEM = (
    "Je bent een hedge-fund risk officer. Een idea is gevalideerd. Bepaal: "
    "hoeveel stake en wat is de max exposure?\n\n"
    "Bot hard caps (NIET overschrijden):\n"
    "- Max per trade: $10\n"
    "- Max total exposure: $100\n"
    "- Min order: $1.05 (Polymarket minimum)\n\n"
    "Houd rekening met:\n"
    "- Huidige exposure van de bot (bot_state.total_exposure_usd)\n"
    "- Conviction-niveau (hogere conviction → grotere stake binnen cap)\n"
    "- Asymmetry: longshots ≤3c krijgen kleinere stakes ($1-2), high-prob "
    "  base-rate plays kunnen $5-10\n"
    "- Concentration risk: als bot al veel exposure heeft in zelfde thema, "
    "  reduce of skip\n\n"
    "Geef ALLEEN valid JSON terug:\n"
    "{\"stake_usd\": float (1.05-10), "
    "\"max_exposure_pct\": float (% van $100 cap), "
    "\"rationale\": \"1-2 zin waarom deze stake/exposure\", "
    "\"skip\": bool (true als concentration of risk reden om uberhaupt niet te traden)}"
)


async def run_stakes(idea: Dict, ctx: Optional[Dict] = None) -> Dict:
    ctx = ctx or await _build_market_context(idea)
    user = (
        "IDEA (validated):\n" + json.dumps({k: idea.get(k) for k in
            ["market_type", "ticker_or_event", "thesis", "conviction"]},
            ensure_ascii=False)
        + "\nSKEPTIC NOTES:\n" + json.dumps(idea.get("skeptic", {}), ensure_ascii=False)
        + "\nBOT STATE:\n" + json.dumps(ctx.get("bot_state", {}), ensure_ascii=False)
    )
    raw = await asyncio.to_thread(_call_llm_sync, STAKES_SYSTEM, user, 250)
    data = _parse_json(raw) or {}
    stake = data.get("stake_usd")
    if stake is not None:
        try:
            stake = max(1.05, min(float(stake), settings.agent_max_per_trade))
        except Exception:
            stake = None
    return {
        "stake_usd": stake,
        "max_exposure_pct": data.get("max_exposure_pct"),
        "rationale": data.get("rationale"),
        "skip": bool(data.get("skip", False)),
        "at": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────
# Role 3: Trader — concrete execution plan
# ──────────────────────────────────────────────────────────────────────

TRADER_SYSTEM = (
    "Je bent een trader die een concreet trade-plan schrijft. Het idea is "
    "gevalideerd én sized. Maak nu het actuele plan klaar voor uitvoering.\n\n"
    "Output is advisory — de user klikt zelf om uit te voeren. Maar wees "
    "specifiek genoeg dat 't direct uitvoerbaar is.\n\n"
    "Voor polymarket-trades: cite de exacte markt-URL uit polymarket_matches "
    "context (als er geen goede match is, zet 'target_market_url' op null en "
    "leg uit in rationale).\n"
    "Voor stocks: geef ticker + entry-prijs + exit-triggers.\n"
    "Voor crypto: spot of perp, exchange, entry + stop.\n\n"
    "Geef ALLEEN valid JSON terug:\n"
    "{\"target_market_url\": string|null, "
    "\"entry_price\": float|null, "
    "\"exit_triggers\": \"1-2 zin: TP/SL/event-resolve trigger\", "
    "\"stop_loss\": float|string|null, "
    "\"time_to_resolution\": \"hours/days/weeks of een datum\", "
    "\"action_summary\": \"1 zin samenvatting van de hele trade\"}"
)


async def run_trader(idea: Dict, ctx: Optional[Dict] = None) -> Dict:
    ctx = ctx or await _build_market_context(idea)
    user = (
        "IDEA (validated + staked):\n" + json.dumps({k: idea.get(k) for k in
            ["market_type", "ticker_or_event", "thesis"]}, ensure_ascii=False)
        + "\nSTAKES:\n" + json.dumps(idea.get("stakes", {}), ensure_ascii=False)
        + "\nLIVE MARKET CONTEXT:\n" + json.dumps(ctx, ensure_ascii=False)[:5000]
    )
    raw = await asyncio.to_thread(_call_llm_sync, TRADER_SYSTEM, user, 350)
    data = _parse_json(raw) or {}
    return {
        "target_market_url": data.get("target_market_url"),
        "entry_price": data.get("entry_price"),
        "exit_triggers": data.get("exit_triggers"),
        "stop_loss": data.get("stop_loss"),
        "time_to_resolution": data.get("time_to_resolution"),
        "action_summary": data.get("action_summary"),
        "at": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────
# Pipeline orchestrator
# ──────────────────────────────────────────────────────────────────────

async def run_pipeline_one(idea: Dict) -> Dict:
    """Run an idea through all 3 stages. Stops early on rejection/skip.

    Returns the idea dict with skeptic / stakes / trader / stage fields
    populated. The caller persists it.
    """
    # Build context once, reuse across all three roles
    ctx = await _build_market_context(idea)

    # Stage 1: Skeptic
    sk = await run_skeptic(idea, ctx=ctx)
    idea["skeptic"] = sk
    if not sk.get("pass"):
        idea["stage"] = "rejected"
        return idea

    idea["stage"] = "validated"

    # Stage 2: Stakes
    st = await run_stakes(idea, ctx=ctx)
    idea["stakes"] = st
    if st.get("skip") or not st.get("stake_usd"):
        # Skeptic said pass, but stakes refuses (concentration risk) — keep at validated
        return idea

    idea["stage"] = "staked"

    # Stage 3: Trader
    tr = await run_trader(idea, ctx=ctx)
    idea["trader"] = tr
    idea["stage"] = "implement"
    return idea


async def run_pipeline(ideas: List[Dict], concurrency: int = 2) -> List[Dict]:
    """Run pipeline on a batch of ideas, capped concurrency to stay friendly
    to the LLM provider."""
    sem = asyncio.Semaphore(concurrency)
    async def _bound(it: Dict) -> Dict:
        async with sem:
            try:
                return await run_pipeline_one(it)
            except Exception as e:
                logger.warning(f"pipeline error for idea {it.get('id')}: {e}")
                it["stage"] = it.get("stage") or "raw"
                return it
    return await asyncio.gather(*(_bound(it) for it in ideas))
