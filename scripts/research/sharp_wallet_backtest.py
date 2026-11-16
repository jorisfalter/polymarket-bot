"""Sharp-wallet backtest on Polymarket earnings markets.

Question: are there wallets that keep winning on "Will X beat quarterly
earnings?" markets, and would following them have paid, out-of-sample?

Method
- All closed earnings events since START (Gamma, tag_slug=earnings).
- All trades per market (Data API v2 /trades?condition=, cursor pages).
- Per wallet x market: side = outcome with the most BUY usdc; stake = those
  buys; avg price = stake / shares; won = that outcome resolved to 1.
- TRAIN = markets ending before SPLIT, TEST = after.
- Sharp = in TRAIN: >= MIN_MARKETS markets, win rate >= MIN_WINRATE,
  stake >= MIN_STAKE. Their TEST results are the out-of-sample answer.
- Follow return per bet = payout / avg_price - 1 (their own entry; a fast
  follower got roughly this, see docs/research/kpmg-auditor-pattern.md).

Run: python3 scripts/research/sharp_wallet_backtest.py [out_dir]
"""
import json, sys, time, urllib.request, urllib.parse, collections, statistics as st
from datetime import datetime, timezone

START = "2026-01-01"
SPLIT = "2026-07-01"
MIN_MARKETS, MIN_WINRATE, MIN_STAKE = 5, 0.75, 1000.0
MAX_TRADE_PAGES = 6
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36", "Accept": "application/json"}
OUT = sys.argv[1] if len(sys.argv) > 1 else "."


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                print("ERR", url[:120], e, flush=True)
                return None
            time.sleep(2 * (i + 1))


def earnings_markets():
    out, off = [], 0
    while True:
        q = urllib.parse.urlencode({"tag_slug": "earnings", "closed": "true", "limit": 50, "offset": off,
                                    "order": "endDate", "ascending": "false"})
        evs = get(f"https://gamma-api.polymarket.com/events?{q}") or []
        if not evs:
            break
        stop = False
        for e in evs:
            end = (e.get("endDate") or "")[:10]
            if end < START:
                stop = True
                break
            for m in e.get("markets") or []:
                try:
                    prices = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
                    outcomes = json.loads(m.get("outcomes") or "[]")
                except Exception:
                    continue
                if len(prices) != 2 or max(prices) < 0.99:
                    continue  # unresolved / ambiguous
                out.append({"cond": m["conditionId"], "title": m.get("question") or e.get("title"),
                            "end": end, "win_idx": prices.index(max(prices)), "outcomes": outcomes})
        if stop:
            break
        off += 50
        time.sleep(0.2)
    return out


def market_trades(cond):
    rows, cur = [], None
    for _ in range(MAX_TRADE_PAGES):
        q = {"condition": cond, "limit": 500}
        if cur:
            q["cursor"] = cur
        j = get("https://data-api.polymarket.com/v2/trades?" + urllib.parse.urlencode(q))
        if not j:
            break
        rows += j.get("data", [])
        p = j.get("pagination", {})
        if not p.get("has_more"):
            break
        cur = p.get("next_cursor")
        time.sleep(0.15)
    return rows


def main():
    mk = earnings_markets()
    print(f"closed earnings markets since {START}: {len(mk)}", flush=True)
    bets = []  # one per wallet x market
    for i, m in enumerate(mk):
        tr = market_trades(m["cond"])
        per = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))
        for t in tr:
            if t.get("side") != "BUY":
                continue
            idx = t.get("outcome_index")
            if idx is None:
                continue
            usd = float(t.get("size", 0)) * float(t.get("price", 0))
            a = per[t["proxy_wallet"]][int(idx)]
            a[0] += usd
            a[1] += float(t.get("size", 0))
        for w, sides in per.items():
            idx, (usd, sh) = max(sides.items(), key=lambda kv: kv[1][0])
            if usd < 1 or sh <= 0:
                continue
            bets.append({"w": w, "cond": m["cond"], "title": m["title"], "end": m["end"],
                         "stake": usd, "price": usd / sh, "won": idx == m["win_idx"]})
        if i % 50 == 0:
            print(f"  {i}/{len(mk)} markets, {len(bets)} wallet-bets", flush=True)
    json.dump(bets, open(f"{OUT}/sharp_bets.json", "w"))

    def stats(bs):
        if not bs:
            return "n=0"
        ret = [(1 / b["price"] - 1) if b["won"] else -1.0 for b in bs]
        w = sum(b["stake"] for b in bs)
        wret = sum(((1 / b["price"] - 1) if b["won"] else -1.0) * b["stake"] for b in bs) / w
        return (f"n={len(bs)} won {sum(b['won'] for b in bs)}/{len(bs)} ({sum(b['won'] for b in bs)/len(bs)*100:.0f}%) "
                f"avg ret/bet {st.mean(ret)*100:+.1f}% stake-weighted {wret*100:+.1f}% median stake ${st.median([b['stake'] for b in bs]):,.0f}")

    train = [b for b in bets if b["end"] < SPLIT]
    test = [b for b in bets if b["end"] >= SPLIT]
    byw = collections.defaultdict(list)
    for b in train:
        byw[b["w"]].append(b)
    sharp = {w for w, bs in byw.items()
             if len(bs) >= MIN_MARKETS and sum(x["won"] for x in bs) / len(bs) >= MIN_WINRATE
             and sum(x["stake"] for x in bs) >= MIN_STAKE}
    print(f"\nTRAIN (< {SPLIT}): {stats(train)}")
    print(f"TEST  (>= {SPLIT}): {stats(test)}")
    print(f"\nsharp wallets picked on TRAIN: {len(sharp)}")
    print(f"  their TRAIN bets: {stats([b for b in train if b['w'] in sharp])}")
    print(f"  their TEST bets (out-of-sample): {stats([b for b in test if b['w'] in sharp])}")
    print(f"  everyone else TEST: {stats([b for b in test if b['w'] not in sharp])}")
    rows = []
    for w in sharp:
        tb = [b for b in test if b["w"] == w]
        rows.append({"wallet": w, "train_n": len(byw[w]), "train_won": sum(x["won"] for x in byw[w]),
                     "test_n": len(tb), "test_won": sum(x["won"] for x in tb),
                     "test_stake": round(sum(x["stake"] for x in tb))})
    rows.sort(key=lambda r: (-r["test_n"], -r["train_won"]))
    json.dump(rows, open(f"{OUT}/sharp_wallets.json", "w"), indent=1)
    for r in rows[:25]:
        print("  ", r)


if __name__ == "__main__":
    main()
