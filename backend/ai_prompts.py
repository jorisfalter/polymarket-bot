"""
AI Trading Agent — Prompts and context builders.

Keeps the system prompt and data formatting separate from agent logic
so it's easy to tune the agent's personality and decision-making.
"""
import json
from typing import List, Dict, Any
from datetime import datetime


SYSTEM_PROMPT = """You are an AI hedge fund manager trading on Polymarket, a prediction market platform. You are cautious but decisive — you don't trade for the sake of trading, but when you see a real edge, you act fast.

## Your Edge
You have access to an insider detection system that scans thousands of trades and flags suspicious activity. When a fresh wallet suddenly drops $5,000 on a 10-cent outcome, that's a signal. You also see what the smartest traders on the platform are doing.

## Rules
- You trade with REAL money, but tiny amounts ($0.05 to $1.00 per trade) to prove the system works.
- Max 5 positions open at once. Max $1 per trade. Max $5 total exposure.
- NEVER trade sports markets, crypto price markets, or entertainment/celebrity markets.
- Focus on: politics, geopolitics, regulation, tech, science, finance, legal outcomes.
- You MUST respond with valid JSON only. No markdown, no explanation outside the JSON.

## When to Trade
- HIGH/CRITICAL insider alerts where a fresh wallet bets big on unlikely outcomes — this is your bread and butter.
- Smart money moves: when top-performing traders (60%+ win rate) take new positions.
- Resolution arbitrage: markets about to resolve where one outcome is 95%+ likely.
- Your own conviction: if the market data tells a clear story, you can act on it.

## When NOT to Trade
- No insider alerts and no clear edge — just wait. Most cycles you should do nothing.
- Price has already moved significantly since the signal.
- You already have a position in that market.
- You're near your exposure limit.

## Response Format
You MUST respond with this exact JSON structure:
{
  "thinking": "Your internal monologue. What do you see? What's interesting? What concerns you? Be specific about market names and numbers.",
  "trades": [
    {
      "action": "BUY",
      "market_id": "the conditionId or market ID",
      "market_question": "the market question",
      "outcome": "Yes or No",
      "amount_usd": 0.50,
      "confidence": 0.8,
      "thesis": "One sentence: why this trade"
    }
  ],
  "watchlist_notes": "Markets you want to keep watching and why. Be specific.",
  "risk_assessment": "How comfortable are you with current exposure? Any positions you're worried about?"
}

If you have no trades to make, return an empty trades array. That's fine — patience is a virtue.
The "thinking" field is the most important. It's your trading journal. Be honest and specific."""


def build_market_briefing(markets: List[Dict[str, Any]]) -> str:
    """Format top markets into a concise briefing."""
    if not markets:
        return "No market data available."

    lines = ["## Top Markets by Volume"]
    for m in markets[:20]:
        question = m.get("question", "?")[:80]
        prices_str = m.get("outcomePrices", "")
        try:
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            yes_price = float(prices[0]) if prices else 0
            no_price = float(prices[1]) if len(prices) > 1 else 0
        except (json.JSONDecodeError, ValueError, IndexError):
            yes_price, no_price = 0, 0

        vol = float(m.get("volume24hr", 0) or 0)
        liq = float(m.get("liquidity", 0) or 0)
        market_id = m.get("conditionId") or m.get("id") or ""
        end_date = m.get("endDate") or ""

        lines.append(
            f"- [{market_id[:12]}] {question}\n"
            f"  YES: {yes_price*100:.0f}c | NO: {no_price*100:.0f}c | "
            f"Vol24h: ${vol:,.0f} | Liq: ${liq:,.0f} | Ends: {end_date[:10]}"
        )

    return "\n".join(lines)


def build_alert_summary(alerts: list) -> str:
    """Format recent insider alerts for the agent."""
    if not alerts:
        return "No new insider alerts."

    lines = ["## Insider Alerts (Last 5 Minutes)"]
    for alert in alerts[:10]:
        st = alert.suspicious_trade if hasattr(alert, "suspicious_trade") else alert
        trade = st.trade if hasattr(st, "trade") else st
        wallet = st.wallet if hasattr(st, "wallet") else None

        question = getattr(trade, "market_question", "?")[:70]
        severity = st.severity.value if hasattr(st, "severity") else "?"
        score = getattr(st, "suspicion_score", 0)
        flags = getattr(st, "flags", [])
        side = getattr(trade, "side", "?")
        price = getattr(trade, "price", 0)
        notional = getattr(trade, "notional_usd", 0)
        market_id = getattr(trade, "market_id", "")
        outcome = getattr(trade, "outcome", "?")

        wallet_info = ""
        if wallet:
            wallet_info = (
                f"  Wallet: {wallet.address[:16]}... | "
                f"Trades: {wallet.total_trades} | Markets: {wallet.unique_markets} | "
                f"Win rate: {wallet.win_rate*100:.0f}%" if wallet.win_rate else ""
            )

        lines.append(
            f"- **{severity.upper()}** (score: {score}) [{market_id[:12]}]\n"
            f"  {question}\n"
            f"  {side} {outcome} @ {price:.0f}c | ${notional:,.0f}\n"
            f"  Flags: {', '.join(flags[:4])}\n"
            f"{wallet_info}"
        )

    return "\n".join(lines)


def build_portfolio_summary(positions: List[Dict], balance: float, exposure: float) -> str:
    """Format current portfolio state."""
    lines = [
        "## Your Portfolio",
        f"USDC Balance: ${balance:.2f}",
        f"Total Exposure: ${exposure:.2f} / $5.00",
        f"Open Positions: {len(positions)} / 5",
    ]

    if positions:
        lines.append("")
        for p in positions:
            lines.append(
                f"- {p.get('market_question', '?')[:60]}\n"
                f"  Entry: {p.get('price', 0):.4f} | Amount: ${p.get('amount_usd', 0):.2f} | "
                f"Strategy: {p.get('strategy', '?')}"
            )
    else:
        lines.append("\nNo open positions.")

    return "\n".join(lines)


def build_thinking_history(entries: List[Dict]) -> str:
    """Format recent thinking entries for continuity."""
    if not entries:
        return "No previous thinking entries. This is your first cycle."

    lines = ["## Your Recent Thinking"]
    for e in entries[:3]:
        ts = e.get("timestamp", "?")[:16]
        thinking = e.get("thinking", "")[:300]
        trades_count = len(e.get("trades", []))
        lines.append(f"[{ts}] ({trades_count} trades) {thinking}")

    return "\n".join(lines)


def build_smart_money_summary(trades: List[Dict]) -> str:
    """Format recent smart money trades."""
    if not trades:
        return "No new smart money activity."

    lines = ["## Smart Money Moves"]
    for t in trades[:10]:
        lines.append(
            f"- Trader {t.get('trader', '?')[:12]}... "
            f"{t.get('side', '?')} on \"{t.get('market', '?')[:50]}\" "
            f"${float(t.get('usdcSize', 0)):,.0f} @ {float(t.get('price', 0))*100:.0f}c"
        )

    return "\n".join(lines)
