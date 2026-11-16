"""Sharp-wallet follower (paper) — Polymarket earnings markets.

Why: the EventWaves KPMG wallets kept winning after the article was
published (17/20). Following their bet within 1-10 minutes would have
returned ~+38% per bet. Our old bot never looked at them. See
docs/research/kpmg-auditor-pattern.md.

What it does
- Every minute: fetch new activity of each watched wallet (Data API v2).
- A BUY on an earnings market (title contains "earnings") of at least
  MIN_USDC becomes a SIGNAL. At detection we record the live order book:
  the average fill price for a $FOLLOW_USD follow and the depth available.
- Every 30 minutes: resolve open signals from the CLOB price history
  (>= 0.99 won, <= 0.01 lost) and score a paper follow of $FOLLOW_USD.

Paper only: no orders, no Telegram. Journal is append-only JSONL.
Watchlist: data/sharp_wallets.json (seeded with the 13 EventWaves wallets).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from loguru import logger

DATA = Path(__file__).resolve().parent.parent / "data"
WATCHLIST_PATH = DATA / "sharp_wallets.json"
STATE_PATH = DATA / "sharp_follow_state.json"
JOURNAL_PATH = DATA / "sharp_follow.jsonl"

DATA_API = "https://data-api.polymarket.com/v2"
CLOB = "https://clob.polymarket.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36",
           "Accept": "application/json"}

MIN_USDC = 20.0       # ignore dust buys
FOLLOW_USD = 100.0    # paper follow size per signal
MARKET_FILTER = re.compile(r"earnings", re.I)

# EventWaves, 24 Feb 2026 — wallets named in "KPMG-Audited Companies are Trading Strangely on Polymarket"
SEED = [
    ("0x4038f719b14e1fbacc31be0116605ec6efe07d42", "RandiBabuRandi"),
    ("0x8fa98e6d9b2a5985abbf7edc9035199392e8ab24", "Kaleenbhaiya"),
    ("0x56518fabda5d36ccf514beb058b2a4ec820c7530", "KARLSON1970"),
    ("0x1a1d18b776c297539df61b4f394e3c65d7b051e0", "kundragame"),
    ("0xdd21f5155b3c014328df96e027ce388113aef7ac", "molgum12"),
    ("0x696babd2d70f82096289b008a313ed49aa291638", "orisonpro"),
    ("0x4230f6f33b9b9eef256e77673729a3964ea9252e", "greatfan1983"),
    ("0xd0c03f20489b77e27badd174e753deeacd644135", "Kosamurai"),
    ("0x7d7a4812c6ced10653b67e652aa42e89dce3e192", "perlgrow"),
    ("0x42f1ce163f941d7ba0cd12c501c11a4751794a12", "Youaregu"),
    ("0x202d88e56b512f32194faacd5dfcf77713b83d97", "anon-DASH-1"),
    ("0x60a028937929520ecef00ac8d3b158af93255f2e", "anon-DASH-2"),
    ("0x701e37585fff132e27a5a51c6e778c5c62219013", "anon-current-quarter"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_watchlist() -> List[Dict]:
    if not WATCHLIST_PATH.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        rows = [{"wallet": w, "label": l, "source": "EventWaves KPMG article, 2026-02-24"} for w, l in SEED]
        WATCHLIST_PATH.write_text(json.dumps(rows, indent=1))
    return json.loads(WATCHLIST_PATH.read_text())


def add_wallet(wallet: str, label: str, source: str, markets: str = "any") -> str:
    """Add a wallet named in a claim (news/X/newsletter). Idempotent."""
    wallet = wallet.strip().lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", wallet):
        return f"REJECT: not a 0x address: {wallet}"
    try:
        re.compile(markets)
    except re.error:
        return f"REJECT: bad markets regex: {markets}"
    wl = load_watchlist()
    if any(w["wallet"].lower() == wallet for w in wl):
        return f"EXISTS: {wallet}"
    wl.append({"wallet": wallet, "label": label[:40], "source": source[:300], "markets": markets,
               "added": _now()})
    WATCHLIST_PATH.write_text(json.dumps(wl, indent=1))
    return f"ADDED: {wallet} ({label}) markets={markets}"


def _load_state() -> Dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state: Dict):
    STATE_PATH.write_text(json.dumps(state))


def _append(rec: Dict):
    with JOURNAL_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def _read_journal() -> List[Dict]:
    if not JOURNAL_PATH.exists():
        return []
    out = []
    for line in JOURNAL_PATH.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _book_fill(book: Dict, usd: float):
    """Average price to buy `usd` worth from the asks, and depth (usd) on the book."""
    asks = sorted(((float(a["price"]), float(a["size"])) for a in book.get("asks", [])), key=lambda x: x[0])
    depth = sum(p * s for p, s in asks)
    left, cost, shares = usd, 0.0, 0.0
    for p, s in asks:
        take = min(left, p * s)
        cost += take
        shares += take / p
        left -= take
        if left <= 1e-9:
            break
    avg = cost / shares if shares else None
    return (avg if left <= 1e-6 else None), (asks[0][0] if asks else None), round(depth, 2)


async def poll():
    """Check every watched wallet for new earnings-market buys."""
    wl = load_watchlist()
    state = _load_state()
    seen = {(r.get("wallet"), r.get("token_id")) for r in _read_journal() if r.get("event") == "SIGNAL"}
    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as c:
        for w in wl:
            wallet = w["wallet"]
            last = state.get(wallet)
            if last is None:  # first run: start watching from now, don't replay history
                state[wallet] = int(time.time())
                continue
            try:
                r = await c.get(f"{DATA_API}/activity", params={"user": wallet, "limit": 100, "start": last + 1})
                rows = r.json().get("data", []) if r.status_code == 200 else []
            except Exception as e:
                logger.debug(f"sharp_follow poll {wallet[:10]}: {e}")
                continue
            newest = last
            for t in sorted(rows, key=lambda x: x.get("timestamp", 0)):
                newest = max(newest, int(t.get("timestamp", 0)))
                if t.get("type") != "TRADE" or t.get("side") != "BUY":
                    continue
                # per-wallet market filter: "any", or a regex (default: earnings)
                filt = w.get("markets") or MARKET_FILTER.pattern
                if filt != "any" and not re.search(filt, t.get("title") or "", re.I):
                    continue
                if float(t.get("usdc_size") or 0) < MIN_USDC:
                    continue
                key = (wallet, t.get("token_id"))
                if key in seen:
                    continue  # one signal per wallet x outcome; later adds don't count
                seen.add(key)
                follow_avg = best_ask = depth = None
                try:
                    b = await c.get(f"{CLOB}/book", params={"token_id": t["token_id"]})
                    if b.status_code == 200:
                        follow_avg, best_ask, depth = _book_fill(b.json(), FOLLOW_USD)
                except Exception:
                    pass
                m = re.search(r"\(([A-Z.]{1,6})\)", t.get("title") or "")
                rec = {
                    "event": "SIGNAL", "ts": _now(), "wallet": wallet, "label": w.get("label"),
                    "title": t.get("title"), "ticker": m.group(1) if m else None,
                    "condition_id": t.get("condition_id"), "token_id": t.get("token_id"),
                    "outcome": t.get("outcome"), "their_price": t.get("price"),
                    "their_usdc": t.get("usdc_size"), "their_ts": t.get("timestamp"),
                    "delay_s": int(time.time()) - int(t.get("timestamp", 0)),
                    "follow_avg_price": follow_avg, "best_ask": best_ask, "book_depth_usd": depth,
                }
                _append(rec)
                logger.info(f"sharp_follow SIGNAL {w.get('label')}: {t.get('title')} {t.get('outcome')} "
                            f"${t.get('usdc_size'):.0f} @ {t.get('price')} (follow avg {follow_avg})")
            state[wallet] = newest
    _save_state(state)


async def resolve():
    """Score open signals once their market resolved."""
    j = _read_journal()
    done = {r["token_id"] for r in j if r.get("event") == "RESOLVED"}
    open_sig = {r["token_id"]: r for r in j if r.get("event") == "SIGNAL" and r["token_id"] not in done}
    if not open_sig:
        return
    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as c:
        for tok, s in open_sig.items():
            t0 = int(s.get("their_ts") or 0)
            end = min(int(time.time()), t0 + 14 * 86400)
            try:
                r = await c.get(f"{CLOB}/prices-history",
                                params={"market": tok, "startTs": t0, "endTs": end, "fidelity": 60})
                hist = r.json().get("history", []) if r.status_code == 200 else []
            except Exception:
                continue
            if not hist:
                continue
            p = float(hist[-1]["p"])
            if 0.01 < p < 0.99:
                continue
            _append({"event": "RESOLVED", "ts": _now(), "token_id": tok, "won": p >= 0.99, "final_price": p})


def _paper(sig: Dict, won: bool) -> Optional[float]:
    price = sig.get("follow_avg_price") or sig.get("their_price")
    if not price:
        return None
    return round(FOLLOW_USD / float(price) - FOLLOW_USD if won else -FOLLOW_USD, 2)


def get_status() -> Dict:
    j = _read_journal()
    res = {r["token_id"]: r for r in j if r.get("event") == "RESOLVED"}
    sigs = []
    for s in (r for r in j if r.get("event") == "SIGNAL"):
        r = res.get(s["token_id"])
        row = dict(s)
        if r:
            row["won"] = r["won"]
            row["paper_pnl"] = _paper(s, r["won"])
        sigs.append(row)
    sigs.sort(key=lambda x: x.get("ts", ""), reverse=True)
    done = [s for s in sigs if "won" in s]
    pnl = [s["paper_pnl"] for s in done if s.get("paper_pnl") is not None]
    return {
        "watching": len(load_watchlist()),
        "follow_usd": FOLLOW_USD,
        "signals": sigs[:100],
        "n_signals": len(sigs),
        "n_resolved": len(done),
        "won": sum(1 for s in done if s["won"]),
        "paper_pnl_usd": round(sum(pnl), 2),
        "paper_return_pct": round(sum(pnl) / (FOLLOW_USD * len(pnl)) * 100, 1) if pnl else None,
    }


if __name__ == "__main__":
    import asyncio, sys
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print(json.dumps(get_status(), indent=1, default=str)[:4000])
    elif len(sys.argv) > 1 and sys.argv[1] == "add":
        # python -m backend.sharp_follow add <0xwallet> <label> <source> [markets-regex|any]
        if len(sys.argv) < 5:
            sys.exit("usage: add <0xwallet> <label> <source> [markets-regex|any]")
        print(add_wallet(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else "any"))
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        for w in load_watchlist():
            print(w["wallet"], w.get("label"), w.get("markets", "earnings"), "|", w.get("source", "")[:80])
    else:
        asyncio.run(poll())
        asyncio.run(resolve())
        print(json.dumps({k: v for k, v in get_status().items() if k != "signals"}, indent=1))
