"""
Hypothetical P&L backtest for stock signals — answer the question
"if we'd bought $100 of the ticker on every signal we detected, how
would we have done at 7/30/60/90 day holds?"

Used to decide which signal types (politician buys, Form 4 insider buys,
13D, audit-cluster, WSB) deserve real money via the planned IBKR
integration. No real orders here — analysis only.

Reuses _price_history / _close_at from stocks_data (yfinance with 24h
disk cache).
"""
from __future__ import annotations
import asyncio
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict
from loguru import logger

from .stocks_data import _price_history, _close_at


HOLD_HORIZONS_DAYS = [7, 30, 60, 90]
BENCHMARK = "SPY"
NOTIONAL_USD = 100.0


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------

@dataclass
class Signal:
    """A single detected signal that could have triggered a trade."""
    signal_date: str          # YYYY-MM-DD — when we'd have acted
    ticker: str
    signal_type: str          # "politician_buy" | "form4_buy" | "13d" | "audit_cluster" | "wsb_buzz"
    source: str = ""          # e.g. "Nancy Pelosi" or "CEO of XYZ"
    raw_size: str = ""        # optional descriptive size for reporting (e.g. "50K-100K")


@dataclass
class TradeResult:
    signal: Signal
    horizon_days: int
    buy_date: Optional[str] = None
    buy_price: Optional[float] = None
    sell_date: Optional[str] = None
    sell_price: Optional[float] = None
    return_pct: Optional[float] = None
    spy_return_pct: Optional[float] = None
    alpha_pct: Optional[float] = None
    skip_reason: Optional[str] = None


# -----------------------------------------------------------------------------
# Per-signal backtest
# -----------------------------------------------------------------------------

async def backtest_signal(
    sig: Signal, horizon_days: int, today_iso: Optional[str] = None,
) -> TradeResult:
    """Compute hypothetical trade outcome for one signal × horizon."""
    today_iso = today_iso or date.today().isoformat()
    sell_target_iso = (date.fromisoformat(sig.signal_date) + timedelta(days=horizon_days)).isoformat()

    # Need enough forward data for the hold window
    if sell_target_iso > today_iso:
        return TradeResult(sig, horizon_days, skip_reason="hold horizon extends past today")

    prices = await _price_history(sig.ticker, days=400)
    if not prices:
        return TradeResult(sig, horizon_days, skip_reason=f"no price history for {sig.ticker}")

    # Buy on next available trading day on/after signal
    buy_price = _close_at(prices, sig.signal_date)
    if buy_price is None:
        return TradeResult(sig, horizon_days, skip_reason="no price on/after signal date")
    buy_row = next(r for r in prices if r["close"] == buy_price and r["date"] >= sig.signal_date)
    sell_price = _close_at(prices, sell_target_iso)
    if sell_price is None:
        return TradeResult(sig, horizon_days, buy_date=buy_row["date"], buy_price=buy_price,
                           skip_reason="no price on/after sell target")
    sell_row = next(r for r in prices if r["close"] == sell_price and r["date"] >= sell_target_iso)
    return_pct = (sell_price - buy_price) / buy_price * 100

    # SPY benchmark over the same window
    spy_prices = await _price_history(BENCHMARK, days=400)
    spy_return_pct = None
    alpha_pct = None
    if spy_prices:
        spy_buy = _close_at(spy_prices, sig.signal_date)
        spy_sell = _close_at(spy_prices, sell_target_iso)
        if spy_buy and spy_sell:
            spy_return_pct = (spy_sell - spy_buy) / spy_buy * 100
            alpha_pct = return_pct - spy_return_pct

    return TradeResult(
        signal=sig, horizon_days=horizon_days,
        buy_date=buy_row["date"], buy_price=buy_price,
        sell_date=sell_row["date"], sell_price=sell_price,
        return_pct=return_pct, spy_return_pct=spy_return_pct, alpha_pct=alpha_pct,
    )


# -----------------------------------------------------------------------------
# Batch runner + summary
# -----------------------------------------------------------------------------

async def backtest_all(signals: List[Signal]) -> List[TradeResult]:
    """Run backtest_signal for every (signal × horizon). Sequential to
    respect yfinance rate-limits; cache makes repeats cheap."""
    out: List[TradeResult] = []
    for i, sig in enumerate(signals):
        for h in HOLD_HORIZONS_DAYS:
            r = await backtest_signal(sig, h)
            out.append(r)
        if (i + 1) % 25 == 0:
            logger.info(f"backtest progress: {i+1}/{len(signals)} signals")
    return out


def summarize(results: List[TradeResult]) -> Dict:
    """Group by (signal_type, horizon) and compute hit rate / mean alpha
    / Sharpe-analog. Skips entries with no return."""
    grouped: Dict[tuple, List[TradeResult]] = defaultdict(list)
    skipped: Dict[str, int] = defaultdict(int)
    for r in results:
        if r.return_pct is None:
            skipped[r.skip_reason or "unknown"] += 1
            continue
        grouped[(r.signal.signal_type, r.horizon_days)].append(r)

    summary: Dict[str, Dict] = {}
    for (sig_type, horizon), rows in sorted(grouped.items()):
        returns = [r.return_pct for r in rows]
        alphas = [r.alpha_pct for r in rows if r.alpha_pct is not None]
        sharpe = (statistics.mean(returns) / statistics.stdev(returns)) if len(returns) > 1 and statistics.stdev(returns) > 0 else 0.0
        summary[f"{sig_type}@{horizon}d"] = {
            "signal_type": sig_type,
            "horizon_days": horizon,
            "n": len(rows),
            "hit_rate_pct": round(sum(1 for x in returns if x > 0) / len(returns) * 100, 1),
            "mean_return_pct": round(statistics.mean(returns), 2),
            "median_return_pct": round(statistics.median(returns), 2),
            "mean_alpha_pct": round(statistics.mean(alphas), 2) if alphas else None,
            "stdev_return_pct": round(statistics.stdev(returns), 2) if len(returns) > 1 else 0,
            "sharpe_analog": round(sharpe, 2),
            "best_return_pct": round(max(returns), 2),
            "worst_return_pct": round(min(returns), 2),
            "total_pnl_per_100usd": round(sum(returns), 2),  # cumulative if we bet $100 each time
        }
    return {"summary": summary, "skipped": dict(skipped)}


# -----------------------------------------------------------------------------
# Signal source — pull live politician trades from Firecrawl
# -----------------------------------------------------------------------------

async def politician_signals(politicians: List[str], min_date: Optional[str] = None) -> List[Signal]:
    """Pull recent trades for the named politicians via Firecrawl/CapitolTrades.
    Filters to BUY transactions only (we're testing the long-side hypothesis)."""
    from .congress_scraper import fetch_watched_politicians_firecrawl
    trades = await fetch_watched_politicians_firecrawl(politicians)
    out: List[Signal] = []
    for t in trades:
        # Scraper normalizes type to "buy"|"sell"|"exchange"|"receive".
        if (t.get("type") or "").lower() not in ("buy", "purchase"):
            continue
        td = t.get("transaction_date") or ""
        if min_date and td < min_date:
            continue
        ticker = (t.get("ticker") or "").upper().strip()
        if not ticker or ticker in ("NA", "N/A", "-"):
            continue
        out.append(Signal(
            signal_date=td,
            ticker=ticker,
            signal_type="politician_buy",
            source=t.get("representative") or "",
            raw_size=str(t.get("amount") or ""),
        ))
    return out


# -----------------------------------------------------------------------------
# Pretty-print runner
# -----------------------------------------------------------------------------

def print_table(summary: Dict) -> None:
    """Render the summary as a fixed-width markdown table."""
    print()
    print(f"{'signal_type':<22} {'horiz':>6} {'n':>4} {'hit%':>6} {'mean':>7} {'med':>7} {'alpha':>7} {'stdev':>7} {'sharpe':>7} {'best':>7} {'worst':>7}")
    print("-" * 110)
    for key, row in summary["summary"].items():
        print(f"{row['signal_type']:<22} "
              f"{row['horizon_days']:>5}d "
              f"{row['n']:>4} "
              f"{row['hit_rate_pct']:>5}% "
              f"{row['mean_return_pct']:>6}% "
              f"{row['median_return_pct']:>6}% "
              f"{(row['mean_alpha_pct'] or 0):>6}% "
              f"{row['stdev_return_pct']:>6}% "
              f"{row['sharpe_analog']:>7} "
              f"{row['best_return_pct']:>6}% "
              f"{row['worst_return_pct']:>6}%")
    if summary["skipped"]:
        print()
        print("Skipped:")
        for reason, n in summary["skipped"].items():
            print(f"  {n} × {reason}")


async def main():
    """Default runner — politicians we already scrape."""
    politicians = [
        "Nancy Pelosi", "Markwayne Mullin", "Josh Gottheimer",
        "Tommy Tuberville", "Sheldon Whitehouse", "Dan Crenshaw",
        "Ro Khanna", "Marjorie Taylor Greene", "Suzan Delbene",
        "Mike McCaul", "Diana Harshbarger",
    ]
    # Look back ~6 months but only as far as our forward data lets us
    cutoff = (date.today() - timedelta(days=180)).isoformat()
    logger.info(f"pulling politician signals since {cutoff}…")
    signals = await politician_signals(politicians, min_date=cutoff)
    logger.info(f"got {len(signals)} BUY signals across {len(politicians)} politicians")
    if not signals:
        print("No signals to backtest.")
        return
    results = await backtest_all(signals)
    summary = summarize(results)
    print_table(summary)
    out_path = Path(__file__).parent.parent / "data" / "stock_backtest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "ran_at": datetime.utcnow().isoformat(),
        "n_signals": len(signals),
        "horizons_days": HOLD_HORIZONS_DAYS,
        "notional_usd": NOTIONAL_USD,
        "summary": summary,
    }, indent=2))
    print(f"\nfull results: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
