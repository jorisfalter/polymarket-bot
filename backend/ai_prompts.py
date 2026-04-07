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
- You trade with REAL money, small amounts ($1.05 to $1.50 per trade).
- IMPORTANT: Polymarket minimum order size is $1.00. Always use at least $1.05 per trade to account for rounding.
- Max 5 positions open at once. Max $1.50 per trade. Max $20 total exposure.
- NEVER trade sports markets, crypto price markets, or entertainment/celebrity markets.
- Focus on: politics, geopolitics, regulation, tech, science, finance, legal outcomes.
- You MUST respond with valid JSON only. No markdown, no explanation outside the JSON.

## Your Data Sources
You receive these every cycle:
1. **Insider alerts** — suspicious trades flagged by the detection system (your primary edge)
2. **Smart money** — recent trades from watched top performers
3. **Leaderboard** — top 10 traders by P&L with their win rates and volumes
4. **Top markets** — 20 highest-volume markets with current prices
5. **Near-resolution markets** — markets ending within 48h with 90%+ dominant outcome (arb opportunities)
6. **Stock market data** — Polymarket markets related to stocks/finance + real-time SPY, QQQ, Gold, Oil prices for cross-market arbitrage
7. **Twitter intel** — recent tweets from @unusual_whales, @DeItaone, @Fxhedgers, @zaborado, @EventWavesPM (financial news, options flow, Polymarket analysis)
8. **Newsletter intel** — recent items from EventWaves, Axios (breaking news relevant to markets)
9. **Your thesis board** — your running hypotheses from previous cycles
10. **Your recent thinking** — what you said in the last few cycles

## When to Trade
- HIGH/CRITICAL insider alerts where a fresh wallet bets big on unlikely outcomes — this is your bread and butter.
- Smart money moves: when top-performing traders take new positions **that are in their specialty category** (marked ⚡ IN SPECIALTY). A trader with 80% win rate in politics making a politics trade = strong signal. The same trader on a sports market (⚠️ outside specialty) = weaker signal, treat skeptically.
- Resolution arbitrage: markets about to resolve where one outcome is 95%+ likely. Check the "Near Resolution" section.
- Stock market arbitrage: if Polymarket prices diverge from what real stock data suggests (e.g., "S&P above 5500" priced at 40c but SPY is already at 5480), that's an edge.
- **Auditor insider pattern (KPMG pattern)**: Watch for wallets that bet big ONLY on earnings markets for companies sharing the same auditor (KPMG, Deloitte, EY, PwC). This was documented by EventWaves — insiders at audit firms know earnings before release. If you see a wallet betting $5k on Wells Fargo, CarMax, and Five Below (all KPMG-audited) but $50 on non-KPMG companies, FOLLOW THAT BET.
- Your own conviction: if the market data tells a clear story, you can act on it.

## When NOT to Trade
- No insider alerts and no clear edge — just wait. Most cycles you should do nothing.
- Price has already moved significantly since the signal.
- You already have a position in that market.
- You're near your exposure limit.

## Thesis Board
You maintain a board of investment theses — hypotheses about what will happen in specific markets. Each thesis tracks your evolving conviction over time, like an analyst's investment memo. You can:
- **CREATE** a new thesis when you spot a pattern or developing story
- **UPDATE** an existing thesis when new evidence arrives (confirm, weaken, or change conviction)
- **CLOSE** a thesis when it's resolved, invalidated, or you lose interest

Good theses are specific: "Iran escalation will push strike market above 30c by April" not "geopolitics is interesting". Theses give you long-term memory — they carry your thinking across cycles and days.

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
  "thesis_updates": [
    {
      "action": "CREATE",
      "id": "short-kebab-case-id",
      "title": "Descriptive title of the thesis",
      "market_id": "related market conditionId (optional)",
      "conviction": "low/medium/high",
      "note": "Why you believe this, what evidence supports it"
    }
  ],
  "watchlist_notes": "Markets you want to keep watching and why. Be specific.",
  "risk_assessment": "How comfortable are you with current exposure? Any positions you're worried about?"
}

For thesis_updates, use action "CREATE" for new theses, "UPDATE" to change conviction/add notes (include the same "id"), "CLOSE" when done (include "id" and "note" explaining why).

If you have no trades, return an empty trades array. That's fine — patience is a virtue.

IMPORTANT — EVERY CYCLE YOU MUST CHECK ALL 6 STRATEGIES:
Each cycle, systematically evaluate ALL of these. Report your findings for each in your thinking:

1. **INSIDER SIGNALS**: Any HIGH/CRITICAL alerts? Fresh wallets betting big on unlikely outcomes? If yes, consider following with $0.50-$1.00.
2. **SMART MONEY**: Did any top leaderboard traders (60%+ win rate) place new bets? What markets? Consider copying.
3. **RESOLUTION ARBITRAGE**: Any markets in the "Near Resolution" section with 95%+ dominant outcome and <48h left? That's near-free money.
4. **STOCK MARKET ARBITRAGE**: Do any Polymarket finance markets diverge from the real stock prices (SPY, QQQ, Gold, Oil)? If Polymarket says "S&P above 5500" at 40c but SPY is at 5490, that's mispriced.
5. **AUDITOR PATTERN (KPMG)**: Any earnings insider alerts where the wallet only bets big on one auditor's clients? Follow that bet.
6. **OWN CONVICTION**: Does any market data tell a clear story that others are missing?

For each strategy, briefly note what you found (or "nothing actionable"). Only trade when there's a genuine edge — patience is fine. But ALWAYS check all 6.

## SPECIAL FOCUS: IRAN ESCALATION (March-April 2026)
There are strong rumors of a US ground invasion of Iran. This is your #1 priority right now. Key markets:
- "US forces enter Iran by March 31" — 6.4c YES, $36.4M volume (resolves in ~1 day!)
- "US forces enter Iran by April 30" — 72c YES, $8.74M volume
- "US forces enter Iran by Dec 31" — 78c YES, $5.81M volume

Watch for: insider signals on these markets (fresh wallets going big), OSINT tweets about military movements, breaking news from defense reporters. If you see a credible signal that an invasion is imminent, even a small one, this is a high-conviction trade.

The Twitter intel now includes OSINT/defense accounts: @IntelDoge, @sentdefender, @BNONews, @jackdetsch. Pay special attention to their Iran-related tweets.

FORMATTING RULES:
- Do NOT start with cycle counts ("Cycle 173") or portfolio summaries. Start with the most interesting finding.
- Do NOT congratulate yourself on discipline or patience. Just analyze.
- Structure your thinking as a brief summary per strategy check:
  1. INSIDER: [what you found or "nothing"]
  2. SMART MONEY: [what you found]
  3. RESOLUTION ARB: [what you found]
  4. STOCK ARB: [what you found]
  5. AUDITOR: [what you found]
  6. CONVICTION: [your overall take]
- Keep each section to 1-2 sentences. Total thinking under 600 chars.
- For thesis_updates: ALWAYS include "id" (short kebab-case like "iran-april-escalation") and "title" (descriptive). Never leave these empty.
- Be specific: name markets, prices, volumes, wallets.
- NEVER calculate time differences yourself — use the pre-calculated "hours left" values provided in the data. You are bad at time math.
"""


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
            f"- [{market_id}] {question}\n"
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
            f"- **{severity.upper()}** (score: {score}) [{market_id}]\n"
            f"  {question}\n"
            f"  {side} {outcome} @ {price:.0f}c | ${notional:,.0f}\n"
            f"  Flags: {', '.join(flags[:4])}\n"
            f"{wallet_info}"
        )

    return "\n".join(lines)


def build_portfolio_summary(positions: List[Dict], balance: float, exposure: float, live: bool = False) -> str:
    """Format current portfolio state. If live=True, positions are from Polymarket API."""
    source = "LIVE from Polymarket" if live else "local journal"
    lines = [
        "## Your Portfolio",
        f"USDC Balance: ${balance:.2f}",
        f"Total Exposure: ${exposure:.2f} / $20.00 ({source})",
        f"Open Positions: {len(positions)} / 5",
    ]

    if positions:
        lines.append("")
        for p in positions:
            lines.append(
                f"- {p.get('market_question', '?')[:60]}\n"
                f"  Entry: {p.get('price', 0):.4f} | Spent: ${p.get('amount_usd', 0):.2f} | "
                f"Outcome: {p.get('side', p.get('outcome', '?'))}"
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


def build_thesis_board(theses: List[Dict]) -> str:
    """Format active theses for the agent's context."""
    active = [t for t in theses if t.get("status") == "active"]
    if not active:
        return "## Your Thesis Board\nNo active theses. Create one when you spot a developing story."

    lines = ["## Your Thesis Board"]
    for t in active:
        conviction = t.get("conviction", "?").upper()
        title = t.get("title", "?")
        tid = t.get("id", "?")
        created = t.get("created", "?")[:10]
        updated = t.get("updated", "?")[:10]
        history = t.get("history", [])
        latest_note = history[-1].get("note", "") if history else t.get("note", "")

        lines.append(
            f"- **[{tid}]** {title}\n"
            f"  Conviction: {conviction} | Created: {created} | Updated: {updated}\n"
            f"  Latest: {latest_note[:200]}"
        )

    return "\n".join(lines)


def build_smart_money_summary(trades: List[Dict]) -> str:
    """Format recent smart money trades, including category specialty signals."""
    if not trades:
        return "No new smart money activity."

    lines = ["## Smart Money Moves"]
    for t in trades[:10]:
        category = t.get("category", "other")
        in_specialty = t.get("in_specialty", False)
        specialty = t.get("wallet_specialty", "unknown")
        specialty_pct = t.get("wallet_specialty_pct", 0)

        # Build specialty tag
        if specialty and specialty != "unknown" and specialty_pct > 0:
            spec_tag = f" | Specialty: {specialty} ({specialty_pct}%)"
            match_tag = " ⚡ IN SPECIALTY" if in_specialty else " ⚠️ outside specialty"
        else:
            spec_tag = ""
            match_tag = ""

        lines.append(
            f"- Trader {t.get('trader', '?')[:12]}... "
            f"{t.get('side', '?')} on \"{t.get('market', '?')[:50]}\" "
            f"${float(t.get('usdcSize', 0)):,.0f} @ {float(t.get('price', 0))*100:.0f}c"
            f" [{category}]{spec_tag}{match_tag}"
        )

    lines.append("\nNote: ⚡ = trade is in wallet's dominant category (higher signal strength). ⚠️ = outside their specialty (treat with more skepticism).")
    return "\n".join(lines)


def build_leaderboard_summary(leaders: List[Dict]) -> str:
    """Format top traders from leaderboard, with category specialization if available."""
    if not leaders:
        return "No leaderboard data available."

    lines = ["## Top Traders (Leaderboard by PnL)"]
    for t in leaders[:10]:
        addr = t.get("address", "?")[:12]
        name = t.get("display_name") or t.get("name") or addr
        pnl = float(t.get("pnl", 0) or 0)
        vol = float(t.get("volume", 0) or 0)
        efficiency = (pnl / vol * 100) if vol > 0 else 0

        spec = t.get("specialization", {})
        spec_str = ""
        if spec and spec.get("top_category") and spec.get("top_category") != "unknown":
            spec_str = f" | Specialty: {spec['top_category']} ({spec.get('top_pct', 0)}%)"

        lines.append(
            f"- #{t.get('rank', '?')} {name[:20]} | PnL: ${pnl:,.0f} | "
            f"Volume: ${vol:,.0f} | Efficiency: {efficiency:.0f}%{spec_str}"
        )

    return "\n".join(lines)


def build_near_resolution_summary(markets: List[Dict]) -> str:
    """Format markets that are about to resolve."""
    if not markets:
        return "No near-resolution opportunities found."

    lines = ["## Markets Near Resolution (within 48h)"]
    for m in markets:
        question = m.get("question", "?")[:70]
        yes_price = m.get("_yes_price", 0)
        hours_left = m.get("_hours_left", 0)
        liq = float(m.get("liquidity", 0) or 0)
        market_id = m.get("conditionId") or m.get("id") or ""
        expected_return = ((1.0 - yes_price) / yes_price * 100) if yes_price > 0 and yes_price < 1 else 0

        dominant = "YES" if yes_price >= 0.5 else "NO"
        dominant_price = yes_price if yes_price >= 0.5 else (1 - yes_price)

        lines.append(
            f"- [{market_id}] {question}\n"
            f"  {dominant}: {dominant_price*100:.0f}c | {hours_left:.0f}h left | "
            f"Liq: ${liq:,.0f} | Potential return: {((1-dominant_price)/dominant_price*100):.1f}%"
        )

    return "\n".join(lines)


def build_stock_market_summary(stock_markets: List[Dict], stock_prices: Dict) -> str:
    """Format stock-related Polymarket markets with real stock data for arbitrage."""
    if not stock_markets:
        return "No stock-related markets found on Polymarket."

    lines = ["## Stock Market Arbitrage Opportunities"]
    if stock_prices:
        lines.append("Real-time stock data:")
        for symbol, data in stock_prices.items():
            price = data.get("price", 0)
            change = data.get("change_pct", 0)
            lines.append(f"  {symbol}: ${price:.2f} ({change:+.1f}%)")
        lines.append("")

    for m in stock_markets[:10]:
        question = m.get("question", "?")[:70]
        prices_str = m.get("outcomePrices", "")
        try:
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            yes_price = float(prices[0]) if prices else 0
        except (json.JSONDecodeError, ValueError, IndexError):
            yes_price = 0

        market_id = m.get("conditionId") or m.get("id") or ""
        end_date = m.get("endDate") or ""

        lines.append(
            f"- [{market_id}] {question}\n"
            f"  YES: {yes_price*100:.0f}c | Ends: {end_date[:10]}"
        )

    return "\n".join(lines)
