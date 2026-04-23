"""
AI Trading Agent — Claude-powered hedge fund manager for Polymarket.

Every 5 minutes, gathers market intelligence, asks Claude for decisions,
and executes penny trades. Full thinking journal for audit trail.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from loguru import logger

from .config import settings
from .auto_seller import auto_seller
from .trade_journal import journal
from .polymarket_client import PolymarketClient
from .integrations import post_tweet, format_thinking_tweet, log_trade_to_sheets, log_thinking_to_sheets, send_telegram, format_thinking_telegram, format_trade_telegram, log_trade_to_airtable
from .leaderboard import tracker
from .auditor_data import get_auditor, is_earnings_market, analyze_wallet_auditor_pattern
from .intel_feeds import fetch_all_intel
from .ai_prompts import (
    SYSTEM_PROMPT,
    build_market_briefing,
    build_alert_summary,
    build_portfolio_summary,
    build_thinking_history,
    build_smart_money_summary,
    build_thesis_board,
    build_leaderboard_summary,
    build_near_resolution_summary,
    build_stock_market_summary,
    build_inconsistency_summary,
)

THINKING_LOG_PATH = Path(__file__).parent.parent / "data" / "agent_thinking.jsonl"
THESES_PATH = Path(__file__).parent.parent / "data" / "agent_theses.json"

# Topic clusters for inconsistency detection
# Each entry: (topic_id, keywords_to_match)
TOPIC_CLUSTERS = [
    ("iran",        ["iran", "tehran", "khamenei", "irgc", "persian"]),
    ("ceasefire",   ["ceasefire", "cease-fire", "peace deal", "truce"]),
    ("fed",         ["fed rate", "federal reserve", "fomc", "basis point", "bps cut", "rate cut"]),
    ("bitcoin",     ["bitcoin", "btc"]),
    ("ethereum",    ["ethereum", "eth "]),
    ("oil",         ["oil", "crude", "wti", "brent", "opec"]),
    ("trump",       ["trump"]),
    ("ukraine",     ["ukraine", "zelensky", "russia", "nato"]),
    ("china_taiwan",["taiwan", "china invade", "pla"]),
    ("sp500",       ["s&p", "sp500", "nasdaq"]),
]

STOCK_KEYWORDS = [
    "s&p", "sp500", "s&p 500", "nasdaq", "dow jones", "djia",
    "apple", "aapl", "google", "goog", "amazon", "amzn", "tesla", "tsla",
    "microsoft", "msft", "nvidia", "nvda", "meta", "netflix", "nflx",
    "stock", "earnings", "revenue", "market cap", "ipo",
    "fed rate", "interest rate", "cpi", "inflation", "gdp",
    "oil price", "gold price", "crude oil",
]


def _find_near_resolution(markets: list) -> list:
    """Filter markets ending within 48h with a dominant outcome."""
    now = datetime.utcnow()
    results = []

    for m in markets:
        end_str = m.get("endDate") or ""
        if not end_str:
            continue
        try:
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue

        hours_left = (end - now).total_seconds() / 3600
        if hours_left <= 0 or hours_left > 48:
            continue

        prices_str = m.get("outcomePrices", "")
        try:
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            if not prices:
                continue
            yes_price = float(prices[0])
        except (json.JSONDecodeError, ValueError, IndexError):
            continue

        # At least one side must be 90%+
        dominant = max(yes_price, 1 - yes_price)
        if dominant < 0.90:
            continue

        m["_yes_price"] = yes_price
        m["_hours_left"] = hours_left
        results.append(m)

    # Sort by hours left
    results.sort(key=lambda x: x["_hours_left"])
    return results[:10]


def _find_stock_markets(markets: list) -> list:
    """Filter markets related to stocks/finance."""
    results = []
    for m in markets:
        text = (m.get("question", "") + " " + m.get("slug", "")).lower()
        if any(kw in text for kw in STOCK_KEYWORDS):
            results.append(m)
    return results[:10]


def _find_market_inconsistencies(markets: list) -> list:
    """Detect pricing inconsistencies between logically related markets.

    Returns list of dicts describing each inconsistency found.
    Types detected:
      - TEMPORAL: P(event by date A) > P(event by date B) where A < B — impossible
      - HIERARCHY: P(X > threshold_high) > P(X > threshold_low) — impossible
    """
    from datetime import datetime as dt
    import re

    inconsistencies = []

    # Group markets by topic
    topic_markets: dict = {}
    for m in markets:
        text = (m.get("question", "") + " " + m.get("slug", "")).lower()
        for topic_id, keywords in TOPIC_CLUSTERS:
            if any(kw in text for kw in keywords):
                topic_markets.setdefault(topic_id, []).append(m)
                break  # one topic per market

    for topic_id, group in topic_markets.items():
        if len(group) < 2:
            continue

        # Parse yes_price and end_date for each market in group
        parsed = []
        for m in group:
            prices_raw = m.get("outcomePrices", "")
            try:
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                yes_price = float(prices[0]) if prices else None
            except Exception:
                yes_price = None

            end_str = m.get("endDate", "") or ""
            try:
                end_dt = dt.fromisoformat(end_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                end_dt = None

            if yes_price is not None:
                parsed.append({
                    "question": m.get("question", "")[:80],
                    "yes_price": yes_price,
                    "end_dt": end_dt,
                    "market_id": m.get("conditionId") or m.get("id", ""),
                    "volume": float(m.get("volume24hr") or m.get("volume") or 0),
                })

        # TEMPORAL check: for same-topic markets, P(by earlier date) <= P(by later date)
        # (assuming they're asking the same question with different deadlines)
        # Only check pairs where questions are very similar
        for i in range(len(parsed)):
            for j in range(i + 1, len(parsed)):
                a, b = parsed[i], parsed[j]
                if not a["end_dt"] or not b["end_dt"]:
                    continue
                # Sort so 'early' has the earlier end date
                early, late = (a, b) if a["end_dt"] < b["end_dt"] else (b, a)

                # Temporal inconsistency: P(earlier) > P(later) by more than 5% (noise threshold)
                if early["yes_price"] > late["yes_price"] + 0.05:
                    gap = early["yes_price"] - late["yes_price"]
                    inconsistencies.append({
                        "type": "TEMPORAL",
                        "topic": topic_id,
                        "description": (
                            f"{early['question'][:60]} = {early['yes_price']:.0%} YES "
                            f"(ends {early['end_dt'].strftime('%b %d')}) "
                            f"BUT {late['question'][:60]} = {late['yes_price']:.0%} YES "
                            f"(ends {late['end_dt'].strftime('%b %d')}) — "
                            f"earlier deadline priced HIGHER by {gap:.0%}"
                        ),
                        "edge": gap,
                        "early_id": early["market_id"],
                        "late_id": late["market_id"],
                    })

        # HIERARCHY check: numeric thresholds in same topic (e.g. BTC >60k vs >70k)
        threshold_pattern = re.compile(r"[\$]?(\d[\d,\.]+)(?:k\b|thousand|million)?")
        for i in range(len(parsed)):
            for j in range(i + 1, len(parsed)):
                a, b = parsed[i], parsed[j]
                # Try to extract numeric thresholds from questions (single group → strings)
                nums_a = [float(n.replace(",", "")) for n in threshold_pattern.findall(a["question"].lower())[0:1]]
                nums_b = [float(n.replace(",", "")) for n in threshold_pattern.findall(b["question"].lower())[0:1]]
                if not nums_a or not nums_b or nums_a[0] == nums_b[0]:
                    continue
                # low_threshold market should have higher yes_price
                low, high = (a, b) if nums_a[0] < nums_b[0] else (b, a)
                if low["yes_price"] < high["yes_price"] - 0.05:
                    gap = high["yes_price"] - low["yes_price"]
                    inconsistencies.append({
                        "type": "HIERARCHY",
                        "topic": topic_id,
                        "description": (
                            f"'{low['question'][:55]}' = {low['yes_price']:.0%} YES "
                            f"but '{high['question'][:55]}' = {high['yes_price']:.0%} YES — "
                            f"higher threshold priced more likely by {gap:.0%}"
                        ),
                        "edge": gap,
                    })

    # Sort by largest edge first, cap at 5
    inconsistencies.sort(key=lambda x: x["edge"], reverse=True)
    return inconsistencies[:5]


async def _fetch_stock_prices() -> dict:
    """Fetch key stock indices/prices from a free API."""
    import httpx
    symbols = {
        "SPY": "S&P 500 ETF",
        "QQQ": "Nasdaq 100 ETF",
        "GLD": "Gold ETF",
        "USO": "Oil ETF",
    }
    prices = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for symbol in symbols:
                try:
                    r = await client.get(
                        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                        params={"interval": "1d", "range": "2d"},
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    if r.status_code == 200:
                        data = r.json()
                        meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                        price = meta.get("regularMarketPrice", 0)
                        prev = meta.get("previousClose") or meta.get("chartPreviousClose", 0)
                        change_pct = ((price - prev) / prev * 100) if prev else 0
                        prices[symbol] = {"price": price, "change_pct": change_pct}
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"Stock price fetch failed: {e}")

    return prices

# Try to import openai (used for OpenRouter)
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("openai SDK not installed. AI agent disabled.")


class AITradingAgent:
    """AI-powered trading agent (via OpenRouter)."""

    def __init__(self):
        self.client: Optional[OpenAI] = None
        self._recent_alerts: list = []  # Fed by main.py after each scan
        self._recent_smart_money: list = []
        self._thinking_history: List[Dict] = []
        self.theses: List[Dict] = []
        self._live_positions: List[Dict] = []  # Synced from Polymarket each cycle
        self._load_recent_thinking()
        self._load_theses()

        api_key = settings.openrouter_api_key or settings.anthropic_api_key
        if HAS_OPENAI and api_key:
            base_url = "https://openrouter.ai/api/v1" if settings.openrouter_api_key else "https://api.anthropic.com/v1"
            self.client = OpenAI(api_key=api_key, base_url=base_url)
            logger.info(f"AI Trading Agent initialized (model: {settings.agent_model})")
        elif HAS_OPENAI:
            logger.warning("No API key set — AI agent won't trade")

    def _load_recent_thinking(self):
        """Load last few thinking entries for continuity."""
        if not THINKING_LOG_PATH.exists():
            return
        entries = []
        for line in THINKING_LOG_PATH.read_text().strip().split("\n"):
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        self._thinking_history = entries[-5:]  # Keep last 5

    def _load_theses(self):
        """Load thesis board from disk."""
        if not THESES_PATH.exists():
            return
        try:
            self.theses = json.loads(THESES_PATH.read_text())
        except (json.JSONDecodeError, Exception):
            self.theses = []

    def _save_theses(self):
        """Persist thesis board to disk."""
        try:
            THESES_PATH.parent.mkdir(parents=True, exist_ok=True)
            THESES_PATH.write_text(json.dumps(self.theses, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save theses: {e}")

    def _apply_thesis_updates(self, updates: List[Dict]):
        """Apply CREATE/UPDATE/CLOSE operations to the thesis board."""
        if not updates:
            return
        now = datetime.utcnow().isoformat()
        changed = False

        for u in updates:
            action = u.get("action", "").upper()
            tid = u.get("id", "")

            if action == "CREATE" and tid:
                # Don't duplicate
                if any(t["id"] == tid for t in self.theses):
                    continue
                self.theses.append({
                    "id": tid,
                    "title": u.get("title", ""),
                    "market_id": u.get("market_id", ""),
                    "conviction": u.get("conviction", "medium"),
                    "status": "active",
                    "created": now,
                    "updated": now,
                    "history": [{"timestamp": now, "note": u.get("note", ""), "conviction": u.get("conviction", "medium")}],
                })
                logger.info(f"📋 Thesis created: [{tid}] {u.get('title', '')[:50]}")
                changed = True

            elif action == "UPDATE" and tid:
                for t in self.theses:
                    if t["id"] == tid and t["status"] == "active":
                        if u.get("conviction"):
                            t["conviction"] = u["conviction"]
                        t["updated"] = now
                        t["history"].append({
                            "timestamp": now,
                            "note": u.get("note", ""),
                            "conviction": u.get("conviction", t["conviction"]),
                        })
                        logger.info(f"📋 Thesis updated: [{tid}] {u.get('note', '')[:50]}")
                        changed = True
                        break

            elif action == "CLOSE" and tid:
                for t in self.theses:
                    if t["id"] == tid and t["status"] == "active":
                        t["status"] = "closed"
                        t["updated"] = now
                        t["history"].append({
                            "timestamp": now,
                            "note": u.get("note", "Closed"),
                            "conviction": "closed",
                        })
                        logger.info(f"📋 Thesis closed: [{tid}]")
                        changed = True
                        break

        if changed:
            self._save_theses()

    def feed_alerts(self, alerts: list):
        """Called by main.py after scan with new alerts."""
        self._recent_alerts = alerts

    def feed_smart_money(self, trades: list):
        """Called by main.py with new smart money trades."""
        self._recent_smart_money = trades

    async def _log_exit_for_resolved(self, position: Dict):
        """Detect the resolution outcome for a position that vanished from live data,
        compute P&L, and append an EXIT entry to the journal so win/loss stats are correct.
        Best-effort: if we can't determine the outcome (market not closed yet in Gamma,
        slug mismatch, etc.), we still log an EXIT with pnl_usd=None so the position
        stops re-appearing in get_open_positions()."""
        token_id = position.get("token_id", "")
        shares = float(position.get("shares", 0) or 0)
        amount_usd = float(position.get("amount_usd", 0) or 0)
        entry_price = float(position.get("price", 0) or 0)
        if entry_price > 1:
            # stored in cents (0-100); normalise to 0-1 for downstream math
            entry_price = entry_price / 100

        resolved_price = None
        resolved_status = "unknown"
        market_slug = position.get("market_slug", "")

        if token_id:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as hc:
                    r = await hc.get(
                        f"{settings.gamma_api_url}/markets",
                        params={"clob_token_ids": token_id},
                    )
                    r.raise_for_status()
                    markets = r.json() or []
                if markets:
                    m = markets[0]
                    market_slug = market_slug or m.get("slug", "")
                    if m.get("closed") or m.get("umaResolutionStatus") == "resolved":
                        clob_ids = m.get("clobTokenIds", "[]")
                        prices = m.get("outcomePrices", "[]")
                        try:
                            clob_ids = json.loads(clob_ids) if isinstance(clob_ids, str) else clob_ids
                            prices = json.loads(prices) if isinstance(prices, str) else prices
                        except json.JSONDecodeError:
                            clob_ids, prices = [], []
                        for tid, p in zip(clob_ids, prices):
                            if str(tid) == str(token_id):
                                resolved_price = float(p)
                                resolved_status = "won" if resolved_price >= 0.5 else "lost"
                                break
            except Exception as e:
                logger.debug(f"Gamma lookup failed for token {token_id[:16]}: {e}")

        # Compute P&L from shares × resolved_price
        if resolved_price is not None:
            payout = shares * resolved_price
            pnl_usd = payout - amount_usd
            pnl_pct = (pnl_usd / amount_usd * 100) if amount_usd else 0
        else:
            pnl_usd = None
            pnl_pct = None

        journal.log_entry(
            strategy=position.get("strategy", "AI-AGENT"),
            action="EXIT",
            market_question=position.get("market_question", ""),
            market_slug=market_slug,
            token_id=token_id,
            side=position.get("side", "SELL"),
            price=resolved_price if resolved_price is not None else 0,
            shares=shares,
            amount_usd=amount_usd,
            reason="auto-resolved (position disappeared from live data)",
            order_id=None,
            entry_price=entry_price,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            exit_reason=f"market resolution ({resolved_status})",
        )

        if pnl_usd is not None:
            emoji = "🎉" if pnl_usd > 0 else "💀"
            try:
                await send_telegram(
                    f"{emoji} <b>Position resolved</b> — {resolved_status.upper()}\n"
                    f"Market: <i>{position.get('market_question','?')[:80]}</i>\n"
                    f"Entry: ${amount_usd:.2f} @ {entry_price*100:.1f}c → Exit @ {resolved_price*100:.1f}c\n"
                    f"P&amp;L: <b>{'+' if pnl_usd>=0 else ''}${pnl_usd:.2f}</b> ({pnl_pct:+.1f}%)"
                )
            except Exception:
                pass

    async def _sync_live_positions(self) -> List[Dict]:
        """Reconcile journal open positions against live Polymarket holdings.

        Dollar amounts come from the journal (we know exactly what was spent).
        The live API is used only to detect which positions have resolved/closed.
        This avoids unreliable Data API field scaling (size = shares, not USD).
        """
        journal_positions = journal.get_open_positions()

        if not journal_positions:
            self._live_positions = []
            return []

        # Collect live token IDs from CLOB client (authoritative for what exists)
        live_token_ids: set = set()
        try:
            if auto_seller.is_ready():
                clob_pos = auto_seller.client.get_positions()
                for p in (clob_pos or []):
                    tid = p.get("asset_id") or p.get("token_id") or ""
                    if tid:
                        live_token_ids.add(tid)
        except Exception as e:
            logger.debug(f"CLOB positions fetch failed: {e}")

        # Collect live market questions from Data API (for question-based matching)
        live_market_questions: set = set()
        try:
            wallet = settings.poly_wallet_address
            if wallet:
                async with PolymarketClient() as client:
                    raw = await client.get_user_positions(wallet)
                for p in (raw or []):
                    q = (p.get("title") or p.get("question") or p.get("market") or "").strip().lower()
                    if q:
                        live_market_questions.add(q)
                    # Also store token IDs from Data API
                    tid = p.get("asset") or p.get("tokenId") or p.get("token_id") or ""
                    if tid:
                        live_token_ids.add(tid)
        except Exception as e:
            logger.debug(f"Data API positions fetch failed: {e}")

        # If we couldn't reach any live API, keep all journal positions (fail safe)
        if not live_token_ids and not live_market_questions:
            logger.debug("No live position data — keeping all journal positions as-is")
            self._live_positions = journal_positions
            return journal_positions

        # Cross-reference: keep journal positions that are still live
        reconciled = []
        for jp in journal_positions:
            token_id = jp.get("token_id", "")
            market_q = jp.get("market_question", "").strip().lower()

            token_match = bool(token_id and token_id in live_token_ids)
            question_match = any(
                market_q in q or q in market_q
                for q in live_market_questions
            ) if live_market_questions and market_q else False

            if token_match or question_match:
                reconciled.append(jp)
            else:
                logger.info(f"Position not found in live data, treating as resolved: {jp.get('market_question', '?')[:50]}")
                try:
                    await self._log_exit_for_resolved(jp)
                except Exception as e:
                    logger.warning(f"Could not log EXIT for resolved position {token_id[:16]}: {e}")

        self._live_positions = reconciled
        logger.info(f"Live positions: {len(reconciled)}/{len(journal_positions)} journal positions still active (exposure: ${sum(p.get('amount_usd',0) for p in reconciled):.2f})")
        return reconciled

    async def run_cycle(self):
        """Main cycle — gather data, ask Claude, execute."""
        if not settings.agent_enabled or not self.client:
            return

        try:
            # 0. Sync live positions from Polymarket (source of truth)
            await self._sync_live_positions()

            # 1. Gather context
            context = await self._gather_context()

            # 2. Ask Claude
            response = await self._ask_claude(context)
            if not response:
                return

            # 3. Parse response
            decision = self._parse_response(response)
            if not decision:
                return

            # 4. Log thinking
            self._log_thinking(decision)

            # 4b. Send to Telegram — enrich with portfolio snapshot first
            try:
                live_positions = self._live_positions or []
                live_exposure = sum(p.get("amount_usd", 0) for p in live_positions)
                balance = auto_seller.get_usdc_balance() or 0
                decision["_portfolio"] = {
                    "balance": balance,
                    "exposure": live_exposure,
                    "positions": live_positions,
                    "max_exposure": settings.agent_max_total_exposure,
                    "max_positions": settings.agent_max_positions,
                }
                for tg_msg in format_thinking_telegram(decision):
                    await send_telegram(tg_msg)
            except Exception as e:
                logger.debug(f"Telegram skipped: {e}")

            # 4c. Post to Twitter (disabled)
            try:
                tweet_text = format_thinking_tweet(decision)
                post_tweet(tweet_text)
            except Exception as e:
                logger.debug(f"Tweet skipped: {e}")

            # 4c. Log to Google Sheets
            try:
                decision["_active_theses"] = [t for t in self.theses if t.get("status") == "active"]
                log_thinking_to_sheets(decision)
            except Exception as e:
                logger.debug(f"Sheets thinking log skipped: {e}")

            # 5. Update thesis board
            if decision.get("thesis_updates"):
                self._apply_thesis_updates(decision["thesis_updates"])

            # 6. Execute trades
            if decision.get("trades"):
                await self._execute_trades(decision["trades"])

            # Clear consumed alerts
            self._recent_alerts = []
            self._recent_smart_money = []

        except Exception as e:
            logger.error(f"AI agent cycle error: {e}")

    async def _gather_context(self) -> str:
        """Build the full context prompt for Claude."""
        parts = []

        # Current time + key deadlines
        now = datetime.utcnow()
        parts.append(f"Current time: {now.strftime('%Y-%m-%d %H:%M UTC')}")
        # Pre-calculate time to common deadlines so the LLM doesn't hallucinate math
        eod = now.replace(hour=23, minute=59, second=0)
        hours_to_eod = (eod - now).total_seconds() / 3600
        parts.append(f"Time until end of today (23:59 UTC): {hours_to_eod:.1f} hours")

        # Portfolio state — use reconciled journal positions (live-cross-referenced)
        # Exposure = sum of amount_usd from journal entries (what we actually spent)
        balance = auto_seller.get_usdc_balance() or 0
        live_positions = self._live_positions
        live_exposure = sum(p.get("amount_usd", 0) for p in live_positions)
        parts.append(build_portfolio_summary(live_positions, balance, live_exposure, live=True))

        # Insider alerts
        parts.append(build_alert_summary(self._recent_alerts))

        # Auditor pattern analysis on insider alerts
        auditor_notes = self._check_auditor_patterns()
        if auditor_notes:
            parts.append(auditor_notes)

        # Smart money
        parts.append(build_smart_money_summary(self._recent_smart_money))

        # Market data + near-resolution + stock markets
        async with PolymarketClient() as client:
            markets = await client.get_markets(limit=50, order="volume24hr")
            parts.append(build_market_briefing(markets[:20]))

            # Near-resolution markets (ending within 48h, one side 90%+)
            near_resolution = _find_near_resolution(markets)
            parts.append(build_near_resolution_summary(near_resolution))

            # Stock-related markets
            stock_markets = _find_stock_markets(markets)
            stock_prices = await _fetch_stock_prices()
            parts.append(build_stock_market_summary(stock_markets, stock_prices))

            # Cross-market inconsistencies (temporal + hierarchy arb)
            inconsistencies = _find_market_inconsistencies(markets)
            parts.append(build_inconsistency_summary(inconsistencies))

        # Leaderboard (top traders) — annotate with cached specializations
        try:
            leaders = await tracker.fetch_leaderboard(order_by="pnl", limit=10)
            for leader in leaders:
                addr = leader.get("address", "").lower()
                spec = tracker.get_wallet_specialization(addr)
                if spec:
                    leader["specialization"] = spec
            parts.append(build_leaderboard_summary(leaders))
        except Exception as e:
            logger.debug(f"Leaderboard fetch failed: {e}")

        # External intel (Twitter + RSS)
        try:
            intel = await fetch_all_intel()
            parts.append(intel)
        except Exception as e:
            logger.debug(f"Intel fetch failed: {e}")

        # Thesis board
        parts.append(build_thesis_board(self.theses))

        # Thinking history
        parts.append(build_thinking_history(self._thinking_history))

        return "\n\n".join(parts)

    async def _ask_claude(self, context: str) -> Optional[str]:
        """Call AI model via OpenRouter (or Anthropic fallback)."""
        try:
            response = self.client.chat.completions.create(
                model=settings.agent_model,
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"AI API error: {e}")
            return None

    def _parse_response(self, response: str) -> Optional[Dict]:
        """Parse Claude's JSON response."""
        import re as _re
        text = response.strip()

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        text = _re.sub(r"^```[a-z]*\n?", "", text)
        text = _re.sub(r"\n?```$", "", text)
        text = text.strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Extract outermost {...} object
        try:
            start = text.index("{")
            # Find matching closing brace
            depth = 0
            end = start
            for i, ch in enumerate(text[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse agent response: {response[:300]}\nError: {e}")
            return None

    def _log_thinking(self, decision: Dict):
        """Append thinking entry to the journal."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "thinking": decision.get("thinking", ""),
            "trades": decision.get("trades", []),
            "watchlist_notes": decision.get("watchlist_notes", ""),
            "risk_assessment": decision.get("risk_assessment", ""),
        }

        try:
            THINKING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(THINKING_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write thinking log: {e}")

        # Keep in memory for continuity
        self._thinking_history.append(entry)
        self._thinking_history = self._thinking_history[-5:]

        thinking_preview = decision.get("thinking", "")[:100]
        trade_count = len(decision.get("trades", []))
        logger.info(f"🧠 Agent thinks: {thinking_preview}... ({trade_count} trades)")

    async def _execute_trades(self, trades: List[Dict]):
        """Execute the agent's trade decisions."""
        for trade in trades:
            try:
                action = trade.get("action", "").upper()
                if action != "BUY":
                    continue  # Only BUY for now

                market_id = trade.get("market_id", "")
                market_question = trade.get("market_question", "Unknown")
                outcome = trade.get("outcome", "Yes")
                amount_usd = float(trade.get("amount_usd", 0))
                confidence = float(trade.get("confidence", 0))
                thesis = trade.get("thesis", "")

                # Enforce hard limits
                amount_usd = min(amount_usd, settings.agent_max_per_trade)
                # Polymarket minimum order is $1.00 — bump up if below
                if amount_usd < 1.05:
                    amount_usd = 1.05
                if amount_usd > settings.agent_max_per_trade:
                    continue

                # Check exposure: use amount_usd from journal entries (what we actually spent)
                live_exposure = sum(p.get("amount_usd", 0) for p in self._live_positions)
                if live_exposure + amount_usd > settings.agent_max_total_exposure:
                    reason = f"exposure limit (${live_exposure + amount_usd:.2f} > ${settings.agent_max_total_exposure:.2f})"
                    logger.info(f"Agent trade skipped: {reason}")
                    await send_telegram(f"⏭️ Trade skipped: {market_question[:50]}\nReason: {reason}")
                    continue

                # Check position count using LIVE positions
                if len(self._live_positions) >= settings.agent_max_positions:
                    logger.info("Agent trade skipped: max positions reached")
                    await send_telegram(f"⏭️ Trade skipped: {market_question[:50]}\nReason: max {settings.agent_max_positions} positions already open")
                    continue

                # Check duplicate against live positions (by market question, case-insensitive)
                mq_lower = market_question.lower()
                already_held = any(
                    mq_lower in p.get("market_question", "").lower() or
                    p.get("market_question", "").lower() in mq_lower
                    for p in self._live_positions
                )
                if already_held:
                    logger.info(f"Agent trade skipped: already have live position in {market_question[:30]}")
                    continue  # No Telegram — not interesting

                # Get token_id for the market
                logger.info(f"🤖 Attempting trade: {action} ${amount_usd:.2f} on {market_question[:40]} (ID: {market_id})")
                token_id = await self._resolve_token_id(market_id, outcome)
                if not token_id:
                    logger.warning(f"Could not resolve token for {market_question[:30]} (ID: {market_id})")
                    await send_telegram(f"❌ Trade failed: {market_question[:50]}\nReason: could not resolve token ID for market {market_id[:20]}")
                    continue

                # Execute real penny trade
                result = await auto_seller.execute_buy(
                    token_id=token_id,
                    amount_usd=amount_usd,
                    max_price=None,
                )

                if result.success:
                    journal.log_entry(
                        strategy="AI-AGENT",
                        action="ENTER",
                        market_question=market_question,
                        market_slug="",
                        token_id=token_id,
                        side="BUY",
                        price=result.price,
                        shares=result.shares,
                        amount_usd=amount_usd,
                        reason=f"[{confidence:.0%}] {thesis}",
                        order_id=result.order_id,
                    )
                    logger.info(f"🤖 AI TRADE: ${amount_usd:.2f} on {market_question[:40]} ({thesis[:30]})")

                    # Notify via Telegram
                    try:
                        tg_msg = format_trade_telegram(
                            "AI-AGENT", "BUY", market_question,
                            outcome, result.price, amount_usd,
                            thesis, result.order_id or "",
                        )
                        await send_telegram(tg_msg)
                    except Exception:
                        pass

                    # Log to Airtable (primary trade tracker)
                    log_trade_to_airtable(
                        action="BUY",
                        market_question=market_question,
                        outcome=outcome,
                        price=result.price,
                        shares=result.shares,
                        amount_usd=amount_usd,
                        confidence=confidence,
                        reason=thesis,
                        order_id=result.order_id or "",
                    )

                    # Log to Google Sheets + local CSV backup
                    log_trade_to_sheets(
                        strategy="AI-AGENT",
                        action="BUY",
                        market_question=market_question,
                        outcome=outcome,
                        price=result.price,
                        shares=result.shares,
                        amount_usd=amount_usd,
                        confidence=confidence,
                        reason=thesis,
                        order_id=result.order_id or "",
                    )
                else:
                    logger.warning(f"AI trade failed: {result.error}")
                    await send_telegram(f"❌ Trade failed: {market_question[:50]}\nReason: {result.error}")

            except Exception as e:
                logger.error(f"AI trade execution error: {e}")

    def _check_auditor_patterns(self) -> Optional[str]:
        """Check insider alerts for the KPMG-style auditor clustering pattern."""
        if not self._recent_alerts:
            return None

        lines = []
        for alert in self._recent_alerts:
            st = alert.suspicious_trade if hasattr(alert, "suspicious_trade") else alert
            trade = st.trade if hasattr(st, "trade") else st
            question = getattr(trade, "market_question", "")

            if not is_earnings_market(question):
                continue

            auditor = get_auditor(question)
            if auditor:
                notional = getattr(trade, "notional_usd", 0)
                wallet_addr = getattr(st.wallet, "address", "?")[:12] if hasattr(st, "wallet") else "?"
                lines.append(
                    f"- EARNINGS ALERT on {auditor}-audited company: {question[:60]}\n"
                    f"  Wallet: {wallet_addr}... | ${notional:,.0f}\n"
                    f"  CHECK: Does this wallet also bet big on other {auditor} clients?"
                )

        if not lines:
            return None

        return "## Auditor Pattern Watch (KPMG-style)\n" + "\n".join(lines)

    async def _resolve_token_id(self, market_id: str, outcome: str) -> Optional[str]:
        """Resolve a market_id + outcome to a CLOB token_id."""
        import json as _json

        async with PolymarketClient() as client:
            market = await client.get_market(market_id)

            # If direct lookup fails, search by slug or conditionId in top markets
            if not market:
                logger.info(f"Direct lookup failed for '{market_id[:30]}...', searching top markets...")
                # Normalise: strip special chars for slug comparison
                import unicodedata
                def _norm(s: str) -> str:
                    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip("-")
                market_id_norm = _norm(market_id)

                markets = await client.get_markets(limit=500, order="volume24hr")
                for m in markets:
                    full_id = m.get("conditionId") or m.get("id") or ""
                    slug = m.get("slug") or ""
                    if (
                        full_id == market_id
                        or full_id.startswith(market_id)
                        or market_id.startswith(full_id)
                        or _norm(slug) == market_id_norm
                        or market_id_norm in _norm(slug)
                        or _norm(slug) in market_id_norm
                    ):
                        market = m
                        logger.info(f"Matched to: {m.get('question', '?')[:40]}")
                        break

            if not market:
                logger.warning(f"Could not find market for ID: {market_id}")
                return None

            # Parse clobTokenIds — can be JSON string or list
            tokens_raw = market.get("clobTokenIds", []) or market.get("tokens", [])
            if isinstance(tokens_raw, str):
                try:
                    tokens = _json.loads(tokens_raw)
                except _json.JSONDecodeError:
                    tokens = []
            else:
                tokens = tokens_raw

            if not tokens:
                return None

            # Handle exactly 2 tokens (binary market)
            idx = 0 if outcome in ("Yes", "YES", "yes") else 1

            if isinstance(tokens[0], dict):
                for t in tokens:
                    if t.get("outcome", "").lower() == outcome.lower():
                        return t.get("token_id")
                return tokens[0].get("token_id") if tokens else None
            else:
                # tokens is a list of token ID strings
                return tokens[idx] if idx < len(tokens) else tokens[0] if tokens else None

    def get_status(self) -> Dict:
        """Return agent status for the API."""
        positions = journal.get_open_positions()
        performance = journal.get_performance()
        balance = auto_seller.get_usdc_balance()
        last_thinking = self._thinking_history[-1] if self._thinking_history else None

        return {
            "enabled": settings.agent_enabled,
            "has_api_key": bool(self.client),
            "model": settings.agent_model,
            "limits": {
                "max_per_trade": settings.agent_max_per_trade,
                "max_total_exposure": settings.agent_max_total_exposure,
                "max_positions": settings.agent_max_positions,
            },
            "portfolio": {
                "usdc_balance": balance,
                "open_positions": len(positions),
                "total_exposure": journal.get_total_exposure(),
                "positions": positions,
            },
            "performance": performance,
            "last_thinking": last_thinking,
            "theses": {
                "active": [t for t in self.theses if t.get("status") == "active"],
                "closed_count": sum(1 for t in self.theses if t.get("status") == "closed"),
            },
        }

    def get_thinking_history(self, limit: int = 50) -> List[Dict]:
        """Return full thinking journal."""
        if not THINKING_LOG_PATH.exists():
            return []
        entries = []
        for line in THINKING_LOG_PATH.read_text().strip().split("\n"):
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        entries.reverse()
        return entries[:limit]


# Singleton
ai_agent = AITradingAgent()
