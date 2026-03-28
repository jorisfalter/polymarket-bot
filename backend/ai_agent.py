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
from .ai_prompts import (
    SYSTEM_PROMPT,
    build_market_briefing,
    build_alert_summary,
    build_portfolio_summary,
    build_thinking_history,
    build_smart_money_summary,
    build_thesis_board,
)

THINKING_LOG_PATH = Path(__file__).parent.parent / "data" / "agent_thinking.jsonl"
THESES_PATH = Path(__file__).parent.parent / "data" / "agent_theses.json"

# Try to import anthropic
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    logger.warning("anthropic SDK not installed. AI agent disabled.")


class AITradingAgent:
    """Claude-powered trading agent."""

    def __init__(self):
        self.client: Optional[anthropic.Anthropic] = None
        self._recent_alerts: list = []  # Fed by main.py after each scan
        self._recent_smart_money: list = []
        self._thinking_history: List[Dict] = []
        self.theses: List[Dict] = []
        self._load_recent_thinking()
        self._load_theses()

        if HAS_ANTHROPIC and settings.anthropic_api_key:
            self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            logger.info("AI Trading Agent initialized")
        elif HAS_ANTHROPIC:
            logger.warning("ANTHROPIC_API_KEY not set — AI agent won't trade")

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

    async def run_cycle(self):
        """Main cycle — gather data, ask Claude, execute."""
        if not settings.agent_enabled or not self.client:
            return

        try:
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

        # Current time
        parts.append(f"Current time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

        # Portfolio state
        balance = auto_seller.get_usdc_balance() or 0
        positions = journal.get_open_positions()
        exposure = journal.get_total_exposure()
        parts.append(build_portfolio_summary(positions, balance, exposure))

        # Insider alerts
        parts.append(build_alert_summary(self._recent_alerts))

        # Smart money
        parts.append(build_smart_money_summary(self._recent_smart_money))

        # Market data
        async with PolymarketClient() as client:
            markets = await client.get_markets(limit=20, order="volume24hr")
            parts.append(build_market_briefing(markets))

        # Thesis board
        parts.append(build_thesis_board(self.theses))

        # Thinking history
        parts.append(build_thinking_history(self._thinking_history))

        return "\n\n".join(parts)

    async def _ask_claude(self, context: str) -> Optional[str]:
        """Call Claude API with the market briefing."""
        try:
            message = self.client.messages.create(
                model=settings.agent_model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}],
            )
            return message.content[0].text
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return None

    def _parse_response(self, response: str) -> Optional[Dict]:
        """Parse Claude's JSON response."""
        try:
            # Strip any markdown code blocks if present
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            try:
                start = response.index("{")
                end = response.rindex("}") + 1
                return json.loads(response[start:end])
            except (ValueError, json.JSONDecodeError):
                logger.warning(f"Failed to parse agent response: {response[:200]}")
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
                if amount_usd < 0.01:
                    continue

                # Check exposure
                current_exposure = journal.get_total_exposure()
                if current_exposure + amount_usd > settings.agent_max_total_exposure:
                    logger.info(f"Agent trade skipped: exposure limit (${current_exposure + amount_usd:.2f} > ${settings.agent_max_total_exposure:.2f})")
                    continue

                # Check position count
                if len(journal.get_open_positions()) >= settings.agent_max_positions:
                    logger.info("Agent trade skipped: max positions reached")
                    continue

                # Check duplicate
                if journal.has_open_position(market_id):
                    logger.info(f"Agent trade skipped: already have position in {market_question[:30]}")
                    continue

                # Get token_id for the market
                token_id = await self._resolve_token_id(market_id, outcome)
                if not token_id:
                    logger.warning(f"Could not resolve token for {market_question[:30]}")
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
                else:
                    logger.warning(f"AI trade failed: {result.error}")

            except Exception as e:
                logger.error(f"AI trade execution error: {e}")

    async def _resolve_token_id(self, market_id: str, outcome: str) -> Optional[str]:
        """Resolve a market_id + outcome to a CLOB token_id."""
        async with PolymarketClient() as client:
            market = await client.get_market(market_id)
            if not market:
                return None

            tokens = market.get("tokens", []) or market.get("clobTokenIds", [])
            if not tokens:
                return None

            idx = 0 if outcome in ("Yes", "YES", "yes") else 1

            if isinstance(tokens[0], dict):
                for t in tokens:
                    if t.get("outcome", "").lower() == outcome.lower():
                        return t.get("token_id")
                return tokens[0].get("token_id") if tokens else None
            else:
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
