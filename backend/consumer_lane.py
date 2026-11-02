"""
Consumer-trend lane (paper) — docs/research/camillo-social-arbitrage.md

Camillo-style social arbitrage, judgement-first: the daily consumer sentinel
(scripts/consumer_sentinel.sh, headless Claude on the host) reads consumer
signals, judges "needle mover vs company size" and "already priced?", and
records a falsifiable thesis here. This module only stores, validates and
scores — it never alerts and never trades.

Why no mechanical trigger: Wikipedia attention spikes showed no edge
(n=157, all t<1.5). Edge, if any, is in the judgement, which only a live
track record can test. Promotion bar: n>=20 complete theses, clearly
positive d60 excess. Dashboard only; no Telegram until then.

CLI (used by the sentinel via `docker exec polymarket-insider python -m backend.consumer_lane ...`):
  check TICKER [WIKI_ARTICLE]   -> price, market cap, revenue, pre-20d excess, wiki attention ratio
  add '<json>'                  -> validate + append THESIS / WATCH record
  status                        -> scored journal (same as /api/consumer/status)
"""
import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

JOURNAL_PATH = Path("data/consumer_theses.jsonl")
HORIZONS = (20, 60)
DEDUPE_DAYS = 60
WIKI_UA = "polymarket-insider-research/1.0 (joris@jorisfalter.com)"

REQUIRED_THESIS = ("ticker", "company", "trend", "direction", "thesis",
                   "needle_mover", "info_parity", "invalidation", "confidence")


def _read_journal() -> list:
    if not JOURNAL_PATH.exists():
        return []
    out = []
    for line in JOURNAL_PATH.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append(record: dict):
    record["ts"] = datetime.now(timezone.utc).isoformat()
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _history(tickers: list, start: str):
    import yfinance as yf
    return yf.download(tickers, start=start, interval="1d", group_by="ticker",
                       progress=False, auto_adjust=True, threads=True)


def _closes(df, ticker):
    try:
        return df[ticker]["Close"].dropna()
    except (KeyError, TypeError):
        return None


def wiki_ratio(article: str):
    """7-day mean views / median of the 90 days before (lagged 7d)."""
    import httpx
    end = datetime.now(timezone.utc) - timedelta(days=1)
    start = end - timedelta(days=110)
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/"
           f"all-access/user/{article}/daily/{start:%Y%m%d}/{end:%Y%m%d}")
    r = httpx.get(url, headers={"User-Agent": WIKI_UA}, timeout=20)
    if r.status_code != 200:
        return None
    v = [i["views"] for i in r.json().get("items", [])]
    if len(v) < 40:
        return None
    base = statistics.median(v[-97:-7]) or 1
    return {"last7_avg": round(sum(v[-7:]) / 7), "baseline_median": base,
            "ratio": round(sum(v[-7:]) / 7 / base, 2)}


def check(ticker: str, article: str = None) -> dict:
    """Context the sentinel needs for the needle-mover and info-parity calls."""
    import yfinance as yf
    t = ticker.upper()
    out = {"ticker": t}
    try:
        info = yf.Ticker(t).info or {}
        out.update({
            "name": info.get("longName") or info.get("shortName"),
            "market_cap": info.get("marketCap"),
            "revenue_ttm": info.get("totalRevenue"),
            "currency": info.get("financialCurrency") or info.get("currency"),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        })
    except Exception as e:
        out["info_error"] = str(e)[:120]
    start = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
    df = _history([t, "SPY"], start)
    c, spy = _closes(df, t), _closes(df, "SPY")
    if c is not None and len(c) > 21 and spy is not None and len(spy) > 21:
        out["pre20_excess_pct"] = round(
            (c.iloc[-1] / c.iloc[-21] - spy.iloc[-1] / spy.iloc[-21]) * 100, 2)
    if article:
        out["wiki"] = wiki_ratio(article)
    return out


def add(rec: dict) -> dict:
    """Validate and append. Returns {"ok": bool, ...}."""
    action = rec.get("action", "thesis")
    if action not in ("thesis", "watch"):
        return {"ok": False, "error": "action must be 'thesis' or 'watch'"}
    if action == "thesis":
        missing = [k for k in REQUIRED_THESIS if rec.get(k) in (None, "")]
        if missing:
            return {"ok": False, "error": f"missing fields: {missing}"}
        if rec["direction"] not in ("long", "short"):
            return {"ok": False, "error": "direction must be long|short"}
        rec["ticker"] = rec["ticker"].upper()
        # One open thesis per ticker: a re-sighting of the same trend is not a
        # new independent bet (same lesson as the gap-alert dedupe).
        cutoff = datetime.now(timezone.utc) - timedelta(days=DEDUPE_DAYS)
        for r in _read_journal():
            if (r.get("event") == "THESIS" and r.get("ticker") == rec["ticker"]
                    and datetime.fromisoformat(r["ts"]) > cutoff):
                rec["event"] = "DUPLICATE"
                rec["duplicate_of"] = r["ts"]
                _append(rec)
                return {"ok": True, "event": "DUPLICATE",
                        "note": f"open thesis on {rec['ticker']} since {r['ts'][:10]}; not counted"}
    rec["event"] = "THESIS" if action == "thesis" else "WATCH"
    _append(rec)
    return {"ok": True, "event": rec["event"]}


def _score(theses: list) -> list:
    """Paper outcome per thesis: entry = close of the first trading day AFTER
    the thesis date (conservative), excess vs SPY, sign-flipped for shorts."""
    if not theses:
        return []
    start = (min(datetime.fromisoformat(t["ts"]) for t in theses)
             - timedelta(days=5)).strftime("%Y-%m-%d")
    tickers = sorted({t["ticker"] for t in theses})
    df = _history(tickers + ["SPY"], start)
    spy = _closes(df, "SPY")
    rows = []
    for t in theses:
        row = {k: t.get(k) for k in ("ts", "ticker", "company", "trend", "direction",
                                     "confidence", "thesis", "invalidation")}
        c = _closes(df, t["ticker"])
        d = datetime.fromisoformat(t["ts"]).date()
        if c is None or spy is None or not len(c):
            row["error"] = "no price data"
            rows.append(row)
            continue
        idx = next((i for i, x in enumerate(c.index) if x.date() > d), None)
        if idx is None:
            rows.append(row)
            continue
        e = c.index[idx]
        si = spy.index.searchsorted(e)
        sign = 1 if t["direction"] == "long" else -1
        row["entry_date"] = str(e.date())
        row["entry_close"] = round(float(c.iloc[idx]), 4)
        for h in HORIZONS:
            if idx + h < len(c) and si + h < len(spy):
                ex = (c.iloc[idx + h] / c.iloc[idx] - spy.iloc[si + h] / spy.iloc[si]) * 100
                row[f"d{h}"] = round(float(ex) * sign, 2)
        last = len(c) - 1
        if last > idx and si + (last - idx) < len(spy):
            ex = (c.iloc[last] / c.iloc[idx] - spy.iloc[si + last - idx] / spy.iloc[si]) * 100
            row["to_date"] = round(float(ex) * sign, 2)
        rows.append(row)
    return rows


def _stats(vals: list) -> dict:
    if not vals:
        return {"n": 0}
    out = {"n": len(vals), "avg": round(statistics.mean(vals), 2),
           "median": round(statistics.median(vals), 2),
           "win_rate": round(sum(v > 0 for v in vals) / len(vals), 2)}
    if len(vals) > 2 and statistics.stdev(vals) > 0:
        out["t"] = round(statistics.mean(vals) / (statistics.stdev(vals) / math.sqrt(len(vals))), 2)
    return out


def get_status() -> dict:
    journal = _read_journal()
    theses = [r for r in journal if r.get("event") == "THESIS"]
    scored = _score(theses)
    return {
        "horizons": HORIZONS,
        "theses": sorted(scored, key=lambda r: r["ts"], reverse=True),
        "watch": [r for r in journal if r.get("event") == "WATCH"][-20:][::-1],
        "duplicates": sum(1 for r in journal if r.get("event") == "DUPLICATE"),
        "stats": {f"d{h}": _stats([r[f"d{h}"] for r in scored if f"d{h}" in r]) for h in HORIZONS},
        "complete": sum(1 for r in scored if f"d{HORIZONS[-1]}" in r),
        "promotion_bar": "n>=20 complete (d60) theses, d60 avg clearly > 0",
    }


def _main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "check" and len(argv) >= 3:
        print(json.dumps(check(argv[2], argv[3] if len(argv) > 3 else None), default=str))
    elif cmd == "add" and len(argv) >= 3:
        res = add(json.loads(argv[2]))
        print(json.dumps(res))
        return 0 if res.get("ok") else 2
    elif cmd == "status":
        print(json.dumps(get_status(), default=str))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
