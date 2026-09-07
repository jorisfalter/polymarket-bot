#!/usr/bin/env python3
"""Standalone headline fetcher for the news sentinel (stdlib only, runs on VPS host)."""
import json
import re
import urllib.parse
import urllib.request

QUERIES = [
    "treasury OR \"federal reserve\" OR liquidity OR \"bond buyback\" when:1d",
    "oil OR opec OR \"strait of hormuz\" OR tanker attack when:1d",
    "bitcoin OR crypto market when:1d",
    "war escalation OR sanctions OR \"capital controls\" when:1d",
]


def fetch(query: str) -> list:
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        text = r.read().decode("utf-8", "replace")
    found = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", text)
    return [t.strip() for t in found[:14] if "Google News" not in t]


def main():
    seen, out = set(), {}
    for q in QUERIES:
        try:
            titles = [t for t in fetch(q) if t not in seen]
            seen.update(titles)
            out[q.split(" ")[0]] = titles[:10]
        except Exception as e:
            out[q.split(" ")[0]] = [f"(fetch failed: {e})"]
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
