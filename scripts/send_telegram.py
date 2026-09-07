#!/usr/bin/env python3
"""Standalone Telegram sender for host-level scripts (sentinel). Stdlib only.

Usage: python3 scripts/send_telegram.py "message"
Reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from .env in the repo root.
"""
import json
import sys
import urllib.request
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: send_telegram.py <message>")
    env = {}
    env_path = Path(__file__).resolve().parent.parent / ".env"
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        sys.exit("telegram keys missing in .env")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat, "text": sys.argv[1][:4000],
                         "parse_mode": "HTML"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        ok = json.load(r).get("ok")
    print("sent" if ok else "failed")


if __name__ == "__main__":
    main()
