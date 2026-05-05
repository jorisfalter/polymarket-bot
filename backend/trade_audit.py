"""
Trade Audit — Deep sanity check over recent bot trades.

Different from `trade_analysis.py` (P&L aggregates) — this one looks for
*weird patterns* a human auditor would notice: same market entered N times,
P&L > stake (impossible for binaries), theme concentration, sizing collapse,
strategy mix imbalance, burst clustering.

Run every 2-3 days via the dashboard button "🔍 Audit Trades". Output goes
to Telegram + JSON response.
"""
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

JOURNAL_PATH = Path(__file__).parent.parent / "data" / "trade_journal.jsonl"

# Themes worth flagging when concentration > 30% of total trades.
# These are recurring narratives the bot tends to lock onto.
THEME_KEYWORDS = {
    "iran": ["iran", "tehran", "kharg", "hormuz", "ayatollah"],
    "trump": ["trump"],
    "bitcoin": ["bitcoin", "btc"],
    "election_us": ["primary", "presidential nomination", "2028 republican", "2028 democratic"],
    "fed": ["fed ", "interest rate", "rate cut", "rate hike", "fomc"],
    "weather": ["temperature", "rainfall", "weather", "high temp"],
    "sport": ["lakers", "padres", "giants", "vs.", " vs ", "wins game"],
}


def _read_entries(since: Optional[datetime] = None) -> List[Dict]:
    if not JOURNAL_PATH.exists():
        return []
    entries = []
    for line in JOURNAL_PATH.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since:
            try:
                ts = datetime.fromisoformat(entry["timestamp"].replace("Z", ""))
                if ts < since:
                    continue
            except Exception:
                pass
        entries.append(entry)
    return entries


def _detect_duplicates(enters: List[Dict]) -> List[Dict]:
    """Same market entered ≥2 times within 24 hours = guard probably failed."""
    by_market = defaultdict(list)
    for e in enters:
        key = e.get("market_question", "") or e.get("token_id", "")
        if key:
            by_market[key].append(e)

    dupes = []
    for market, items in by_market.items():
        if len(items) < 2:
            continue
        # Sort by timestamp and find clusters
        items_sorted = sorted(items, key=lambda x: x.get("timestamp", ""))
        for i in range(len(items_sorted) - 1):
            try:
                t0 = datetime.fromisoformat(items_sorted[i]["timestamp"].replace("Z", ""))
                t1 = datetime.fromisoformat(items_sorted[i + 1]["timestamp"].replace("Z", ""))
                if (t1 - t0) < timedelta(hours=24):
                    dupes.append({
                        "market": market[:80],
                        "entries": len(items),
                        "first": items_sorted[0]["timestamp"][:19],
                        "last": items_sorted[-1]["timestamp"][:19],
                        "total_staked": round(sum(x.get("amount_usd", 0) for x in items), 2),
                    })
                    break
            except Exception:
                continue
    return dupes


def _detect_pnl_anomalies(exits: List[Dict]) -> List[Dict]:
    """Flag exits where |pnl_usd| > stake × 1.5. For binaries, |loss| ≤ stake
    and |gain| is bounded by (1/entry_price - 1) × stake. A loss > stake
    almost always means duplicate ENTERs were aggregated incorrectly."""
    anomalies = []
    for e in exits:
        pnl = e.get("pnl_usd")
        stake = e.get("amount_usd")
        if pnl is None or not stake or stake <= 0:
            continue
        if abs(pnl) > stake * 1.5:
            anomalies.append({
                "market": (e.get("market_question") or "")[:80],
                "stake": round(stake, 2),
                "pnl": round(pnl, 2),
                "ratio": round(pnl / stake, 2),
                "timestamp": e.get("timestamp", "")[:19],
            })
    return anomalies


def _theme_concentration(enters: List[Dict]) -> Dict[str, float]:
    """Share of trades touching each named theme. Anything > 30% gets flagged."""
    if not enters:
        return {}
    counts = defaultdict(int)
    for e in enters:
        text = ((e.get("market_question") or "") + " " + (e.get("reason") or "")).lower()
        for theme, kws in THEME_KEYWORDS.items():
            if any(kw in text for kw in kws):
                counts[theme] += 1
    total = len(enters)
    return {theme: round(n / total, 2) for theme, n in counts.items()}


def _sizing_distribution(enters: List[Dict]) -> Dict:
    """Tally trade sizes; warn if 80%+ of trades are at the moonshot floor."""
    if not enters:
        return {"buckets": {}, "moonshot_share": 0.0}
    buckets = Counter()
    for e in enters:
        amt = float(e.get("amount_usd") or 0)
        if amt < 1.5:
            buckets["$1-1.50 (moonshot floor)"] += 1
        elif amt < 3:
            buckets["$1.50-3 (moonshot)"] += 1
        elif amt < 6:
            buckets["$3-6 (mid)"] += 1
        elif amt < 11:
            buckets["$6-10 (core)"] += 1
        else:
            buckets["$10+ (max)"] += 1
    total = len(enters)
    moonshot_floor = buckets.get("$1-1.50 (moonshot floor)", 0)
    return {
        "buckets": dict(buckets),
        "moonshot_share": round(moonshot_floor / total, 2),
        "total": total,
    }


def _strategy_mix(enters: List[Dict]) -> Dict:
    """Strategy keyword frequency in thesis text. Warns if mix is too narrow."""
    if not enters:
        return {}
    keywords = {
        "asymmetric": ["asymmetric", "♻️"],
        "insider": ["insider", "fresh wallet"],
        "smart_money": ["smart money", "leaderboard", "top trader"],
        "near_resolution": ["near.?resolution", "resolves? (today|tomorrow|in)"],
        "stock_arb": ["stock arb", "ticker", "spy"],
        "inconsistency": ["inconsisten", "arbitrage between"],
        "auditor": ["auditor", "kpmg", "deloitte"],
        "own_conviction": ["own conviction", "my read", "i think", "i believe"],
        "daily_repeating": ["daily.?repeat", "base.?rate"],
    }
    counts = {k: 0 for k in keywords}
    for e in enters:
        text = (e.get("reason") or "").lower()
        for strat, pats in keywords.items():
            if any(re.search(p, text) for p in pats):
                counts[strat] += 1
    total = len(enters)
    return {k: round(v / total, 2) for k, v in counts.items()}


def _burst_clusters(enters: List[Dict]) -> List[Dict]:
    """Days with ≥5 entries. Bursts often correlate with the duplicate bug
    or one signal triggering a cascade."""
    by_day = defaultdict(list)
    for e in enters:
        ts = e.get("timestamp", "")
        if ts:
            by_day[ts[:10]].append(e)
    bursts = []
    for day, items in sorted(by_day.items()):
        if len(items) >= 5:
            bursts.append({
                "day": day,
                "entries": len(items),
                "total_staked": round(sum(x.get("amount_usd", 0) for x in items), 2),
                "unique_markets": len({x.get("market_question") for x in items}),
            })
    return bursts


def _strategy_direction_check(enters: List[Dict]) -> List[Dict]:
    """Flag asymmetric trades whose thesis sounds like fading the insider
    rather than piggybacking. Heuristic — looks for 'unlikely' or 'won't' near
    'asymmetric'/'insider'. The playbook says always piggyback."""
    suspect = []
    for e in enters:
        reason = (e.get("reason") or "").lower()
        if "asymmetric" not in reason and "♻️" not in reason:
            continue
        # Suspect phrasings: "unlikely" / "won't" / "doesn't" near asymmetric mention
        if any(p in reason for p in ["unlikely", "won't", "wont ", "doesn't", "will not"]):
            suspect.append({
                "market": (e.get("market_question") or "")[:80],
                "reason": (e.get("reason") or "")[:160],
                "timestamp": e.get("timestamp", "")[:19],
            })
    return suspect


def audit_trades(days: int = 30) -> Dict:
    """Main audit. Returns a structured findings dict for API + Telegram."""
    since = datetime.utcnow() - timedelta(days=days)
    entries = _read_entries(since=since)
    enters = [e for e in entries if e.get("action") == "ENTER"]
    exits = [e for e in entries if e.get("action") == "EXIT"]

    if not enters:
        return {
            "window_days": days,
            "total_enters": 0,
            "message": "No ENTER entries in the journal for this window.",
        }

    duplicates = _detect_duplicates(enters)
    pnl_anomalies = _detect_pnl_anomalies(exits)
    themes = _theme_concentration(enters)
    sizing = _sizing_distribution(enters)
    strategy_mix = _strategy_mix(enters)
    bursts = _burst_clusters(enters)
    fade_suspects = _strategy_direction_check(enters)

    # Severity assessment — a few clear red flags
    findings = []
    if duplicates:
        worst = max(duplicates, key=lambda d: d["entries"])
        findings.append({
            "severity": "critical",
            "category": "duplicate_trades",
            "headline": f"{len(duplicates)} market(s) entered multiple times within 24h. Worst: {worst['entries']}× on '{worst['market'][:60]}' (${worst['total_staked']:.2f} staked)",
        })
    if pnl_anomalies:
        findings.append({
            "severity": "critical",
            "category": "pnl_anomaly",
            "headline": f"{len(pnl_anomalies)} exit(s) with |P&L| > 1.5× stake. Means duplicate ENTERs got rolled into one EXIT.",
        })

    over_concentrated = [(t, s) for t, s in themes.items() if s > 0.30]
    if over_concentrated:
        descs = [f"{t} {int(s*100)}%" for t, s in sorted(over_concentrated, key=lambda x: -x[1])]
        findings.append({
            "severity": "warning",
            "category": "theme_concentration",
            "headline": f"Theme over-concentration: {', '.join(descs)}",
        })

    if sizing["moonshot_share"] > 0.80:
        findings.append({
            "severity": "warning",
            "category": "sizing_collapse",
            "headline": f"{int(sizing['moonshot_share']*100)}% of trades at moonshot floor (≤$1.50). Core book is unused.",
        })

    if fade_suspects:
        findings.append({
            "severity": "warning",
            "category": "strategy_direction",
            "headline": f"{len(fade_suspects)} asymmetric trade(s) with thesis suggesting FADING the insider (playbook says piggyback).",
        })

    if bursts:
        biggest = max(bursts, key=lambda b: b["entries"])
        findings.append({
            "severity": "info",
            "category": "burst_pattern",
            "headline": f"{len(bursts)} burst day(s). Biggest: {biggest['entries']} entries on {biggest['day']} ({biggest['unique_markets']} unique markets).",
        })

    return {
        "window_days": days,
        "total_enters": len(enters),
        "total_exits": len(exits),
        "findings": findings,
        "duplicates": duplicates,
        "pnl_anomalies": pnl_anomalies,
        "themes": themes,
        "sizing": sizing,
        "strategy_mix": strategy_mix,
        "bursts": bursts,
        "fade_suspects": fade_suspects[:10],
    }


def format_telegram_audit(audit: Dict) -> str:
    """Compact HTML summary for Telegram. Stay under 4096 chars."""
    if audit.get("total_enters", 0) == 0:
        return f"🔍 <b>Trade audit</b> — no entries in last {audit.get('window_days', 30)}d."

    lines = [f"🔍 <b>Trade audit</b> — last {audit['window_days']}d"]
    lines.append(f"Entries: {audit['total_enters']} ENTER, {audit['total_exits']} EXIT")

    findings = audit.get("findings", [])
    if not findings:
        lines.append("\n✅ No red flags found.")
        return "\n".join(lines)

    icons = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}
    by_sev = {"critical": [], "warning": [], "info": []}
    for f in findings:
        by_sev[f["severity"]].append(f)

    for sev in ["critical", "warning", "info"]:
        for f in by_sev[sev]:
            lines.append(f"\n{icons[sev]} <b>{f['category']}</b>")
            lines.append(f"  {f['headline']}")

    # Summary tail
    sizing = audit.get("sizing", {})
    if sizing.get("buckets"):
        lines.append("\n<b>Sizing distribution:</b>")
        for bucket, n in sizing["buckets"].items():
            lines.append(f"  {bucket}: {n}")

    return "\n".join(lines)
