#!/usr/bin/env python3
"""
Daily notification audit script.
Reads notification_log.jsonl for the last 24h and flags suspected false positives
(sports, crypto prices, entertainment) that slipped through the real-time filter.

Usage:
    python scripts/review_notifications.py [--hours 24] [--verbose]
"""
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "data" / "notification_log.jsonl"

# Broader keyword list than the real-time filter — catches edge cases
SPORTS_KEYWORDS = [
    # Leagues & events
    "nfl", "nba", "mlb", "nhl", "mls", "ufc", "pga", "ncaa", "nascar",
    "wnba", "xfl", "afl", "ipl", "bbl", "cpl",
    "super bowl", "world series", "stanley cup", "champions league",
    "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
    "march madness", "playoffs", "finals", "world cup",
    "euro 2026", "copa america", "olympics",
    # Sports
    "football", "basketball", "baseball", "hockey", "soccer", "golf",
    "tennis", "boxing", "mma", "wrestling", "cricket", "rugby",
    "f1", "formula 1", "grand prix", "indy 500", "daytona",
    "wimbledon", "us open tennis", "french open", "australian open",
    # Actions / terms
    "mvp", "touchdown", "home run", "slam dunk", "hat trick",
    "quarterback", "rushing yards", "batting average", "free throw",
    # NFL teams
    "patriots", "chiefs", "eagles", "cowboys", "packers", "49ers",
    "steelers", "ravens", "bills", "dolphins", "jets", "bengals",
    "browns", "titans", "colts", "texans", "jaguars", "broncos",
    "raiders", "chargers", "seahawks", "rams", "cardinals", "commanders",
    "bears", "lions", "vikings", "saints", "falcons", "buccaneers", "panthers",
    # NBA teams
    "lakers", "celtics", "warriors", "bulls", "nets", "knicks",
    "76ers", "sixers", "raptors", "heat", "bucks", "nuggets",
    "suns", "mavericks", "mavs", "clippers", "timberwolves", "thunder",
    "cavaliers", "cavs", "spurs", "rockets", "pelicans", "grizzlies",
    # MLB teams
    "yankees", "dodgers", "red sox", "cubs", "mets", "giants",
    "astros", "braves", "phillies", "padres", "mariners", "orioles",
    "guardians", "twins", "royals", "rays", "blue jays", "brewers",
    # Player names (top names that frequently appear in markets)
    "lebron", "mahomes", "ohtani", "messi", "ronaldo", "curry",
    "giannis", "jokic", "lamar jackson", "josh allen", "travis kelce",
]

CRYPTO_PRICE_KEYWORDS = [
    # Major coins
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
    "dogecoin", "doge", "xrp", "ripple", "cardano", "ada",
    "polkadot", "dot", "avalanche", "avax", "chainlink", "link",
    "polygon", "matic", "litecoin", "ltc", "shiba", "shib",
    "pepe", "bonk", "wif", "floki", "memecoin",
    "toncoin", "ton", "near", "sui", "apt", "aptos",
    # Price patterns
    "above $", "below $", "reach $", "hit $", "break $",
    "price on", "price by", "price of", "price at",
    "market cap", "all-time high", "ath",
    "token price", "coin price", "crypto price",
    # General crypto
    "crypto", "defi", "nft floor",
]

ENTERTAINMENT_KEYWORDS = [
    "oscar", "grammy", "emmy", "golden globe", "academy award",
    "box office", "billboard", "album sales", "streaming record",
    "reality tv", "bachelor", "bachelorette", "survivor",
    "american idol", "the voice",
]

ALL_FILTER_LISTS = {
    "sports": SPORTS_KEYWORDS,
    "crypto_price": CRYPTO_PRICE_KEYWORDS,
    "entertainment": ENTERTAINMENT_KEYWORDS,
}


def load_recent_entries(hours: int) -> list[dict]:
    """Load log entries from the last N hours."""
    if not LOG_PATH.exists():
        return []

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    entries = []
    for line in LOG_PATH.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry["timestamp"])
            if ts >= cutoff:
                entries.append(entry)
        except (json.JSONDecodeError, KeyError):
            continue
    return entries


def check_false_positive(entry: dict) -> list[str]:
    """Return list of matched categories if entry looks like a false positive."""
    question = entry.get("market_question", "").lower()
    slug = entry.get("market_slug", "").lower()
    text = f"{question} {slug}"

    matches = []
    for category, keywords in ALL_FILTER_LISTS.items():
        matched_kws = [kw for kw in keywords if kw in text]
        if matched_kws:
            matches.append(f"{category} ({', '.join(matched_kws[:3])})")
    return matches


def run_audit(hours: int = 24, verbose: bool = False):
    entries = load_recent_entries(hours)

    if not entries:
        print(f"No notifications in the last {hours}h.")
        return

    false_positives = []
    for entry in entries:
        matches = check_false_positive(entry)
        if matches:
            false_positives.append((entry, matches))

    # Report
    print(f"=== Notification Audit ({hours}h) ===")
    print(f"Total sent: {len(entries)}")
    print(f"Suspected false positives: {len(false_positives)}")
    print()

    if false_positives:
        print("--- False Positives ---")
        for entry, matches in false_positives:
            q = entry.get("market_question", "?")[:80]
            ts = entry.get("timestamp", "?")
            alert_type = entry.get("alert_type", "?")
            print(f"  [{ts}] ({alert_type}) {q}")
            print(f"    Matched: {'; '.join(matches)}")
            print()

        # Suggest new keywords
        all_matched = set()
        for _, matches in false_positives:
            for m in matches:
                # Extract category
                cat = m.split(" (")[0]
                all_matched.add(cat)
        print("Suggestion: Review the above markets. If they are true false positives,")
        print(f"consider strengthening filters for: {', '.join(sorted(all_matched))}")
    else:
        print("All clear — no suspected false positives found.")

    if verbose:
        print("\n--- All Entries ---")
        for entry in entries:
            q = entry.get("market_question", "?")[:60]
            sev = entry.get("severity", "-")
            score = entry.get("score", "-")
            print(f"  [{entry.get('timestamp', '?')}] {sev}/{score} {q}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit recent notification log")
    parser.add_argument("--hours", type=int, default=24, help="Look back N hours (default: 24)")
    parser.add_argument("--verbose", action="store_true", help="Show all entries")
    args = parser.parse_args()
    run_audit(hours=args.hours, verbose=args.verbose)
