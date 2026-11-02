#!/usr/bin/env python3
"""Consumer-signal fetcher for the consumer sentinel (stdlib only, runs on VPS host).

Sources (all official/public, no bot-blocking): Google News RSS consumer
queries, Apple App Store top charts (US, with rank change vs a stored
snapshot), Google Trends daily trending searches (US).
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = {"User-Agent": "polymarket-insider-research/1.0 (joris@jorisfalter.com)"}
SNAP_DIR = Path("/home/app/sentinel/consumer/charts")

NEWS_QUERIES = {
    "sold_out": "\"sold out\" OR \"selling out\" OR \"flying off shelves\" OR \"can't keep in stock\" when:2d",
    "viral": "viral TikTok product OR brand OR snack OR toy when:2d",
    "demand": "waitlist OR backorder OR shortage consumer product demand when:2d",
    "growth": "\"fastest-growing\" brand OR app OR restaurant chain when:3d",
    "fading": "\"sales slump\" OR \"lost its cool\" OR \"backlash\" OR boycott brand when:2d",
}
CHARTS = {"top-free": "https://rss.marketingtools.apple.com/api/v2/us/apps/top-free/100/apps.json",
          "top-paid": "https://rss.marketingtools.apple.com/api/v2/us/apps/top-paid/50/apps.json"}
TRENDS = "https://trends.google.com/trending/rss?geo=US"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def news() -> dict:
    out, seen = {}, set()
    for key, q in NEWS_QUERIES.items():
        try:
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
            titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", _get(url))
            titles = [t.strip() for t in titles if "Google News" not in t and t not in seen]
            seen.update(titles)
            out[key] = titles[:12]
        except Exception as e:
            out[key] = [f"(fetch failed: {e})"]
    return out


def charts() -> dict:
    """Current top charts + movers vs the oldest snapshot of the last 7 days."""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cur = {}
    for name, url in CHARTS.items():
        try:
            apps = json.loads(_get(url))["feed"]["results"]
            cur[name] = [{"rank": i + 1, "name": a["name"], "dev": a.get("artistName")}
                         for i, a in enumerate(apps)]
        except Exception as e:
            cur[name] = [{"error": str(e)[:100]}]
    (SNAP_DIR / f"{today}.json").write_text(json.dumps(cur))
    for old in sorted(SNAP_DIR.glob("*.json"))[:-30]:
        old.unlink()
    prior = [p for p in sorted(SNAP_DIR.glob("*.json")) if p.stem < today][-7:]
    ref = json.loads(prior[0].read_text()) if prior else {}
    out = {"compared_to": prior[0].stem if prior else None}
    for name, apps in cur.items():
        before = {a.get("name"): a.get("rank") for a in ref.get(name, [])}
        movers = []
        for a in apps:
            if "rank" not in a:
                continue
            b = before.get(a["name"])
            if b is None and ref and a["rank"] <= 40:
                movers.append({**a, "was": "new"})
            elif b and b - a["rank"] >= 15:
                movers.append({**a, "was": b})
        out[name] = {"top15": [f'{a["rank"]}. {a["name"]} ({a["dev"]})' for a in apps[:15] if "rank" in a],
                     "movers": movers[:15]}
    return out


def trends() -> list:
    try:
        xml = _get(TRENDS)
        items = re.findall(r"<item>(.*?)</item>", xml, re.S)
        out = []
        for it in items[:25]:
            t = re.search(r"<title>(.*?)</title>", it)
            tr = re.search(r"<ht:approx_traffic>(.*?)</ht:approx_traffic>", it)
            if t:
                out.append(f"{t.group(1).strip()} ({tr.group(1) if tr else '?'})")
        return out
    except Exception as e:
        return [f"(fetch failed: {e})"]


if __name__ == "__main__":
    print(json.dumps({"news": news(), "app_store": charts(), "google_trends_us": trends()}, indent=1))
