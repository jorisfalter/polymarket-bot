"""Fresh-wallet conviction backtest (Polymarket, non-sports).

Question: when a brand-new wallet puts >= MIN_USD into one non-sports
market, does following it (1h later, at the then-current price) pay?

Motivation: Ballon d'Or 2026. Wallets created 20 and 22 Oct put $21k and
$25k on the exact #2-#5 ranking, days before the ceremony; a follower could
buy at ~0.70 and every leg paid 1.0. Paris weather, Maduro: same shape.

Method
- All trades >= MIN_USD from the v2 global feed (filter_type=CASH), from
  now back to START. Sports / crypto up-down / esports titles dropped.
- Aggregate BUYs per (wallet, condition, outcome).
- Wallet age at the bet: oldest activity record (<= 500 records; wallets
  with more history are not fresh by definition).
- Fresh = first activity <= FRESH_DAYS before the bet.
- Outcome from CLOB price history of the bought token: last price >= 0.99
  won, <= 0.01 lost, else unresolved (excluded).
- Follow entry = token price ~DELAY_S after the wallet's first buy
  (prices-history fidelity 1 min); return = 1/entry - 1 or -1.
- Baseline: the same stats for NON-fresh wallets' >= MIN_USD bets.

Run: python3 scripts/research/fresh_wallet_backtest.py [out_dir]
"""
import json, re, sys, time, collections, statistics as st, urllib.request, urllib.parse
from datetime import datetime, timezone

START = "2026-08-15"
MIN_USD = 5000
FRESH_DAYS = 7
DELAY_S = 3600
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36",
      "Accept": "application/json"}
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
SPORTS = re.compile(
    r"\bvs\.?\b|O/U|Spread|Up or Down|win on 20\d\d|Exact Score|BO[135]\b|Handicap|Total (?:Goals|Points|Kills|Maps)|"
    r"Both Teams|Moneyline|1H |2H |Map \d|Game \d|Set \d|Draw\?|NBA|NFL|NHL|MLB|UFC|Premier League|Champions League|"
    r"Bitcoin above|Ethereum above|Solana above|XRP above|price of (?:Bitcoin|Ethereum|Solana)|temperature", re.I)


def get(path, q, tries=3):
    url = f"{path}?{urllib.parse.urlencode(q)}"
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                print("ERR", url[:110], e, flush=True)
                return None
            time.sleep(2 * (i + 1))


def ts(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())


def big_trades():
    stop, rows, q = ts(START), [], {"filter_type": "CASH", "filter_amount": MIN_USD, "limit": 500}
    while True:
        j = get("https://data-api.polymarket.com/v2/trades", q)
        if not j or not j.get("data"):
            break
        d = j["data"]
        rows += [t for t in d if t["side"] == "BUY" and not SPORTS.search(t.get("title") or "")]
        oldest = min(t["timestamp"] for t in d)
        if len(rows) % 2000 < 50:
            print(f"  feed at {datetime.fromtimestamp(oldest, timezone.utc):%m-%d}, kept {len(rows)}", flush=True)
        p = j.get("pagination", {})
        if oldest < stop or not p.get("has_more"):
            break
        q["cursor"] = p["next_cursor"]
        time.sleep(0.1)
    return [t for t in rows if t["timestamp"] >= stop]


def wallet_first_seen(w):
    j = get("https://data-api.polymarket.com/v2/activity", {"user": w, "limit": 500})
    if not j or not j.get("data"):
        return None
    if j.get("pagination", {}).get("has_more"):
        return 0  # long history -> not fresh
    return min(r["timestamp"] for r in j["data"])


def price_path(token, t0):
    j = get("https://clob.polymarket.com/prices-history",
            {"market": token, "startTs": t0, "endTs": t0 + 6 * 3600, "fidelity": 1})
    entry = None
    for p in (j or {}).get("history", []):
        if p["t"] >= t0 + DELAY_S:
            entry = float(p["p"])
            break
    # final: last point in a long window
    end = None
    for span in (14, 60, 120):
        k = get("https://clob.polymarket.com/prices-history",
                {"market": token, "startTs": max(t0, int(time.time()) - span * 86400), "endTs": int(time.time()),
                 "fidelity": 60})
        h = (k or {}).get("history", [])
        if h:
            end = float(h[-1]["p"])
            break
    return entry, end


def main():
    tr = big_trades()
    print(f"non-sports BUYs >= ${MIN_USD} since {START}: {len(tr)}", flush=True)
    bets = {}
    for t in sorted(tr, key=lambda x: x["timestamp"]):
        k = (t["proxy_wallet"], t["condition_id"], t["token_id"])
        b = bets.setdefault(k, {"wallet": t["proxy_wallet"], "cond": t["condition_id"], "token": t["token_id"],
                                "title": t["title"], "outcome": t["outcome"], "t0": t["timestamp"], "usd": 0.0, "sh": 0.0})
        b["usd"] += float(t["size"]) * float(t["price"])
        b["sh"] += float(t["size"])
    bets = list(bets.values())
    print(f"wallet x market bets: {len(bets)}; wallets: {len({b['wallet'] for b in bets})}", flush=True)

    seen = {}
    for i, w in enumerate({b["wallet"] for b in bets}):
        seen[w] = wallet_first_seen(w)
        if i % 200 == 0:
            print(f"  wallet ages {i}", flush=True)
    for b in bets:
        fs = seen.get(b["wallet"])
        b["age_days"] = None if fs is None else (999 if fs == 0 else (b["t0"] - fs) / 86400)
        b["fresh"] = b["age_days"] is not None and b["age_days"] <= FRESH_DAYS

    # price paths for all fresh bets + a same-size random sample of non-fresh
    fresh = [b for b in bets if b["fresh"]]
    other = [b for b in bets if not b["fresh"]]
    other = other[:: max(1, len(other) // max(1, 2 * len(fresh)))]
    for i, b in enumerate(fresh + other):
        b["entry"], b["final"] = price_path(b["token"], b["t0"])
        b["their_price"] = b["usd"] / b["sh"] if b["sh"] else None
        if i % 100 == 0:
            print(f"  prices {i}/{len(fresh) + len(other)}", flush=True)
    json.dump(fresh + other, open(f"{OUT}/fresh_bets.json", "w"))

    def stats(name, bs):
        bs = [b for b in bs if b.get("final") is not None and (b["final"] >= 0.99 or b["final"] <= 0.01)
              and b.get("entry") and 0.02 < b["entry"] < 0.98]
        if not bs:
            print(name, "n=0")
            return
        r = [(1 / b["entry"] - 1) if b["final"] >= 0.99 else -1.0 for b in bs]
        won = sum(b["final"] >= 0.99 for b in bs)
        sd = st.pstdev(r) if len(r) > 1 else 0
        print(f"{name}: n={len(bs)} won {won} ({won / len(bs) * 100:.0f}%) mean follow ret {st.mean(r) * 100:+.1f}% "
              f"median {st.median(r) * 100:+.1f}% t={st.mean(r) / (sd / len(r) ** .5) if sd else 0:.1f} "
              f"median entry {st.median(b['entry'] for b in bs):.2f}")
        return bs

    print()
    stats("FRESH (<= %dd old)" % FRESH_DAYS, fresh)
    stats("  fresh, entry <= 0.80", [b for b in fresh if b.get("entry") and b["entry"] <= 0.80])
    stats("  fresh, >= $20k", [b for b in fresh if b["usd"] >= 20000])
    stats("NON-FRESH baseline", other)
    rb = stats("_", fresh) or []
    for b in sorted(rb, key=lambda x: -x["usd"])[:30]:
        print(f"  {datetime.fromtimestamp(b['t0'], timezone.utc):%m-%d} age {b['age_days']:.1f}d ${b['usd']:,.0f} "
              f"{b['outcome']} @ {b['their_price']:.2f} follow {b['entry']:.2f} -> {b['final']:.2f} | {b['title'][:60]}")


if __name__ == "__main__":
    main()
