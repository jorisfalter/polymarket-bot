#!/usr/bin/env python3
"""IBKR Flex Web Service fetcher (test phase) — stdlib only.

Reads IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID from .env in the repo root.
Two-step flow: SendRequest -> reference code -> GetStatement (XML).

Usage:
  python3 scripts/ibkr_flex.py            # fetch + print summary
  python3 scripts/ibkr_flex.py --raw      # fetch + dump raw XML to data/ibkr_flex_latest.xml
"""
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
REPO = Path(__file__).resolve().parent.parent


def load_env():
    env = {}
    for line in (REPO / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def call(path: str, params: dict) -> str:
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "python-flex/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def fetch_statement(token: str, query_id: str) -> str:
    # Step 1: request generation, returns a reference code
    resp = call("SendRequest", {"t": token, "q": query_id, "v": 3})
    root = ET.fromstring(resp)
    if root.findtext("Status") != "Success":
        sys.exit(f"SendRequest failed: {root.findtext('ErrorCode')} {root.findtext('ErrorMessage')}")
    ref = root.findtext("ReferenceCode")
    # Step 2: poll for the statement (generation can take a few seconds)
    for attempt in range(6):
        time.sleep(2 + attempt * 2)
        body = call("GetStatement", {"t": token, "q": ref, "v": 3})
        if "<FlexQueryResponse" in body:
            return body
        root = ET.fromstring(body)
        code = root.findtext("ErrorCode")
        if code not in ("1019", "1021"):  # statement not yet ready
            sys.exit(f"GetStatement failed: {code} {root.findtext('ErrorMessage')}")
    sys.exit("statement not ready after 6 attempts")


def summarize(xml_text: str):
    root = ET.fromstring(xml_text)
    for stmt in root.iter("FlexStatement"):
        print(f"Account {stmt.get('accountId')}  periode {stmt.get('fromDate')} → {stmt.get('toDate')}")
    trades = list(root.iter("Trade"))
    if trades:
        print(f"\nTrades ({len(trades)}):")
        for t in trades[-20:]:
            print(f"  {t.get('tradeDate')} {t.get('buySell'):4s} {t.get('quantity'):>8s} "
                  f"{t.get('symbol'):8s} @ {t.get('tradePrice')} ({t.get('currency')}) "
                  f"P&L {t.get('fifoPnlRealized', '-')}")
    positions = list(root.iter("OpenPosition"))
    if positions:
        print(f"\nOpen posities ({len(positions)}):")
        for p in positions:
            print(f"  {p.get('symbol'):8s} {p.get('position'):>10s} @ kost {p.get('costBasisPrice')} "
                  f"markt {p.get('markPrice')} ({p.get('currency')})")
    cash = list(root.iter("CashReportCurrency"))
    if cash:
        print("\nCash:")
        for c in cash:
            print(f"  {c.get('currency')}: eind {c.get('endingCash')}")
    if not (trades or positions or cash):
        print("\nGeen Trades/OpenPositions/CashReport-secties gevonden — check welke secties "
              "de Flex Query bevat. Root-elementen aanwezig:",
              sorted({e.tag for e in root.iter()})[:15])


def main():
    env = load_env()
    token, qid = env.get("IBKR_FLEX_TOKEN"), env.get("IBKR_FLEX_QUERY_ID")
    if not (token and qid):
        sys.exit("IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID ontbreken in .env")
    xml_text = fetch_statement(token, qid)
    if "--raw" in sys.argv:
        out = REPO / "data" / "ibkr_flex_latest.xml"
        out.parent.mkdir(exist_ok=True)
        out.write_text(xml_text)
        print(f"raw XML → {out} ({len(xml_text)} bytes)")
    summarize(xml_text)


if __name__ == "__main__":
    main()
