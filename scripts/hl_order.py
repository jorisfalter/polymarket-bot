#!/usr/bin/env python3
"""One Hyperliquid order via the API (video demo). Testnet by default.

Needs: pip install hyperliquid-python-sdk
Env (.env or shell):
  HL_API_KEY   private key of an API wallet (Hyperliquid UI -> API). It can trade but
               cannot withdraw.
  HL_ACCOUNT   address of the main account the API wallet trades for.

Usage:
  hl_order.py quote xyz:ANT                    # price only, no key needed
  hl_order.py buy BTC 20                       # $20 market buy on TESTNET, 1x isolated
  hl_order.py sell BTC 20                      # close / short on testnet
  hl_order.py buy xyz:ANT 20 --mainnet         # REAL money: also needs HL_ALLOW_MAINNET=1
  hl_order.py positions [--mainnet]

Mainnet is deliberately double-gated (flag + env var): the project rule is no real
money for bots; a one-off manual order is Joris' call.
"""
import argparse
import os
import sys
from pathlib import Path

import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants


def _env():
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("HL_") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def main():
    _env()
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["quote", "buy", "sell", "positions"])
    ap.add_argument("coin", nargs="?", default="BTC")
    ap.add_argument("usd", nargs="?", type=float, default=20.0)
    ap.add_argument("--mainnet", action="store_true")
    ap.add_argument("--leverage", type=int, default=1)
    a = ap.parse_args()

    if a.mainnet and a.action in ("buy", "sell") and os.environ.get("HL_ALLOW_MAINNET") != "1":
        sys.exit("Mainnet order refused: set HL_ALLOW_MAINNET=1 to confirm real money.")
    url = constants.MAINNET_API_URL if a.mainnet else constants.TESTNET_API_URL
    dex = a.coin.split(":")[0] if ":" in a.coin else ""
    dexs = ["", dex] if dex else None
    info = Info(url, skip_ws=True, perp_dexs=dexs)
    net = "MAINNET" if a.mainnet else "testnet"

    mids = info.all_mids(dex) if dex else info.all_mids()
    px = float(mids[a.coin]) if a.coin in mids else None
    if a.action == "quote":
        print(f"[{net}] {a.coin} mid = {px}")
        return

    key, account = os.environ.get("HL_API_KEY"), os.environ.get("HL_ACCOUNT")
    if not key or not account:
        sys.exit("Set HL_API_KEY (API wallet key) and HL_ACCOUNT (main address).")
    wallet = eth_account.Account.from_key(key)

    if a.action == "positions":
        st = info.user_state(account, dex) if dex else info.user_state(account)
        print(f"[{net}] account value {st['marginSummary']['accountValue']}")
        for p in st["assetPositions"]:
            q = p["position"]
            print(f"  {q['coin']} size {q['szi']} entry {q['entryPx']} pnl {q['unrealizedPnl']}")
        return

    if px is None:
        sys.exit(f"{a.coin} not found on {net}")
    ex = Exchange(wallet, url, account_address=account, perp_dexs=dexs)
    meta = info.meta(dex) if dex else info.meta()
    decimals = next(x["szDecimals"] for x in meta["universe"] if x["name"] == a.coin)
    size = round(a.usd / px, decimals)
    print(f"[{net}] {a.action} {size} {a.coin} (~${a.usd}) at ~{px}, {a.leverage}x isolated")
    print("leverage:", ex.update_leverage(a.leverage, a.coin, is_cross=False))
    r = ex.market_open(a.coin, a.action == "buy", size, None, slippage=0.01)
    print("order:", r)


if __name__ == "__main__":
    main()
