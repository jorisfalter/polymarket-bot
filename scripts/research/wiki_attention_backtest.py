"""Backtest: Wikipedia attention spike on a consumer brand/product -> stock excess return.

Event: 7-day mean views >= RATIO x median of the 90 days before (lagged 7d),
and 7-day mean >= MIN_VIEWS. 60-day cooldown per article.
Entry: close of the trading day AFTER the spike day (pageviews land next day).
Returns: d5/d20/d60 excess vs SPY. Also pre-event 20d excess (info parity check).
"""
import json, sys, time, statistics
import httpx
import pandas as pd
import yfinance as yf

UA = "polymarket-insider-research/1.0 (joris@jorisfalter.com)"
RATIO, MIN_VIEWS, COOLDOWN = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0, 1000, 60

# (article, ticker, kind)  kind: product = product/brand page, company = corporate page
M = [
    ("Crocs", "CROX", "company"), ("Hoka_(company)", "DECK", "product"), ("Ugg_(brand)", "DECK", "product"),
    ("Lululemon_Athletica", "LULU", "company"), ("On_(company)", "ONON", "company"),
    ("Celsius_Holdings", "CELH", "company"), ("Duolingo", "DUOL", "company"),
    ("Chipotle_Mexican_Grill", "CMG", "company"), ("Cava_(restaurant)", "CAVA", "company"),
    ("Sweetgreen", "SG", "company"), ("Dutch_Bros_Coffee", "BROS", "company"),
    ("E.l.f._Cosmetics", "ELF", "company"), ("Ozempic", "NVO", "product"), ("Wegovy", "NVO", "product"),
    ("Mounjaro", "LLY", "product"), ("Zepbound", "LLY", "product"), ("Peloton_Interactive", "PTON", "company"),
    ("Roblox", "RBLX", "product"), ("Nintendo_Switch", "NTDOY", "product"), ("Nintendo_Switch_2", "NTDOY", "product"),
    ("Monster_Energy", "MNST", "product"), ("Abercrombie_&_Fitch", "ANF", "company"),
    ("Hims_&_Hers_Health", "HIMS", "company"), ("Shake_Shack", "SHAK", "company"), ("Wingstop", "WING", "company"),
    ("Yeti_(company)", "YETI", "company"), ("GoPro", "GPRO", "company"), ("Beyond_Meat", "BYND", "company"),
    ("Etsy", "ETSY", "company"), ("Temu", "PDD", "product"), ("Threads_(social_network)", "META", "product"),
    ("Sphere_(venue)", "SPHR", "product"), ("Labubu", "9992.HK", "product"), ("Pop_Mart", "9992.HK", "company"),
    ("Barbie_(film)", "MAT", "product"), ("Mattel", "MAT", "company"), ("Hasbro", "HAS", "company"),
    ("Birkenstock", "BIRK", "company"), ("Vital_Farms", "VITL", "company"), ("Cracker_Barrel", "CBRL", "company"),
    ("American_Eagle_Outfitters", "AEO", "company"), ("Bath_&_Body_Works", "BBWI", "company"),
    ("Ulta_Beauty", "ULTA", "company"), ("Carvana", "CVNA", "company"), ("Squid_Game", "NFLX", "product"),
    ("Stranger_Things", "NFLX", "product"), ("Wednesday_(TV_series)", "NFLX", "product"),
    ("KPop_Demon_Hunters", "NFLX", "product"), ("Traeger_(company)", "COOK", "company"),
    ("Funko", "FNKO", "company"), ("GameStop", "GME", "company"), ("AMC_Theatres", "AMC", "company"),
    ("Pinterest", "PINS", "company"), ("Snap_Inc.", "SNAP", "company"), ("Spotify", "SPOT", "company"),
    ("Hershey_Company", "HSY", "company"), ("Coca-Cola", "KO", "product"), ("Starbucks", "SBUX", "company"),
    ("Sonos", "SONO", "company"), ("Garmin", "GRMN", "company"), ("Deckers_Brands", "DECK", "company"),
    ("Nike,_Inc.", "NKE", "company"), ("Under_Armour", "UAA", "company"), ("Skechers", "SKX", "company"),
    ("Planet_Fitness", "PLNT", "company"), ("Life_Time_Fitness", "LTH", "company"), ("Bumble_(app)", "BMBL", "product"),
    ("Match_Group", "MTCH", "company"), ("Tinder_(app)", "MTCH", "product"), ("Zoom_Video_Communications", "ZM", "company"),
    ("Robinhood_Markets", "HOOD", "company"), ("Coinbase", "COIN", "company"), ("DraftKings", "DKNG", "company"),
    ("Celsius_(drink)", "CELH", "product"), ("Liquid_Death", None, "skip"),
]


def views(article):
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/"
           f"all-access/user/{article}/daily/20160101/20261031")
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=30)
    if r.status_code != 200:
        return None
    s = pd.Series({pd.Timestamp(i["timestamp"][:8]): i["views"] for i in r.json()["items"]})
    return s.asfreq("D").fillna(0)


def events(s):
    m7 = s.rolling(7).mean()
    base = s.shift(7).rolling(90).median()
    out, last = [], None
    for d in s.index[100:]:
        b, v = base[d], m7[d]
        if b and b > 0 and v >= MIN_VIEWS and v / b >= RATIO:
            if last is None or (d - last).days > COOLDOWN:
                out.append((d, round(v / b, 1)))
                last = d
    return out


tickers = sorted({t for _, t, k in M if t})
px = yf.download(tickers + ["SPY"], start="2015-12-01", end="2026-11-01", progress=False,
                 auto_adjust=True, group_by="ticker", threads=True)
closes = {t: px[t]["Close"].dropna() for t in tickers + ["SPY"] if t in px.columns.get_level_values(0)}

rows = []
for art, tik, kind in M:
    if not tik or tik not in closes:
        continue
    s = views(art)
    time.sleep(0.1)
    if s is None:
        print("NO PAGE", art, file=sys.stderr)
        continue
    c, spy = closes[tik], closes["SPY"]
    for d, ratio in events(s):
        idx = c.index.searchsorted(d + pd.Timedelta(days=1))
        if idx + 1 >= len(c):
            continue
        e = c.index[idx]
        si = spy.index.searchsorted(e)
        rec = {"article": art, "ticker": tik, "kind": kind, "spike": str(d.date()), "ratio": ratio, "entry": str(e.date())}
        for h in (5, 20, 60):
            if idx + h < len(c) and si + h < len(spy):
                rec[f"d{h}"] = round((c.iloc[idx + h] / c.iloc[idx] - spy.iloc[si + h] / spy.iloc[si]) * 100, 2)
        if idx >= 20 and si >= 20:
            rec["pre20"] = round((c.iloc[idx] / c.iloc[idx - 20] - spy.iloc[si] / spy.iloc[si - 20]) * 100, 2)
        rows.append(rec)

print(json.dumps(rows))
