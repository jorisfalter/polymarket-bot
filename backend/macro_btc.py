"""
Macro-Event BTC Paper Trader — "money printer" continuation strategy.

Research: docs/research/macro-event-btc-bot.md

Thesis: rare monetary/fiscal liquidity events (Treasury buybacks, QE-like
interventions) drive multi-day BTC trends. The price signature alone is a
coin flip (backtest 2023-2026: 25 hits, avg +0.7% over 3 days) — the edge,
if any, is in classifying the CAUSE. Liquidity events (SVB/BTFP 2023,
Treasury buybacks Aug 2026) continued +10%; ETF hype and bare short
squeezes mean-reverted.

Architecture (market-first, not news-first — see research note):
  1. Deterministic trigger, checked hourly: BTC >= +5% from day open AND
     gold (PAXG) up same day. Fires ~7x/year.
  2. Only then: fetch headlines, LLM classifies cause. Only
     "monetary_liquidity" with confidence >= threshold -> paper entry.
  3. Paper position: 2x on fictional capital, trailing stop, max 72h hold.
  4. Telegram on trigger + exit only (rare by design — user wants no
     daily noise, only the unique clear cases).

PAPER ONLY — no Binance keys, no real orders. Public endpoints only.
"""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from .config import settings

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path("data/macro_btc_paper.jsonl")
STATE_PATH = Path("data/macro_btc_state.json")

BINANCE_API = "https://api.binance.com/api/v3"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

CLASSIFY_PROMPT = """You are a macro analyst. Bitcoin is up {btc_pct:+.1f}% today and gold is up {gold_pct:+.1f}% today ({date} UTC).

Here are today's news headlines:

{headlines}

Classify the PRIMARY cause of this bitcoin move into exactly one category:
- "monetary_liquidity": an ACTUAL central bank or treasury operation that expands liquidity or signals fiat debasement (QE, bond buybacks, emergency lending facilities like BTFP, yield curve intervention, large fiscal stimulus passage). NOT merely dovish commentary, rate-cut expectations, a soft CPI print, or an FOMC hold — words and data are not operations
- "etf_flows": ETF inflows / institutional allocation news
- "short_squeeze_only": derivatives liquidation cascade without a clear macro catalyst
- "crypto_idiosyncratic": crypto-specific news (regulation, halving, exchange events, adoption)
- "other": anything else / unclear

Respond with ONLY a JSON object, no markdown:
{{"cause": "<category>", "confidence": <0.0-1.0>, "headline_evidence": "<the 1-2 headlines that support this>", "reasoning": "<one sentence>"}}"""


class MacroBTCPaperTrader:
    """Hourly cycle: check trigger -> classify cause -> manage paper position."""

    def __init__(self):
        self.state = self._load_state()

    # ---------- state / journal ----------

    def _load_state(self) -> dict:
        if STATE_PATH.exists():
            try:
                return json.loads(STATE_PATH.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"position": None, "last_trigger_date": None}

    def _save_state(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(self.state, indent=2))

    def _journal(self, record: dict):
        record["ts"] = datetime.now(timezone.utc).isoformat()
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def get_journal(self, limit: int = 100) -> list:
        if not JOURNAL_PATH.exists():
            return []
        entries = []
        for line in JOURNAL_PATH.read_text().strip().split("\n"):
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries[-limit:]

    # ---------- market data ----------

    async def _day_change(self, client: httpx.AsyncClient, symbol: str) -> Optional[dict]:
        """Today's UTC daily candle: open, last price, % change from open."""
        r = await client.get(f"{BINANCE_API}/klines",
                             params={"symbol": symbol, "interval": "1d", "limit": 1})
        r.raise_for_status()
        k = r.json()[-1]
        o, last = float(k[1]), float(k[4])
        return {"open": o, "last": last, "pct": (last / o - 1) * 100}

    # ---------- headlines ----------

    async def _fetch_headlines(self, client: httpx.AsyncClient) -> list:
        """Top headlines from Google News RSS for today's macro + bitcoin news."""
        titles = []
        for query in ("bitcoin when:1d", "treasury OR \"federal reserve\" OR liquidity when:1d"):
            try:
                r = await client.get(GOOGLE_NEWS_RSS,
                                     params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
                                     follow_redirects=True)
                r.raise_for_status()
                found = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", r.text)
                titles.extend(t.strip() for t in found[:16]
                              if "Google News" not in t)  # drop feed/channel titles
            except Exception as e:
                logger.warning(f"Headline fetch failed for '{query}': {e}")
        # Dedupe, keep order
        seen, unique = set(), []
        for t in titles:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique[:25]

    # ---------- LLM classification ----------

    async def _classify(self, btc_pct: float, gold_pct: float, headlines: list) -> Optional[dict]:
        if not (settings.openrouter_api_key or settings.anthropic_api_key):
            logger.warning("macro_btc: no LLM API key — cannot classify")
            return None
        prompt = CLASSIFY_PROMPT.format(
            btc_pct=btc_pct, gold_pct=gold_pct,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            headlines="\n".join(f"- {h}" for h in headlines) or "(no headlines available)",
        )
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                if settings.openrouter_api_key:
                    r = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                        json={"model": settings.agent_model,
                              "messages": [{"role": "user", "content": prompt}],
                              "temperature": 0.1},
                    )
                    r.raise_for_status()
                    text = r.json()["choices"][0]["message"]["content"].strip()
                else:
                    # Anthropic native fallback (local dev has no OpenRouter key)
                    r = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={"x-api-key": settings.anthropic_api_key,
                                 "anthropic-version": "2023-06-01"},
                        json={"model": "claude-haiku-4-5-20251001", "max_tokens": 500,
                              "messages": [{"role": "user", "content": prompt}]},
                    )
                    r.raise_for_status()
                    text = r.json()["content"][0]["text"].strip()
            m = re.search(r"\{.*\}", text, re.DOTALL)
            return json.loads(m.group(0)) if m else None
        except Exception as e:
            logger.error(f"macro_btc classification failed: {e}")
            return None

    # ---------- main cycle ----------

    async def run_cycle(self, force_trigger: bool = False, notify: bool = True) -> dict:
        """Hourly. Returns a summary dict (also used by the manual endpoint)."""
        if not settings.macro_btc_enabled:
            return {"status": "disabled"}

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                btc = await self._day_change(client, "BTCUSDT")
                gold = await self._day_change(client, "PAXGUSDT")
            except Exception as e:
                logger.warning(f"macro_btc price fetch failed: {e}")
                return {"status": "error", "error": str(e)}

            # 1. Manage open paper position first
            if self.state.get("position"):
                exit_summary = await self._manage_position(btc["last"], notify=notify)
                if exit_summary:
                    return exit_summary
                return {"status": "holding", "position": self.state["position"],
                        "btc": btc, "gold": gold}

            # 2. Trigger check — one trigger per UTC day
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            triggered = (btc["pct"] >= settings.macro_btc_trigger_pct
                         and gold["pct"] >= settings.macro_btc_gold_confirm_pct)
            if not (triggered or force_trigger):
                return {"status": "no_trigger", "btc": btc, "gold": gold}
            if self.state.get("last_trigger_date") == today and not force_trigger:
                return {"status": "already_triggered_today", "btc": btc, "gold": gold}

            # 3. Classify cause
            headlines = await self._fetch_headlines(client)

        classification = await self._classify(btc["pct"], gold["pct"], headlines)
        self.state["last_trigger_date"] = today

        cause = (classification or {}).get("cause", "unclassified")
        confidence = float((classification or {}).get("confidence", 0.0))
        entry_taken = (cause == "monetary_liquidity"
                       and confidence >= settings.macro_btc_min_confidence)

        record = {
            "event": "TRIGGER", "date": today, "forced": force_trigger,
            "btc_pct": round(btc["pct"], 2), "gold_pct": round(gold["pct"], 2),
            "btc_price": btc["last"], "headlines": headlines,
            "classification": classification, "entry_taken": entry_taken,
        }
        self._journal(record)

        if entry_taken:
            notional = settings.macro_btc_paper_capital * settings.macro_btc_leverage
            self.state["position"] = {
                "entry_price": btc["last"], "entry_ts": datetime.now(timezone.utc).isoformat(),
                "notional": notional, "peak_price": btc["last"],
                "cause": cause, "confidence": confidence,
            }
        self._save_state()

        if notify:
            from .integrations import send_telegram, _esc
            emoji = "🖨️" if entry_taken else "👀"
            action = (f"PAPER LONG ${self.state['position']['notional']:.0f} notional "
                      f"({settings.macro_btc_leverage:.0f}x) @ ${btc['last']:,.0f}"
                      if entry_taken else "geen entry (oorzaak-filter)")
            evidence = _esc((classification or {}).get("headline_evidence", ""))
            await send_telegram(
                f"{emoji} <b>Macro-BTC trigger</b>\n"
                f"BTC {btc['pct']:+.1f}% | goud {gold['pct']:+.1f}%\n"
                f"Oorzaak: <b>{_esc(cause)}</b> ({confidence:.0%})\n"
                f"→ {action}\n"
                f"<i>{evidence}</i>"
            )

        return {"status": "triggered", **record}

    async def _manage_position(self, price: float, notify: bool = True) -> Optional[dict]:
        """Apply exit rules to the open paper position. Returns exit summary or None."""
        pos = self.state["position"]
        pos["peak_price"] = max(pos["peak_price"], price)
        entry = pos["entry_price"]
        age_h = (datetime.now(timezone.utc)
                 - datetime.fromisoformat(pos["entry_ts"])).total_seconds() / 3600

        reason = None
        if price <= entry * (1 - settings.macro_btc_hard_stop_pct / 100):
            reason = "hard_stop"
        elif price <= pos["peak_price"] * (1 - settings.macro_btc_trail_pct / 100):
            reason = "trailing_stop"
        elif age_h >= settings.macro_btc_max_hold_hours:
            reason = "max_hold"

        if not reason:
            self._save_state()
            return None

        move_pct = (price / entry - 1) * 100
        gross = pos["notional"] * (price / entry - 1)
        fees = pos["notional"] * 0.0005 * 2                    # taker in + out
        funding = pos["notional"] * 0.0001 * (age_h / 8)       # ~0.01% per 8h
        net = gross - fees - funding

        record = {
            "event": "EXIT", "reason": reason,
            "entry_price": entry, "exit_price": price, "peak_price": pos["peak_price"],
            "hold_hours": round(age_h, 1), "move_pct": round(move_pct, 2),
            "gross_pnl": round(gross, 2), "fees": round(fees + funding, 2),
            "net_pnl": round(net, 2), "cause": pos.get("cause"),
        }
        self._journal(record)
        self.state["position"] = None
        self._save_state()

        if notify:
            from .integrations import send_telegram
            emoji = "✅" if net > 0 else "❌"
            await send_telegram(
                f"{emoji} <b>Macro-BTC paper exit</b> ({reason})\n"
                f"${entry:,.0f} → ${price:,.0f} ({move_pct:+.1f}%) in {age_h:.0f}u\n"
                f"Net P&amp;L: <b>${net:+.2f}</b> op ${settings.macro_btc_paper_capital:.0f} paper capital"
            )
        return {"status": "exited", **record}


macro_btc = MacroBTCPaperTrader()
