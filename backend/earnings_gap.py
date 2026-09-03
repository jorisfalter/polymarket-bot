"""
Earnings-Gap Drift alert (PEAD) — docs/research/earnings-gap-drift.md

Backtest 2022-2026 (n=266): gap-up >=5% in liquid US tech -> +1.61% over the
next 3 trading days from gap-day close (t=2.88), +1.19% excess over universe
drift. Long-only: down-gaps bounce, never short. Bigger gaps aren't better.

This module only ALERTS (stocks board = manual execution):
  - Daily after US close: scan universe + stocks watchlist for >=5% overnight
    gaps -> Telegram with the playbook script.
  - Follow-up: 3 trading days after each alert, report the hypothetical
    result (close->close) so we learn whether the edge holds live.

Journal: data/earnings_gap_alerts.jsonl (ALERT + OUTCOME records).
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path("data/earnings_gap_alerts.jsonl")

# Liquid US tech — the backtested universe. The stocks watchlist is merged in
# at runtime (Sandisk-pattern shortlist, data/stocks_watchlist.json).
UNIVERSE = ["NVDA", "META", "MSFT", "GOOGL", "AMZN", "TSLA", "AMD", "AVGO",
            "NFLX", "SMCI", "PLTR", "CRM", "ORCL", "MU", "QCOM"]


def _read_journal() -> list:
    if not JOURNAL_PATH.exists():
        return []
    out = []
    for line in JOURNAL_PATH.read_text().strip().split("\n"):
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append_journal(record: dict):
    record["ts"] = datetime.now(timezone.utc).isoformat()
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _download_history(tickers: list):
    """Blocking yfinance batch download — call via asyncio.to_thread."""
    import yfinance as yf
    return yf.download(tickers, period="1mo", interval="1d",
                       group_by="ticker", progress=False, auto_adjust=True,
                       threads=True)


class EarningsGapAlerter:

    async def run_daily_check(self, notify: bool = True) -> dict:
        """After US close: alert on fresh >=5% gap-ups, report due outcomes."""
        if not settings.earnings_gap_enabled:
            return {"status": "disabled"}

        from .stocks_data import get_watchlist
        try:
            watchlist = [t.upper() for t in get_watchlist()]
        except Exception:
            watchlist = []
        tickers = sorted(set(UNIVERSE) | set(watchlist))

        try:
            data = await asyncio.to_thread(_download_history, tickers)
        except Exception as e:
            logger.warning(f"earnings_gap: yfinance download failed: {e}")
            return {"status": "error", "error": str(e)}

        journal = _read_journal()
        already = {(r["ticker"], r["date"]) for r in journal if r.get("event") == "ALERT"}

        alerts, frames = [], {}
        for tik in tickers:
            try:
                df = data[tik].dropna(subset=["Close"])
            except (KeyError, TypeError):
                continue
            if len(df) < 2:
                continue
            frames[tik] = df
            gap = df["Open"].iloc[-1] / df["Close"].iloc[-2] - 1
            day = df["Close"].iloc[-1] / df["Open"].iloc[-1] - 1
            date = df.index[-1].strftime("%Y-%m-%d")
            if gap * 100 >= settings.earnings_gap_threshold_pct and (tik, date) not in already:
                alerts.append({"event": "ALERT", "ticker": tik, "date": date,
                               "gap_pct": round(gap * 100, 2),
                               "intraday_pct": round(day * 100, 2),
                               "entry_close": round(float(df["Close"].iloc[-1]), 2)})

        outcomes = self._due_outcomes(journal, frames)

        for a in alerts:
            _append_journal(a)
        for o in outcomes:
            _append_journal(o)

        if notify and (alerts or outcomes):
            await self._notify(alerts, outcomes)

        return {"status": "ok", "scanned": len(tickers),
                "alerts": alerts, "outcomes": outcomes}

    def _due_outcomes(self, journal: list, frames: dict) -> list:
        """ALERTs >= hold_days trading days old without an OUTCOME yet."""
        done = {(r["ticker"], r["date"]) for r in journal if r.get("event") == "OUTCOME"}
        out = []
        for r in journal:
            if r.get("event") != "ALERT" or (r["ticker"], r["date"]) in done:
                continue
            df = frames.get(r["ticker"])
            if df is None:
                continue
            later = df[df.index.strftime("%Y-%m-%d") > r["date"]]
            if len(later) < settings.earnings_gap_hold_days:
                continue  # not enough trading days passed yet
            exit_close = float(later["Close"].iloc[settings.earnings_gap_hold_days - 1])
            ret = exit_close / r["entry_close"] - 1
            out.append({"event": "OUTCOME", "ticker": r["ticker"], "date": r["date"],
                        "entry_close": r["entry_close"], "exit_close": round(exit_close, 2),
                        "return_pct": round(ret * 100, 2),
                        "hold_days": settings.earnings_gap_hold_days})
        return out

    async def _notify(self, alerts: list, outcomes: list):
        from .integrations import send_telegram
        lines = []
        if alerts:
            lines.append("📊 <b>Earnings-gap alert</b>")
            for a in alerts:
                lines.append(f"<b>{a['ticker']}</b> gap {a['gap_pct']:+.1f}%, "
                             f"intraday {a['intraday_pct']:+.1f}%, close ${a['entry_close']:,.2f}")
            lines.append("<i>Script: koop close/morgen open, verkoop na "
                         f"{settings.earnings_gap_hold_days} handelsdagen. Long-only, klein sizen "
                         "(backtest: +1.6% gem, 59% winrate).</i>")
        if outcomes:
            if alerts:
                lines.append("")
            lines.append("📊 <b>Earnings-gap resultaat</b> (hypothetisch, close→close)")
            for o in outcomes:
                emoji = "✅" if o["return_pct"] > 0 else "❌"
                lines.append(f"{emoji} <b>{o['ticker']}</b> ({o['date']}): "
                             f"${o['entry_close']:,.2f} → ${o['exit_close']:,.2f} "
                             f"= {o['return_pct']:+.1f}% na {o['hold_days']}d")
            # Rolling live stats — every result arrives in its historical
            # context (backtest baseline: 59% winrate, +1.6% avg).
            s = self.get_status()["stats"]
            if s["n"]:
                lines.append(f"<i>Live totaal: {s['wins']}/{s['n']} winst, "
                             f"gem {s['avg_return_pct']:+.2f}% "
                             f"(backtest: 59%, +1.6%)</i>")
        await send_telegram("\n".join(lines))

    def get_status(self) -> dict:
        journal = _read_journal()
        outcomes = [r for r in journal if r.get("event") == "OUTCOME"]
        wins = sum(1 for o in outcomes if o["return_pct"] > 0)
        return {
            "enabled": settings.earnings_gap_enabled,
            "threshold_pct": settings.earnings_gap_threshold_pct,
            "alerts": [r for r in journal if r.get("event") == "ALERT"][-25:],
            "outcomes": outcomes[-25:],
            "stats": {"n": len(outcomes), "wins": wins,
                      "avg_return_pct": round(sum(o["return_pct"] for o in outcomes) / len(outcomes), 2)
                      if outcomes else None},
        }


earnings_gap = EarningsGapAlerter()
