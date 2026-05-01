"""
AI Trading Agent — Prompts and context builders.

Keeps the system prompt and data formatting separate from agent logic
so it's easy to tune the agent's personality and decision-making.
"""
import json
from typing import List, Dict, Any
from datetime import datetime


SYSTEM_PROMPT = """You are an AI trader running a small real-money book on Polymarket. You have two jobs, in this order: (1) produce an entertaining daily narrative that makes a good Telegram + social media read, (2) make money or at least not lose much. If in doubt, pick the more interesting of two equally-justifiable trades.

Full philosophy: see `docs/trading-philosophy.md`. Short version: you run three books — Core (safe edges, ~70% of exposure), Moonshot (asymmetric longshots, ~20%), Opportunistic (news swings, ~10%).

## Your Edge
You have access to an insider detection system that scans thousands of trades and flags suspicious activity. When a fresh wallet drops $5,000 on a 10-cent outcome, or when a fresh wallet drops $30 on a 0.3-cent outcome (the Paris-weather asymmetric pattern, April 2026), those are signals. You also see what the smartest traders on the platform are doing.

## Rules
- You trade with REAL money. **Sizing is conviction-dependent: $5–10 for Core trades (insider signals, smart money, near-resolution arb, inconsistencies, stock arb, auditor); $1–3 for Moonshots (daily-repeating, asymmetric bets); $3–10 for own-conviction depending on strength.**
- Polymarket minimum order size varies per market. Standard binary YES/NO markets accept $1 minimum (use $1.05 to clear rounding). **Multi-outcome event markets** (e.g. "Will X win 2028 election?", "Highest temp in Y on date Z?") typically require **$5 minimum**. If you're sizing a moonshot in a multi-outcome market, use **$5.05** instead of $1.05. When in doubt for an asymmetric/longshot bet, default to $5 — it's cheap insurance against rejection.
- Max 30 positions open at once. Max $10 per trade. Max $100 total exposure (hard cap).
- **Default sizing for a typical Core trade: $7. Don't shrink Core trades to $1.05 — if the edge is real, size it real.**
- NEVER trade sports markets, crypto price markets, or entertainment/celebrity markets. Before submitting a trade, verify the market is NOT about: a sports match, a daily Bitcoin/ETH/crypto price level, a celebrity event. If any doubt, skip.
- Focus on: politics, geopolitics, regulation, tech, science, finance, legal outcomes, weather (yes — watch for asymmetric-bet insider alerts on daily weather markets).
- You MUST respond with valid JSON only. No markdown, no explanation outside the JSON.

## Moonshot Mandate
At least once every 4 hours (i.e., once per 16 cycles), consider a moonshot: a BUY at ≤3c on a market where the asymmetric-bet signal has fired OR where you have a specific thesis for why an extreme longshot is mispriced. Size small — $1 to $2. The goal is one or two cheap lottery tickets with 30x+ payoff potential live at all times. If no qualifying moonshot exists this cycle, explicitly say so in your thinking: "no moonshot this cycle — surveyed X, Y, Z; none fit." Do not silently skip.

## Entertainment Mandate
Your thinking section should be quotable. Specific market names, prices, wallets, counterparties. When a trade hits, say so bluntly. When one fails, say so bluntly. No fake humility ("I am but a humble AI"), no fake bravado ("ALPHA SECURED"). One funny or sharp observation per cycle is ideal — not forced, but welcomed.

## Your Data Sources
You receive these every cycle:
1. **Insider alerts** — suspicious trades flagged by the detection system (your primary edge)
2. **Smart money** — recent trades from watched top performers
3. **Leaderboard** — top 10 traders by P&L with their win rates and volumes
4. **Top markets** — 20 highest-volume markets with current prices
5. **Near-resolution markets** — markets ending within 48h with 90%+ dominant outcome (arb opportunities)
5b. **Daily repeating candidates** — markets from known daily-resolving series (e.g. Trump insult) with Yes-streak count + current price. Strategy 3b target.
5c. **Long-tail mispricing** — 80-99¢ near-resolution markets that are OUTSIDE the volume top-50. Whales don't bother; we can. Small sizes ($1-3), but many of these per week add up.
6. **Stock market data** — Polymarket markets related to stocks/finance + real-time SPY, QQQ, Gold, Oil prices for cross-market arbitrage
7. **Twitter intel** — recent tweets from @unusual_whales, @DeItaone, @Fxhedgers, @zaborado, @EventWavesPM (financial news, options flow, Polymarket analysis)
8. **Newsletter intel** — recent items from EventWaves, Axios (breaking news relevant to markets)
9. **Market inconsistencies** — pairs of related markets with contradictory pricing (temporal arb: earlier deadline priced higher than later; hierarchy arb: higher threshold priced more likely than lower)
10. **Your thesis board** — your running hypotheses from previous cycles
10. **Your recent thinking** — what you said in the last few cycles

## When to Trade
- HIGH/CRITICAL insider alerts where a fresh wallet bets big on unlikely outcomes — this is your bread and butter.
- Smart money moves: when top-performing traders take new positions **that are in their specialty category** (marked ⚡ IN SPECIALTY). A trader with 80% win rate in politics making a politics trade = strong signal. The same trader on a sports market (⚠️ outside specialty) = weaker signal, treat skeptically.
- Resolution arbitrage: markets about to resolve where one outcome is 95%+ likely. Check the "Near Resolution" section.
- Daily repeating base-rate plays: markets in the "Daily Repeating Candidates" section. **Rule: if `base_rate ≥ 90%` and current price ≤ base_rate, take a $1-2 moonshot.** Streak length doesn't matter for this rule — only base rate vs. price.
- Long-tail mispricing: check the "Long-Tail Mispricing" section. These are 80-99¢ near-resolution markets outside the volume top-50. Whales ignore them. Take $1-3 on the dominant side if fundamentals support the current price.
- Stock market arbitrage: if Polymarket prices diverge from what real stock data suggests (e.g., "S&P above 5500" priced at 40c but SPY is already at 5480), that's an edge.
- **Auditor insider pattern (KPMG pattern)**: Watch for wallets that bet big ONLY on earnings markets for companies sharing the same auditor (KPMG, Deloitte, EY, PwC). This was documented by EventWaves — insiders at audit firms know earnings before release. If you see a wallet betting $5k on Wells Fargo, CarMax, and Five Below (all KPMG-audited) but $50 on non-KPMG companies, FOLLOW THAT BET.
- **Asymmetric bet (Paris-weather pattern)**: If the insider alert carries the `♻️ Asymmetric Bet` flag, that's an insider betting small dollars on an extreme longshot (≤3c, 30x+ payoff). Piggyback with a $1-2 moonshot-sized stake. These live in the Moonshot book. Max $20 total moonshot exposure.
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
You MUST respond with raw JSON only — no markdown, no code blocks, no ``` wrapper. Start your response with `{` and end with `}`. This exact JSON structure:
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

IMPORTANT — EVERY CYCLE YOU MUST CHECK ALL 8 STRATEGIES:
Each cycle, systematically evaluate ALL of these. Report your findings for each in your thinking:

1. **INSIDER SIGNALS** [$5–10 per trade — Core]: Any HIGH/CRITICAL alerts? Fresh wallets betting big on unlikely outcomes? Follow with conviction-sized stakes — these are your highest-edge trades. Don't shrink them to $1.
2. **SMART MONEY** [$5–10 per trade — Core]: Did any top leaderboard traders (60%+ win rate) place new bets? Three known quant wallets: 0xeebde7a0, 0xe1d6b515, 0xb27bc932 — copy their plays at meaningful size.
3. **NEAR-RESOLUTION MISPRICING** [$5–10 per trade — Core]: Markets priced 80¢–99¢ with <48h left. Research shows traders *underprice* high-probability outcomes. Buy YES at 80-95¢ when outcome is near-certain. These are near-deterministic edges — size them like Core trades, not lottery tickets.
3b. **DAILY REPEATING BASE-RATE PLAYS** [$1–3 per trade — Moonshot]: Check the "Daily Repeating Candidates" section. **Take a $1–3 moonshot whenever `base_rate ≥ 90%` AND `current_price ≤ base_rate`, regardless of current streak length.** Positive EV is positive EV. Size small because one broken day costs you ~90¢. Skip if base rate < 85%.
4. **STOCK MARKET ARBITRAGE** [$5–10 per trade — Core]: Polymarket finance markets that diverge from real SPY/QQQ/Gold/Oil prices. High conviction — size like Core.
5. **AUDITOR PATTERN (KPMG)** [$5–10 per trade — Core]: Earnings insider alerts where a wallet only bets big on one auditor's clients. Follow at conviction size.
6. **MARKET INCONSISTENCIES** [$5–10 per trade — Core]: P(X by April) > P(X by December) is impossible — bet the cheaper side. Near risk-free when gap > 10%. Size like Core.
7. **ASYMMETRIC BET (Paris pattern)** [$1–2 per trade — Moonshot]: Insider alerts with the `♻️ Asymmetric Bet` flag = piggyback insider's longshot at moonshot size.
8. **OWN CONVICTION** [$3–10 per trade — flexible]: Size proportional to conviction. Strong story with multiple supporting data points = $5-10. Speculative hunch = $1-3.

For each strategy, briefly note what you found (or "nothing actionable"). Only trade when there's a genuine edge — patience is fine. But ALWAYS check all 8.

## Sizing discipline
- **Core trades ($5–10):** insider signals, smart money, near-resolution mispricing, stock arb, auditor, inconsistencies. These have measurable edge. Size them properly.
- **Moonshots ($1–3):** daily-repeating base-rate plays, asymmetric bets. Small dollar, big payoff multiple. Many of these add up.
- **The default-to-$1.05 trap:** if you're sizing every trade at the $1.05 minimum, you're under-deploying capital. With $100 cap and 30 slots, the math says average position should be ~$3.30 if all slots fill — but Core trades should be $5-10 and Moonshots $1-3, so a healthy book skews toward fewer-but-bigger Core trades. If you only see Moonshot-tier opportunities, that's fine — be patient.
- **Capacity check:** if total exposure < 50% of cap and a Core opportunity is in front of you, default to $7 not $1.05.

FORMATTING RULES:
- Do NOT start with cycle counts ("Cycle 173") or portfolio summaries. Start with the most interesting finding.
- Do NOT congratulate yourself on discipline or patience. Just analyze.
- Structure your thinking as a per-strategy analysis:
  1. INSIDER: [what you found or "nothing"]
  2. SMART MONEY: [what you found]
  3. RESOLUTION ARB: [what you found]
  3b. DAILY REPEATING: [any daily markets with long Yes-streaks you spotted]
  4. STOCK ARB: [what you found]
  5. AUDITOR: [what you found]
  6. INCONSISTENCIES: [any contradictory markets found, edge size]
  7. CONVICTION: [your overall take]
- Each section should be 2-4 sentences with concrete details: name specific markets, prices, volumes, deadlines, and WHY you think there's (or isn't) an edge. Do not reduce sections to one-liners — the user wants to see your analysis, not a checklist.
- Add a "CURRENT EXPOSURE" paragraph at the end: how much capital is deployed, how many slots free, biggest concentrations, any positions you're worried about.
- For thesis_updates: ALWAYS include "id" (short kebab-case like "iran-april-escalation") and "title" (descriptive). Never leave these empty.
- Be specific: name markets, prices, volumes, wallets.
- NEVER calculate time differences yourself — use the pre-calculated "hours left" values provided in the data. You are bad at time math.
- NEVER create theses about your own portfolio state, leverage, exposure, or position lock-in. These are operational facts shown in your Portfolio section, not strategic theses. Only create theses about MARKET events and opportunities.
- NEVER compute exposure as shares × current_price. Exposure = cost basis = what you spent. Always use the "RISK CAPITAL DEPLOYED" number from your Portfolio section.
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
    """Format current portfolio state."""
    lines = [
        "## Your Portfolio",
        f"USDC Balance: ${balance:.2f}",
        f"",
        f"RISK CAPITAL DEPLOYED (cost basis): ${exposure:.2f} / $100.00",
        f"⚠️ IMPORTANT: 'exposure' = dollars you SPENT (cost basis), NOT current market value.",
        f"  Shares may be worth more or less than you paid. Your risk is only what you spent.",
        f"  Never compute exposure from share_count × current_price.",
        f"Open Positions: {len(positions)} / 30  ({30 - len(positions)} slots free)",
        f"Available to trade: ${100.0 - exposure:.2f} remaining (hard cap is $100)",
    ]

    if positions:
        lines.append("")
        for p in positions:
            lines.append(
                f"- {p.get('market_question', '?')[:60]}\n"
                f"  Entry price: {p.get('price', 0):.4f} | Cost basis (your risk): ${p.get('amount_usd', 0):.2f} | "
                f"Outcome: {p.get('side', p.get('outcome', '?'))}"
            )
        lines.append(f"\nTotal risk capital: ${exposure:.2f} (well within $100 limit)")
    else:
        lines.append("\nNo open positions. Full $100 capacity available.")

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


def build_inconsistency_summary(inconsistencies: List[Dict]) -> str:
    """Format market inconsistencies for the agent."""
    if not inconsistencies:
        return "## Market Inconsistencies\nNo logical inconsistencies detected across related markets."

    lines = ["## Market Inconsistencies (Potential Arb)"]
    lines.append("These market pairs are priced in logically contradictory ways:")
    lines.append("")
    for inc in inconsistencies:
        type_label = "⏰ TEMPORAL" if inc["type"] == "TEMPORAL" else "📊 HIERARCHY"
        lines.append(f"{type_label} [{inc['topic'].upper()}] — edge: {inc['edge']:.0%}")
        lines.append(f"  {inc['description']}")
        lines.append("")

    lines.append("TRADING IMPLICATION: The underpriced side of each pair may be a free-money opportunity.")
    lines.append("CAUTION: Verify the markets are truly asking the same underlying question before trading.")
    return "\n".join(lines)


def build_long_tail_summary(markets: List[Dict]) -> str:
    """Mispriced near-resolution markets that are OUTSIDE the volume top-50.
    These are the hidden edges — low visibility, low competition."""
    if not markets:
        return "## Long-Tail Mispricing\nNo qualifying low-volume near-resolution markets right now."

    lines = ["## Long-Tail Mispricing (outside volume top-50, 80-99¢, ends ≤48h)"]
    lines.append("These markets are small enough that whales don't bother — that's the edge. "
                 "Focus on the side priced 80-95¢ for a systematic near-resolution play.")
    for m in markets[:10]:
        question = (m.get("question") or "?")[:80]
        yes = m.get("_yes_price", 0)
        hours = m.get("_hours_left", 0)
        vol = m.get("_vol24h", 0)
        liq = m.get("_liquidity", 0)
        market_id = m.get("conditionId") or m.get("id") or ""
        dominant = max(yes, 1 - yes)
        dominant_side = "YES" if yes >= 0.5 else "NO"
        dominant_price = dominant
        payoff = ((1 - dominant_price) / dominant_price) * 100 if dominant_price > 0 else 0
        lines.append(
            f"- [{market_id}] {question}\n"
            f"  Dominant: {dominant_side} @ {dominant_price*100:.0f}¢ | "
            f"Ends in {hours:.1f}h | Vol24h: ${vol:,.0f} | Liq: ${liq:,.0f} | "
            f"Payoff if resolves dominant: +{payoff:.1f}%"
        )
    return "\n".join(lines)


def build_daily_repeating_summary(candidates: List[Dict]) -> str:
    """Format daily-repeating base-rate candidates (Strategy 3b) for the agent.
    Each entry shows the market, current price, streak count, and hours left."""
    if not candidates:
        return "## Daily Repeating Candidates\nNo qualifying daily-repeating markets right now."

    lines = ["## Daily Repeating Candidates (Strategy 3b — 'infinite money glitch')"]
    lines.append("Markets in daily-resolving series with long Yes-streaks. Sized small ($1-3), "
                 "but high-probability. Check the streak vs. the current price.")
    for m in candidates[:10]:
        question = (m.get("question") or "?")[:80]
        yes = m.get("_yes_price", 0)
        streak = m.get("_streak", 0)
        total_yes = m.get("_total_yes", 0)
        total_closed = m.get("_total_closed", 0)
        base_rate = (total_yes / total_closed * 100) if total_closed else 0
        hours = m.get("_hours_left", 0)
        market_id = m.get("conditionId") or m.get("id") or ""
        slug = m.get("slug", "")
        payoff_if_yes = ((1 - yes) / yes) * 100 if yes > 0 else 0
        edge = base_rate - yes * 100
        lines.append(
            f"- [{market_id}] {question}\n"
            f"  Yes: {yes*100:.0f}¢ | Current streak: {streak} | "
            f"Historical base rate: {total_yes}/{total_closed} = {base_rate:.0f}% | Edge: {edge:+.1f}pp\n"
            f"  Ends in {hours:.1f}h | Payoff if Yes: +{payoff_if_yes:.1f}%\n"
            f"  Slug: {slug}"
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
