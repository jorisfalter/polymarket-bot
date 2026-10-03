"""
Gap-momentum alert (historically named "earnings-gap") — docs/research/earnings-gap-drift.md

Backtest 2022-2026: gap-up >=5% -> continuation over 1-10 trading days.
2026-10-03 correction: this is NOT PEAD. Only ~40% of the megacap gaps
coincided with earnings, and the non-earnings gaps did BETTER (d10 +4.9% vs
+2.2%). So we do not filter on earnings; we only label it for analysis.
What does matter (backtest, watchlist n=728): one alert per ticker while its
tranches are open -> d3 excess +1.59% -> +2.19% (t=4.0), d10 +0.81% -> +2.26%.
Long-only: down-gaps bounce, never short.

Counting rules (also applied retroactively to old journal entries):
  - a gap in a ticker that still has open tranches is SUPPRESSED (journaled,
    no Telegram, not counted)
  - EPISODE = independent data point: an earnings gap is always its own
    episode; non-earnings gaps <=EPISODE_DAYS apart chain into one theme
    (e.g. the BTC-miner rally of 16-18 Sep 2026). The promotion count
    (n>=20-30) counts episodes, not alerts

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

SUPPRESS_CAL_DAYS = 15   # ~10 trading days: a ticker's tranches are still open
EPISODE_DAYS = 3         # alerts <=3 calendar days apart chain into one episode


def _days_between(a: str, b: str) -> int:
    return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).days)


def _counted_alerts(alerts: list) -> list:
    """Alerts that count: drop those whose ticker had an earlier counted
    alert within SUPPRESS_CAL_DAYS. Works on old entries too (retroactive)."""
    counted, last = [], {}
    for a in sorted(alerts, key=lambda r: r["date"]):
        if a.get("suppressed"):
            continue
        prev = last.get(a["ticker"])
        if prev and _days_between(prev, a["date"]) <= SUPPRESS_CAL_DAYS:
            continue
        counted.append(a)
        last[a["ticker"]] = a["date"]
    return counted


def _episodes(alerts: list) -> list:
    """Group counted alerts into independent episodes.

    An earnings gap is company-specific news -> always its own episode (NVDA
    and ORCL reporting in the same week are independent). Gaps WITHOUT
    confirmed earnings on nearby days are usually one theme (BTC-miner
    rally) -> chained when <=EPISODE_DAYS apart. Unknown label (None) is
    treated as non-earnings (conservative). Backtest 2024-26: ~75
    episodes/yr with this rule vs ~43 when everything chained (that version
    merged a whole earnings season into one 25-alert episode)."""
    eps, theme = [], []
    for a in sorted(alerts, key=lambda r: r["date"]):
        if a.get("earnings_nearby") is True:
            eps.append([a])
        elif theme and _days_between(theme[-1][-1]["date"], a["date"]) <= EPISODE_DAYS:
            theme[-1].append(a)
        else:
            theme.append([a])
    return sorted(eps + theme, key=lambda ep: ep[0]["date"])


def _earnings_nearby(ticker: str, date: str):
    """Label only (no filter): earnings report within 0-4 days before the
    gap? True/False, None when the lookup fails. Needs lxml."""
    try:
        import yfinance as yf
        ed = yf.Ticker(ticker).get_earnings_dates(limit=12)
        day = datetime.fromisoformat(date)
        return any(0 <= (day - d.tz_localize(None).to_pydatetime()).days <= 4 for d in ed.index)
    except Exception:
        return None


def _read_journal() -> list:
    """Journal is append-only. Labels added later (ALERT_LABEL records, e.g.
    the 2026-10-03 earnings backfill) are merged onto their ALERT here."""
    if not JOURNAL_PATH.exists():
        return []
    out = []
    for line in JOURNAL_PATH.read_text().strip().split("\n"):
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    labels = {(r["ticker"], r["date"]): r for r in out if r.get("event") == "ALERT_LABEL"}
    for r in out:
        lab = labels.get((r.get("ticker"), r.get("date")))
        if r.get("event") == "ALERT" and lab and "earnings_nearby" not in r:
            r["earnings_nearby"] = lab.get("earnings_nearby")
    return out


def backfill_earnings_labels() -> list:
    """One-off/idempotent: label old ALERTs that lack earnings_nearby."""
    done = []
    for r in _read_journal():
        if r.get("event") == "ALERT" and "earnings_nearby" not in r:
            lab = _earnings_nearby(r["ticker"], r["date"])
            _append_journal({"event": "ALERT_LABEL", "ticker": r["ticker"],
                             "date": r["date"], "earnings_nearby": lab})
            done.append((r["ticker"], r["date"], lab))
    return done


def _append_journal(record: dict):
    record["ts"] = datetime.now(timezone.utc).isoformat()
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _download_history(tickers: list):
    """Blocking yfinance batch download — call via asyncio.to_thread."""
    import yfinance as yf
    return yf.download(tickers, period="3mo", interval="1d",
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
        already = {(r["ticker"], r["date"]) for r in journal
                   if r.get("event") in ("ALERT", "GAP_SUPPRESSED")}
        counted_hist = _counted_alerts([r for r in journal if r.get("event") == "ALERT"])

        alerts, suppressed, frames = [], [], {}
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
                rec = {"ticker": tik, "date": date,
                       "gap_pct": round(gap * 100, 2),
                       "intraday_pct": round(day * 100, 2),
                       "entry_close": round(float(df["Close"].iloc[-1]), 2),
                       "source": "universe" if tik in UNIVERSE else "watchlist"}
                open_prev = [a for a in counted_hist if a["ticker"] == tik
                             and _days_between(a["date"], date) <= SUPPRESS_CAL_DAYS]
                if open_prev:
                    suppressed.append({"event": "GAP_SUPPRESSED", **rec,
                                       "reason": f"tranches van {open_prev[-1]['date']} staan nog open"})
                else:
                    alerts.append({"event": "ALERT", **rec})

        for a in alerts:
            a["earnings_nearby"] = await asyncio.to_thread(_earnings_nearby, a["ticker"], a["date"])

        # Only counted alerts get outcomes; old duplicate alerts stay in the
        # journal but are skipped from here on.
        outcomes = self._due_outcomes(journal, frames)

        for a in alerts + suppressed:
            _append_journal(a)
        for o in outcomes:
            _append_journal(o)

        if notify and (alerts or outcomes):
            await self._notify(alerts, outcomes)

        return {"status": "ok", "scanned": len(tickers),
                "alerts": alerts, "suppressed": suppressed, "outcomes": outcomes}

    def _due_outcomes(self, journal: list, frames: dict) -> list:
        """Per ALERT, one OUTCOME per tranche horizon once enough trading
        days have passed. hold_days on the record = the tranche length."""
        done = {(r["ticker"], r["date"], r.get("hold_days"))
                for r in journal if r.get("event") == "OUTCOME"}
        out = []
        for r in _counted_alerts([x for x in journal if x.get("event") == "ALERT"]):
            df = frames.get(r["ticker"])
            if df is None:
                continue
            later = df[df.index.strftime("%Y-%m-%d") > r["date"]]
            for k in settings.earnings_gap_tranches:
                if (r["ticker"], r["date"], k) in done or len(later) < k:
                    continue
                exit_close = float(later["Close"].iloc[k - 1])
                ret = exit_close / r["entry_close"] - 1
                out.append({"event": "OUTCOME", "ticker": r["ticker"], "date": r["date"],
                            "entry_close": r["entry_close"], "exit_close": round(exit_close, 2),
                            "return_pct": round(ret * 100, 2), "hold_days": k})
        return out

    async def _notify(self, alerts: list, outcomes: list):
        from .integrations import send_telegram
        lines = []
        if alerts:
            lines.append("📊 <b>Gap-momentum alert</b>")
            for a in alerts:
                tag = {True: "cijfers", False: "geen cijfers", None: "cijfers ?"}[a.get("earnings_nearby")]
                lines.append(f"<b>{a['ticker']}</b> gap {a['gap_pct']:+.1f}%, "
                             f"intraday {a['intraday_pct']:+.1f}%, close ${a['entry_close']:,.2f} "
                             f"({a['source']}, {tag})")
            themed = [a for a in alerts if a.get("earnings_nearby") is not True]
            if len(themed) > 1:
                lines.append(f"⚠️ {len(themed)} gaps zonder cijfers tegelijk = waarschijnlijk één thema "
                             f"({', '.join(a['ticker'] for a in themed)}); telt als één episode, size kleiner.")
            tr = settings.earnings_gap_tranches
            lines.append(f"<i>Script: koop close/morgen open in 1 keer; verkoop in derden "
                         f"na {', '.join(str(k) for k in tr)} handelsdagen. Long-only, klein sizen.</i>")
        if outcomes:
            if alerts:
                lines.append("")
            lines.append("📊 <b>Gap-momentum resultaat</b> (hypothetisch, close→close)")
            for o in outcomes:
                emoji = "✅" if o["return_pct"] > 0 else "❌"
                lines.append(f"{emoji} <b>{o['ticker']}</b> ({o['date']}): "
                             f"${o['entry_close']:,.2f} → ${o['exit_close']:,.2f} "
                             f"= {o['return_pct']:+.1f}% na {o['hold_days']}d (tranche)")
            # Rolling live stats per tranche — every result arrives in its
            # historical context (backtest excess: d1 +0.8%, d3 +1.2%, d10 +2.6%).
            st = self.get_status()
            parts = [f"verkoop-na-{k}d: {s['wins']} van {s['n']} winst, gem {s['avg_return_pct']:+.1f}%"
                     for k, s in st["stats"].items() if s["n"]]
            if parts:
                lines.append(f"<i>Live score per tranche — {' | '.join(parts)}</i>")
            lines.append(f"<i>Onafhankelijke episodes afgerond: {st['episodes_complete']} "
                         f"(promotie-drempel 20-30)</i>")
        await send_telegram("\n".join(lines))

    def get_status(self) -> dict:
        journal = _read_journal()
        all_alerts = [r for r in journal if r.get("event") == "ALERT"]
        counted = _counted_alerts(all_alerts)
        keys = {(a["ticker"], a["date"]) for a in counted}
        outcomes = [r for r in journal if r.get("event") == "OUTCOME"
                    and (r["ticker"], r["date"]) in keys]
        # Episode view: average each episode's alerts per tranche -> one data
        # point per episode. This is the n that counts for promotion.
        eps = _episodes(counted)
        last_k = max(settings.earnings_gap_tranches)
        per_episode = []
        for ep in eps:
            row = {"start": ep[0]["date"], "tickers": [a["ticker"] for a in ep]}
            for k in settings.earnings_gap_tranches:
                vals = [o["return_pct"] for o in outcomes if o["hold_days"] == k
                        and (o["ticker"], o["date"]) in {(a["ticker"], a["date"]) for a in ep}]
                row[f"d{k}"] = round(sum(vals) / len(vals), 2) if len(vals) == len(ep) else None
            per_episode.append(row)
        complete = [e for e in per_episode if e[f"d{last_k}"] is not None]
        per_tranche = {}
        for k in settings.earnings_gap_tranches:
            sub = [o for o in outcomes if o.get("hold_days") == k]
            per_tranche[k] = {
                "n": len(sub), "wins": sum(1 for o in sub if o["return_pct"] > 0),
                "avg_return_pct": round(sum(o["return_pct"] for o in sub) / len(sub), 2)
                if sub else None,
            }
        return {
            "enabled": settings.earnings_gap_enabled,
            "threshold_pct": settings.earnings_gap_threshold_pct,
            "tranches": settings.earnings_gap_tranches,
            "alerts": all_alerts[-25:],
            "alerts_counted": len(counted),
            "alerts_dropped_as_duplicate": len(all_alerts) - len(counted),
            "suppressed": [r for r in journal if r.get("event") == "GAP_SUPPRESSED"][-25:],
            "outcomes": outcomes[-40:],
            "stats": per_tranche,
            "episodes": per_episode,
            "episodes_complete": len(complete),
        }


earnings_gap = EarningsGapAlerter()
