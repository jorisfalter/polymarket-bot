#!/usr/bin/env python3
"""Insider-claim fetcher for the claims sentinel (stdlib only, runs on the VPS host).

Finds reports of suspicious / insider trading on prediction markets:
- Google News RSS (journalism: NYT, Bloomberg, Upside, In Game, ...)
- X posts via Firecrawl search (the Twitter API key is dead, 401)
- EventWaves substack (published the KPMG wallets in Feb 2026)

Only items not seen before are printed (state: /home/app/sentinel/claims_state.json),
so the wrapper can skip the Claude call entirely when nothing is new.
Usage: fetch_insider_claims.py [--dry]   (--dry: don't update the seen-state)
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

STATE = Path("/home/app/sentinel/claims_state.json")
ENV = Path("/opt/polymarket-insider/.env")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36"}

NEWS = [
    "polymarket \"insider trading\" when:2d",
    "polymarket suspicious bets OR trades OR wallets when:2d",
    "kalshi \"insider trading\" OR suspicious when:2d",
    "\"prediction market\" leaked OR leak OR \"advance knowledge\" when:2d",
    "polymarket \"new accounts\" OR \"fresh wallets\" OR \"newly created\" when:3d",
]
JUNK = re.compile(r"promo|referral|code \"?rocky|rocky top|bonus|odds boost|sportsbook", re.I)
X_QUERIES = [
    "site:x.com polymarket insider wallet",
    "site:x.com polymarket suspicious fresh wallet bet",
    "site:x.com polymarket leak before announcement",
    # accounts that post suspicious wallets (verified 2026-11-17); Google lags hours
    "site:x.com/EventWavesIO",
    "site:x.com/Polysights insider",
    "site:x.com/lookonchain polymarket",
]
RSS = [("https://eventwaves.substack.com/feed", "EventWaves")]


def _get(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def google_news(q):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    xml = _get(url)
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S)[:15]:
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        l = re.search(r"<link>(.*?)</link>", item, re.S)
        d = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        if t and l:
            out.append({"src": "news", "title": t.group(1).strip(), "url": l.group(1).strip(),
                        "date": d.group(1)[:16] if d else ""})
    return out


def firecrawl_key():
    for line in ENV.read_text().splitlines():
        if line.startswith("FIRECRAWL_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def x_search(q, key):
    body = json.dumps({"query": q, "limit": 8, "tbs": "qdr:d"}).encode()
    j = json.loads(_get("https://api.firecrawl.dev/v1/search", data=body, timeout=60,
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}))
    return [{"src": "x", "title": (d.get("title") or "")[:200], "url": d.get("url"),
             "snippet": (d.get("description") or "")[:400]} for d in j.get("data", []) if d.get("url")]


def rss(url, name):
    xml = _get(url)
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S)[:5]:
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.S)
        l = re.search(r"<link>(.*?)</link>", item, re.S)
        if t and l:
            out.append({"src": name, "title": t.group(1).strip(), "url": l.group(1).strip()})
    return out


def main():
    dry = "--dry" in sys.argv
    try:
        state = json.loads(STATE.read_text())
    except Exception:
        state = {"seen": []}
    seen = set(state["seen"])
    items, errors = [], []
    for q in NEWS:
        try:
            items += google_news(q)
        except Exception as e:
            errors.append(f"news '{q}': {e}")
    key = firecrawl_key()
    for q in X_QUERIES if key else []:
        try:
            items += x_search(q, key)
        except Exception as e:
            errors.append(f"x '{q}': {e}")
    for url, name in RSS:
        try:
            items += rss(url, name)
        except Exception as e:
            errors.append(f"rss {name}: {e}")

    new, keys = [], set()
    for it in items:
        if JUNK.search(it["title"]):
            continue
        k = re.sub(r"\W+", " ", it["title"].lower()).strip()[:90]  # same story on many sites -> title key
        if it["url"] in seen or k in seen or k in keys:
            continue
        keys.add(k)
        new.append(it)
        seen.update([it["url"], k])
    if not dry:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        state["seen"] = list(seen)[-3000:]
        STATE.write_text(json.dumps(state))
    print(json.dumps({"n_new": len(new), "items": new, "errors": errors}, indent=1))


if __name__ == "__main__":
    main()
