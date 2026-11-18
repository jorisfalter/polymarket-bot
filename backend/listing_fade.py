"""Listing-pump fade (paper) — short a coin on Hyperliquid after a CEX spot listing.

Why: backtest Apr-Nov 2026 (docs/research/listing-pump-fade.md): after a spot-listing
announcement (mostly Upbit) the coin pumps ~+12% within the hour, then gives it back.
Short at the open of the first full hour after the announcement, hold 24h, hedge with
BTC: +7.1% mean after funding and 0.25% costs, 18/21 episodes won (t=3.3); +8.1% vs a
basket of other alts shorted at the same moment (t=3.9). Small n, one regime: paper only.

Rules (identical to the backtest)
- Event: `spot_listing` in cryptolisting.ws/data/recent-announcements.json, any CEX,
  ticker has a Hyperliquid perp. Same coin within 3 days = one episode.
- Entry: first full hour after detection, paper short $NOTIONAL at the Hyperliquid mid,
  long the same notional of BTC (market-neutral).
- Exit: entry + 24h. P&L = short leg + BTC leg + funding received by shorts - COST_PCT.

Paper only: no orders, no Telegram. Journal: data/listing_fade.jsonl (append-only).
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
JOURNAL = DATA / "listing_fade.jsonl"
FEED = "https://cryptolisting.ws/data/recent-announcements.json"
HL = "https://api.hyperliquid.xyz/info"
UPBIT = "https://api-manager.upbit.com/api/v1/announcements"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36"}

NOTIONAL = 100.0
COST_PCT = 0.25
HOLD_H = 24
STOP_PCT = 20.0  # close the short if the coin rises 20% above entry (2-year backtest: squeezes up to -122%)
EPISODE_GAP_MS = 3 * 86400_000
MAX_EVENT_AGE_MS = 45 * 60_000  # only act on fresh announcements (the feed keeps months)
ALIASES = {"MANTRA": "OM"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> List[Dict]:
    if not JOURNAL.exists():
        return []
    out = []
    for line in JOURNAL.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def _append(rec: Dict):
    DATA.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a") as f:
        f.write(json.dumps(rec) + "\n")


async def _hl(c: httpx.AsyncClient, body: Dict):
    r = await c.post(HL, json=body)
    r.raise_for_status()
    return r.json()


def _coin(ticker: str, universe: set) -> Optional[str]:
    t = ALIASES.get(ticker, ticker)
    if t in universe:
        return t
    if "k" + t in universe:
        return "k" + t
    return None


async def run_cycle():
    """Detect new listings, open due paper shorts, close shorts after HOLD_H."""
    j = _read()
    seen = {r["event_id"] for r in j if r.get("event") == "DETECTED"}
    entered = {r["event_id"] for r in j if r.get("event") == "ENTER"}
    exited = {r["event_id"] for r in j if r.get("event") == "EXIT"}
    now_ms = int(time.time() * 1000)
    async with httpx.AsyncClient(timeout=20, headers=UA) as c:
        try:
            meta = await _hl(c, {"type": "meta"})
            universe = {a["name"] for a in meta["universe"]}
            mids = {k: float(v) for k, v in (await _hl(c, {"type": "allMids"})).items()}
        except Exception as e:
            logger.warning(f"listing_fade: hyperliquid unavailable: {e}")
            return

        # 1. detect
        try:
            feed = (await c.get(FEED)).json()
            events = next(v for v in feed.values() if isinstance(v, list))
        except Exception as e:
            logger.warning(f"listing_fade: feed unavailable: {e}")
            events = []
        # Upbit's own notices: the aggregator misses some Upbit listings
        try:
            r = await c.get(UPBIT, params={"os": "web", "page": 1, "per_page": 20, "category": "trade"})
            for n in r.json()["data"]["notices"]:
                t = n.get("title", "")
                if not re.search(r"신규 거래지원|디지털 자산 추가", t) or "취소" in t:
                    continue
                us = int(datetime.fromisoformat(n["first_listed_at"]).timestamp() * 1_000_000)
                for tk in re.findall(r"\(([A-Z0-9]{2,12})\)", t):
                    events.append({"cex": "upbit", "ticker": tk, "type": "spot_listing", "detected_at_us": us})
        except Exception as e:
            logger.debug(f"listing_fade: upbit notices unavailable: {e}")
        last_coin = {}
        for r in j:
            if r.get("event") == "DETECTED":
                last_coin[r["coin"]] = max(last_coin.get(r["coin"], 0), r["detected_ms"])
        for ev in sorted(events, key=lambda x: x.get("detected_at_us", 0)):
            if ev.get("type") != "spot_listing":
                continue
            eid = f"{ev.get('cex')}:{ev.get('ticker')}:{ev.get('detected_at_us')}"
            t0 = int(ev.get("detected_at_us", 0)) // 1000
            if eid in seen or now_ms - t0 > MAX_EVENT_AGE_MS:
                continue
            coin = _coin(ev.get("ticker", ""), universe)
            if not coin:
                continue
            if t0 - last_coin.get(coin, 0) < EPISODE_GAP_MS:
                continue  # same coin listed elsewhere within 3 days: one episode
            last_coin[coin] = t0
            entry_due = (t0 // 3600_000 + 1) * 3600_000
            _append({"event": "DETECTED", "ts": _now(), "event_id": eid, "cex": ev.get("cex"),
                     "ticker": ev.get("ticker"), "coin": coin, "detected_ms": t0,
                     "entry_due_ms": entry_due, "mid_at_detect": mids.get(coin)})
            logger.info(f"listing_fade DETECTED {coin} ({ev.get('cex')}), short due at "
                        f"{datetime.fromtimestamp(entry_due / 1000, timezone.utc):%H:%M} UTC")
        j = _read()

        # 2. enter
        for r in (x for x in j if x.get("event") == "DETECTED" and x["event_id"] not in entered):
            if now_ms < r["entry_due_ms"]:
                continue
            if now_ms - r["entry_due_ms"] > 15 * 60_000:
                _append({"event": "SKIPPED", "ts": _now(), "event_id": r["event_id"],
                         "reason": "entry window missed (app down?)"})
                entered.add(r["event_id"])
                continue
            px, btc = mids.get(r["coin"]), mids.get("BTC")
            if not px or not btc:
                continue
            _append({"event": "ENTER", "ts": _now(), "event_id": r["event_id"], "coin": r["coin"],
                     "entry_ms": now_ms, "entry_px": px, "btc_px": btc,
                     "pump_pct": round((px / r["mid_at_detect"] - 1) * 100, 2) if r.get("mid_at_detect") else None})
            logger.info(f"listing_fade ENTER paper short {r['coin']} @ {px}")

        # 3. exit
        for r in (x for x in _read() if x.get("event") == "ENTER" and x["event_id"] not in exited):
            px, btc = mids.get(r["coin"]), mids.get("BTC")
            if not px or not btc:
                continue
            stopped = px >= r["entry_px"] * (1 + STOP_PCT / 100)
            if now_ms < r["entry_ms"] + HOLD_H * 3600_000 and not stopped:
                continue
            try:
                fh = await _hl(c, {"type": "fundingHistory", "coin": r["coin"], "startTime": r["entry_ms"],
                                   "endTime": r["entry_ms"] + HOLD_H * 3600_000})
                funding = sum(float(f["fundingRate"]) for f in fh) * 100
            except Exception:
                funding = 0.0
            short = -(px / r["entry_px"] - 1) * 100
            btc_leg = (btc / r["btc_px"] - 1) * 100
            net = short + btc_leg + funding - COST_PCT
            _append({"event": "EXIT", "ts": _now(), "event_id": r["event_id"], "coin": r["coin"],
                     "reason": "stop" if stopped else "24h",
                     "exit_px": px, "btc_exit_px": btc, "short_pct": round(short, 2),
                     "btc_leg_pct": round(btc_leg, 2), "funding_pct": round(funding, 3),
                     "net_pct": round(net, 2), "pnl_usd": round(NOTIONAL * net / 100, 2)})
            logger.info(f"listing_fade EXIT {r['coin']}: net {net:+.2f}%")


def get_status() -> Dict:
    j = _read()
    det = {r["event_id"]: r for r in j if r.get("event") == "DETECTED"}
    ent = {r["event_id"]: r for r in j if r.get("event") == "ENTER"}
    ex = {r["event_id"]: r for r in j if r.get("event") == "EXIT"}
    rows = []
    for eid, d in det.items():
        row = {k: d.get(k) for k in ("coin", "cex", "ticker", "ts")}
        row.update({k: ent[eid].get(k) for k in ("entry_px", "pump_pct")} if eid in ent else {})
        row.update({k: ex[eid].get(k) for k in ("net_pct", "pnl_usd")} if eid in ex else {})
        row["state"] = "closed" if eid in ex else "open" if eid in ent else "pending"
        rows.append(row)
    nets = [r["net_pct"] for r in ex.values()]
    return {
        "notional_usd": NOTIONAL, "hold_h": HOLD_H, "n_detected": len(det), "n_closed": len(nets),
        "won": sum(1 for x in nets if x > 0),
        "mean_net_pct": round(sum(nets) / len(nets), 2) if nets else None,
        "pnl_usd": round(sum(r["pnl_usd"] for r in ex.values()), 2),
        "backtest": "Upbit Aug 2024-Nov 2026 (4h, 20% stop): n=76, +4.4%/episode, 55/76 won, t=3.0; "
                    "Apr-Nov 2026 (1h): n=21, +7.1%, 18/21",
        "episodes": sorted(rows, key=lambda r: r.get("ts") or "", reverse=True)[:50],
    }


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_cycle())
    print(json.dumps({k: v for k, v in get_status().items() if k != "episodes"}, indent=1))
