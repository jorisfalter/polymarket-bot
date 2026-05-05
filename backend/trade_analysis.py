"""
Trade Analysis — Learning loop over the trade journal.

Reads `data/trade_journal.jsonl`, groups exits by strategy + signal pattern,
and surfaces aggregates so we can see if entire strategies are losing money.
The output is structured for both an API response and a Telegram digest.

Signal patterns are inferred from the `reason` text the agent wrote at entry
(thesis + confidence). The patterns mirror the moonshot vs. core split in
ai_prompts.py — asymmetric / daily-repeating / near-resolution / smart-money /
insider / own-conviction. Anything that doesn't match a known pattern lands
in "other".
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

JOURNAL_PATH = Path(__file__).parent.parent / "data" / "trade_journal.jsonl"


# Order matters: more specific patterns first so an "asymmetric daily-repeating"
# bet is bucketed by the stronger asymmetric signal, not generically as daily.
PATTERN_RULES: List[Tuple[str, re.Pattern]] = [
    ("asymmetric",       re.compile(r"asymmetric|paris.?weather|moonshot.*longshot|♻️", re.I)),
    ("daily-repeating",  re.compile(r"daily.?repeat|base.?rate|streak", re.I)),
    ("near-resolution",  re.compile(r"near.?resolution|resolution.?arb|expir(es|ing)|resolve\w* (today|tomorrow|in)", re.I)),
    ("smart-money",      re.compile(r"smart.?money|whale|top.?trader|leaderboard", re.I)),
    ("insider-signal",   re.compile(r"insider|fresh wallet|suspicious|cluster", re.I)),
    ("inconsistency",    re.compile(r"inconsisten|mispriced|arbitrage between|spread between", re.I)),
    ("stock-arb",        re.compile(r"stock.?arb|equity arb|ticker mispriced", re.I)),
    ("auditor",          re.compile(r"auditor|polymarket.?auditor", re.I)),
    ("news-swing",       re.compile(r"news|breaking|headline|just announced", re.I)),
    ("own-conviction",   re.compile(r"own conviction|my read|i think|i believe|conviction", re.I)),
]


def _classify_pattern(reason: str) -> str:
    if not reason:
        return "other"
    for name, rx in PATTERN_RULES:
        if rx.search(reason):
            return name
    return "other"


def _stake_bucket(amount_usd: float) -> str:
    """Group stakes so we can see whether dust-sized longshots specifically
    are losing — this is the bucket the user flagged with the $26 Eurovision
    observation."""
    if amount_usd < 2:
        return "<$2"
    if amount_usd < 5:
        return "$2-5"
    if amount_usd < 10:
        return "$5-10"
    return "$10+"


def _read_exits(since: Optional[datetime] = None) -> List[Dict]:
    if not JOURNAL_PATH.exists():
        return []
    exits = []
    for line in JOURNAL_PATH.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("action") != "EXIT":
            continue
        if since:
            try:
                ts = datetime.fromisoformat(entry["timestamp"].replace("Z", ""))
                if ts < since:
                    continue
            except Exception:
                pass
        exits.append(entry)
    return exits


def _aggregate(exits: List[Dict], key_fn) -> Dict[str, Dict]:
    """Group exits by `key_fn(entry)` and compute per-bucket aggregates.
    Excludes entries with pnl_usd=None (unresolved) from win/loss math but
    still counts them under `unresolved`."""
    buckets = defaultdict(lambda: {
        "trades": 0, "wins": 0, "losses": 0, "unresolved": 0,
        "pnl": 0.0, "stake": 0.0, "best": None, "worst": None,
    })
    for e in exits:
        key = key_fn(e)
        b = buckets[key]
        b["trades"] += 1
        b["stake"] += float(e.get("amount_usd") or 0)
        pnl = e.get("pnl_usd")
        if pnl is None:
            b["unresolved"] += 1
            continue
        b["pnl"] += pnl
        if pnl > 0:
            b["wins"] += 1
        else:
            b["losses"] += 1
        if b["best"] is None or pnl > b["best"]["pnl"]:
            b["best"] = {"pnl": pnl, "market": e.get("market_question", "")[:80]}
        if b["worst"] is None or pnl < b["worst"]["pnl"]:
            b["worst"] = {"pnl": pnl, "market": e.get("market_question", "")[:80]}

    out = {}
    for key, b in buckets.items():
        resolved = b["wins"] + b["losses"]
        out[key] = {
            "trades": b["trades"],
            "resolved": resolved,
            "unresolved": b["unresolved"],
            "wins": b["wins"],
            "losses": b["losses"],
            "win_rate": round(b["wins"] / resolved, 2) if resolved else None,
            "total_pnl": round(b["pnl"], 2),
            "total_stake": round(b["stake"], 2),
            "roi_pct": round(b["pnl"] / b["stake"] * 100, 1) if b["stake"] else None,
            "avg_pnl": round(b["pnl"] / resolved, 2) if resolved else None,
            "best": b["best"],
            "worst": b["worst"],
        }
    return out


def _detect_red_flags(by_pattern: Dict, by_pattern_stake: Dict) -> List[str]:
    """Find buckets that are clearly losing money so the user can see
    which strategies to kill or shrink. Heuristic, not statistical — the
    sample sizes are small."""
    flags = []
    for pattern, agg in by_pattern.items():
        if agg["resolved"] >= 5 and agg["win_rate"] is not None:
            if agg["win_rate"] < 0.2 and agg["total_pnl"] < -5:
                flags.append(
                    f"❌ {pattern}: {agg['wins']}/{agg['resolved']} wins ({agg['win_rate']:.0%}), "
                    f"net ${agg['total_pnl']:+.2f}. Consider tightening or killing this signal."
                )
        if agg["resolved"] >= 3 and agg["roi_pct"] is not None and agg["roi_pct"] < -50:
            flags.append(
                f"⚠️ {pattern}: ROI {agg['roi_pct']:+.0f}% over {agg['resolved']} resolved trades "
                f"(net ${agg['total_pnl']:+.2f} on ${agg['total_stake']:.0f} staked)."
            )

    # Stake-bucket within pattern: e.g. asymmetric at <$2 stake bleeding
    for (pattern, stake), agg in by_pattern_stake.items():
        if agg["resolved"] >= 5 and agg["win_rate"] is not None and agg["win_rate"] < 0.15:
            flags.append(
                f"💸 {pattern} @ {stake}: {agg['wins']}/{agg['resolved']} wins, "
                f"net ${agg['total_pnl']:+.2f}. Sample is whispering, not shouting — watch."
            )
    return flags


def _detect_winners(by_pattern: Dict) -> List[str]:
    """Surface profitable patterns so we know what to do MORE of."""
    wins = []
    for pattern, agg in by_pattern.items():
        if agg["resolved"] >= 3 and agg["total_pnl"] > 5 and agg["win_rate"] is not None and agg["win_rate"] >= 0.5:
            wins.append(
                f"✅ {pattern}: {agg['wins']}/{agg['resolved']} wins ({agg['win_rate']:.0%}), "
                f"net ${agg['total_pnl']:+.2f}. Keep doing this."
            )
    return wins


def analyze_history(days: int = 30) -> Dict:
    """Main entry point. Returns structured analysis for API + Telegram."""
    since = datetime.utcnow() - timedelta(days=days)
    exits = _read_exits(since=since)
    if not exits:
        return {
            "window_days": days,
            "total_exits": 0,
            "message": "No exits in the journal for this window.",
        }

    by_strategy = _aggregate(exits, lambda e: e.get("strategy", "unknown"))
    by_pattern = _aggregate(exits, lambda e: _classify_pattern(e.get("reason", "")))
    by_stake = _aggregate(exits, lambda e: _stake_bucket(float(e.get("amount_usd") or 0)))

    # Cross-tab pattern × stake — this is the bucket the user cares about
    # (e.g. "asymmetric @ <$2" vs "asymmetric @ $5-10")
    by_pattern_stake = _aggregate(
        exits,
        lambda e: (_classify_pattern(e.get("reason", "")), _stake_bucket(float(e.get("amount_usd") or 0))),
    )
    # Flatten tuple keys to "pattern @ stake" strings for JSON-friendly output
    by_pattern_stake_flat = {f"{p} @ {s}": v for (p, s), v in by_pattern_stake.items()}

    resolved_total = sum(1 for e in exits if e.get("pnl_usd") is not None)
    total_pnl = round(sum((e.get("pnl_usd") or 0) for e in exits if e.get("pnl_usd") is not None), 2)
    total_stake = round(sum(float(e.get("amount_usd") or 0) for e in exits), 2)
    wins = sum(1 for e in exits if (e.get("pnl_usd") or 0) > 0)

    return {
        "window_days": days,
        "total_exits": len(exits),
        "resolved": resolved_total,
        "unresolved": len(exits) - resolved_total,
        "total_pnl": total_pnl,
        "total_stake": total_stake,
        "win_rate": round(wins / resolved_total, 2) if resolved_total else None,
        "by_strategy": by_strategy,
        "by_pattern": by_pattern,
        "by_stake": by_stake,
        "by_pattern_stake": by_pattern_stake_flat,
        "red_flags": _detect_red_flags(by_pattern, by_pattern_stake),
        "winners": _detect_winners(by_pattern),
    }


def format_telegram_summary(analysis: Dict) -> str:
    """Compact HTML summary for Telegram. Stay under 4096 chars."""
    if analysis.get("total_exits", 0) == 0:
        return f"📊 <b>Trade analysis</b> — no exits in last {analysis.get('window_days', 30)}d."

    lines = [f"📊 <b>Trade analysis</b> — last {analysis['window_days']}d"]
    lines.append(
        f"Exits: {analysis['total_exits']} ({analysis['resolved']} resolved, {analysis['unresolved']} pending)"
    )
    if analysis.get("win_rate") is not None:
        lines.append(
            f"Net P&amp;L: <b>${analysis['total_pnl']:+.2f}</b> on ${analysis['total_stake']:.0f} staked "
            f"({analysis['win_rate']:.0%} win rate)"
        )

    # By pattern — the most actionable view
    by_pattern = analysis.get("by_pattern", {})
    if by_pattern:
        lines.append("\n<b>By signal pattern:</b>")
        sorted_patterns = sorted(by_pattern.items(), key=lambda x: x[1]["total_pnl"])
        for pattern, agg in sorted_patterns:
            wr = f"{agg['win_rate']:.0%}" if agg["win_rate"] is not None else "—"
            lines.append(
                f"  {pattern}: {agg['resolved']}r / ${agg['total_pnl']:+.2f} ({wr})"
            )

    if analysis.get("red_flags"):
        lines.append("\n<b>Red flags:</b>")
        for flag in analysis["red_flags"][:5]:
            lines.append(f"  {flag}")

    if analysis.get("winners"):
        lines.append("\n<b>What's working:</b>")
        for win in analysis["winners"][:5]:
            lines.append(f"  {win}")

    return "\n".join(lines)
