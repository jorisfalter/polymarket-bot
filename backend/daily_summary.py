"""
Daily Summary — runs at 09:00 UTC every day, produces a social-media-ready
recap of the last 24h: P&L, wins/losses, running theses, live moonshots,
and a trader's take for the day.

Output shape is deliberately quotable — it should be copy-paste ready for
X/Telegram/LinkedIn with no cleanup.

See docs/trading-philosophy.md for the philosophy this recap reinforces.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger

from .config import settings
from .trade_journal import journal
from .integrations import send_telegram, _esc
from . import ai_agent as _ai_agent_module
from .auto_seller import auto_seller

SUMMARY_JOURNAL_PATH = Path(__file__).parent.parent / "data" / "daily_summaries.jsonl"


def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _recent_exits(hours: int) -> List[Dict]:
    """Return all EXIT journal entries within the last N hours."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    history = journal.get_history(limit=500)
    out = []
    for e in history:
        if e.get("action") != "EXIT":
            continue
        ts = _parse_ts(e.get("timestamp", ""))
        if ts and ts >= cutoff:
            out.append(e)
    return out


def _pnl_window(hours: int) -> Dict:
    exits = _recent_exits(hours)
    total = sum(e.get("pnl_usd", 0) or 0 for e in exits)
    wins = sum(1 for e in exits if (e.get("pnl_usd") or 0) > 0)
    losses = sum(1 for e in exits if (e.get("pnl_usd") or 0) <= 0)
    return {
        "pnl_usd": round(total, 2),
        "trades": len(exits),
        "wins": wins,
        "losses": losses,
        "exits": exits,
    }


def _biggest_win_and_loss(exits: List[Dict]):
    if not exits:
        return None, None
    by_pnl = sorted(exits, key=lambda e: (e.get("pnl_usd") or 0), reverse=True)
    top = by_pnl[0] if by_pnl and (by_pnl[0].get("pnl_usd") or 0) > 0 else None
    bottom = by_pnl[-1] if by_pnl and (by_pnl[-1].get("pnl_usd") or 0) < 0 else None
    return top, bottom


def _classify_book(entry: Dict) -> str:
    """Tag an open position as core / moonshot / opportunistic based on entry."""
    price = float(entry.get("price", 0) or 0)
    if 0 < price <= 3:
        return "moonshot"
    if price >= 80:
        return "core"
    return "opportunistic"


def _live_moonshots() -> List[Dict]:
    return [p for p in journal.get_open_positions() if _classify_book(p) == "moonshot"]


def generate_daily_summary() -> Dict:
    """Produce the raw data shape for the daily summary."""
    ai_agent = _ai_agent_module.ai_agent

    last_24h = _pnl_window(24)
    last_7d = _pnl_window(24 * 7)
    lifetime = journal.get_performance()

    open_positions = journal.get_open_positions()
    exposure = sum(p.get("amount_usd", 0) or 0 for p in open_positions)
    balance = auto_seller.get_usdc_balance() or 0

    top_win, top_loss = _biggest_win_and_loss(last_24h["exits"])

    active_theses = [t for t in (ai_agent.theses or []) if t.get("status") == "active"]
    active_theses_sorted = sorted(
        active_theses,
        key=lambda t: {"high": 3, "medium": 2, "low": 1}.get((t.get("conviction") or "").lower(), 0),
        reverse=True,
    )[:3]

    # Last agent cycle's watchlist + thinking snippet
    last_thinking = ai_agent._thinking_history[-1] if ai_agent._thinking_history else {}
    watchlist = last_thinking.get("watchlist_notes", "")
    last_take = last_thinking.get("thinking", "")

    return {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "timestamp": datetime.utcnow().isoformat(),
        "pnl_24h": last_24h,
        "pnl_7d": last_7d,
        "lifetime": lifetime,
        "balance": balance,
        "exposure": exposure,
        "open_positions": open_positions,
        "top_win": top_win,
        "top_loss": top_loss,
        "moonshots_live": _live_moonshots(),
        "active_theses": active_theses_sorted,
        "watchlist": watchlist,
        "last_take": last_take,
    }


def format_for_telegram(data: Dict) -> List[str]:
    """Return a list of HTML-formatted messages (one per block) ready for Telegram."""
    date = data["date"]
    p24 = data["pnl_24h"]
    p7 = data["pnl_7d"]
    lt = data["lifetime"]
    balance = data["balance"]
    exposure = data["exposure"]
    positions = data["open_positions"]

    pnl_emoji = "🟢" if p24["pnl_usd"] >= 0 else "🔴"
    pnl_sign = "+" if p24["pnl_usd"] >= 0 else ""

    # Headline
    headline = (
        f"📰 <b>Daily Recap — {date}</b>\n"
        f"{pnl_emoji} 24h P&amp;L: <b>{pnl_sign}${p24['pnl_usd']:.2f}</b> "
        f"({p24['wins']}W / {p24['losses']}L over {p24['trades']} closed trades)"
    )

    # Scoreboard
    scoreboard = (
        f"📊 <b>Scoreboard</b>\n"
        f"• 24h: {pnl_sign}${p24['pnl_usd']:.2f} on {p24['trades']} trades\n"
        f"• 7d: {'+' if p7['pnl_usd']>=0 else ''}${p7['pnl_usd']:.2f} on {p7['trades']} trades\n"
        f"• Lifetime: {'+' if lt['total_pnl']>=0 else ''}${lt['total_pnl']:.2f} on {lt['trades']} trades "
        f"(win rate {lt['win_rate']*100:.0f}%)\n"
        f"• Exposure: ${exposure:.2f} / ${settings.agent_max_total_exposure:.0f} "
        f"({len(positions)}/{settings.agent_max_positions} slots)\n"
        f"• Cash: ${balance:.2f}"
    )

    # Biggest win / loss
    win_loss_lines = ["🏆 <b>Biggest win / loss (24h)</b>"]
    if data["top_win"]:
        w = data["top_win"]
        win_loss_lines.append(
            f"🥇 +${(w.get('pnl_usd') or 0):.2f} — <i>{_esc((w.get('market_question') or '?')[:70])}</i>"
        )
    else:
        win_loss_lines.append("🥇 No wins logged in the last 24h.")
    if data["top_loss"]:
        l = data["top_loss"]
        win_loss_lines.append(
            f"🪦 ${(l.get('pnl_usd') or 0):.2f} — <i>{_esc((l.get('market_question') or '?')[:70])}</i>"
        )
    else:
        win_loss_lines.append("🪦 No losses logged — or nothing closed yet.")
    win_loss = "\n".join(win_loss_lines)

    # Theses
    thesis_lines = ["📋 <b>Theses on the board</b>"]
    if data["active_theses"]:
        for t in data["active_theses"]:
            conv = (t.get("conviction") or "?").upper()
            title = _esc((t.get("title") or t.get("id") or "?")[:80])
            thesis_lines.append(f"• [{conv}] {title}")
    else:
        thesis_lines.append("• (no active theses — agent hasn't spotted a multi-cycle story)")
    theses = "\n".join(thesis_lines)

    # Moonshots
    moonshot_lines = ["🚀 <b>Moonshots live</b>"]
    if data["moonshots_live"]:
        for m in data["moonshots_live"][:5]:
            q = _esc((m.get("market_question") or "?")[:60])
            price = float(m.get("price", 0) or 0)
            amt = float(m.get("amount_usd", 0) or 0)
            payoff = (100 / price) if price > 0 else 0
            moonshot_lines.append(f"• {q} @ {price:.2f}c — ${amt:.2f} stake, {payoff:.0f}x payoff if it hits")
    else:
        moonshot_lines.append("• No moonshots open right now. The book is boring. Fix this today.")
    moonshots = "\n".join(moonshot_lines)

    # Watchlist + take
    extras_lines = []
    if data["watchlist"]:
        extras_lines.append(f"👀 <b>Watchlist</b>\n{_esc(data['watchlist'])}")
    if data["last_take"]:
        take = data["last_take"]
        if len(take) > 800:
            take = take[:800].rstrip() + "…"
        extras_lines.append(f"🎤 <b>Trader's take</b>\n{_esc(take)}")
    extras = "\n\n".join(extras_lines) if extras_lines else ""

    messages = [headline, scoreboard, win_loss, theses, moonshots]
    if extras:
        messages.append(extras)
    return messages


def _archive(data: Dict):
    try:
        SUMMARY_JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SUMMARY_JOURNAL_PATH, "a") as f:
            f.write(json.dumps(data, default=str) + "\n")
    except Exception as e:
        logger.warning(f"Daily summary archive failed: {e}")


async def run_daily_summary():
    """Orchestrate: generate, archive, send to Telegram."""
    try:
        data = generate_daily_summary()
        _archive(data)
        messages = format_for_telegram(data)
        for msg in messages:
            await send_telegram(msg)
        logger.info(f"Daily summary sent: 24h P&L ${data['pnl_24h']['pnl_usd']:.2f}, {len(messages)} messages")
    except Exception as e:
        logger.error(f"Daily summary failed: {e}")
