"""
Trade failure log + triage. Every failed trade attempt gets a structured
entry on disk so we can:
- Triage in batches (user calls /api/agent/triage-failures every few days)
- Detect new failure modes that aren't covered by pre-flight checks
- Build evidence for adding new pre-flight rules

Each entry captures the full context at time of failure so we don't have
to query Polymarket later (where state may have moved on).
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import httpx
from loguru import logger

FAILURES_PATH = Path(__file__).parent.parent / "data" / "trade_failures.jsonl"


# Known failure modes — keep in sync with docs/polymarket-trade-execution.md
KNOWN_MODES = {
    "uma_disputed": "UMA market disputed",
    "uma_proposed": "UMA proposed liveness window",
    "uma_resolved": "UMA already resolved",
    "market_closed": "market closed",
    "market_archived": "market archived",
    "not_accepting_orders": "market not accepting orders",
    "below_min_size": "amount below market minimum",
    "no_orderbook": "no orderbook (expired/closed)",
    "thin_orderbook": "best ask far from displayed price",
    "token_resolve_fail": "could not resolve token_id",
    "malformed_market_id": "agent passed truncated market_id",
    "below_per_trade_min": "amount below polymarket min ($1.05)",
    "above_per_trade_cap": "amount above per-trade cap ($10)",
    "exposure_cap": "total exposure cap reached",
    "slot_cap": "max positions cap reached",
    "duplicate_position": "already hold this market",
    "unknown": "no known mode matched — needs investigation",
}


def log_failure(
    market_question: str,
    market_id: str,
    token_id: Optional[str],
    outcome: str,
    amount_usd: float,
    error: str,
    confidence: Optional[float] = None,
    thesis: Optional[str] = None,
    market_metadata: Optional[Dict] = None,
):
    """Append a failure entry. market_metadata is the gamma snapshot if we
    have it (for failures that happen post-pre-flight)."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "market_question": market_question,
        "market_id": market_id,
        "token_id": token_id,
        "outcome": outcome,
        "amount_usd": amount_usd,
        "error": error,
        "confidence": confidence,
        "thesis": thesis,
        "market_metadata": market_metadata,
        "classified_mode": classify_error(error),
        "triaged": False,
        "triage_notes": None,
    }
    try:
        FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FAILURES_PATH, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        logger.info(f"Logged trade failure: {entry['classified_mode']} | {market_question[:50]}")
    except Exception as e:
        logger.warning(f"Failed to log trade failure: {e}")


def classify_error(error: str) -> str:
    """Match an error string to a known failure mode. Order matters — most
    specific first."""
    if not error:
        return "unknown"
    e = error.lower()
    if "uma disputed" in e or "uma challenged" in e:
        return "uma_disputed"
    if "uma proposed" in e:
        return "uma_proposed"
    if "uma resolved" in e:
        return "uma_resolved"
    if "market closed" in e:
        return "market_closed"
    if "market archived" in e:
        return "market_archived"
    if "not accepting orders" in e:
        return "not_accepting_orders"
    if "below market minimum" in e or "below min" in e:
        return "below_min_size"
    if "no orderbook" in e or "404" in e and "orderbook" in e:
        return "no_orderbook"
    if "orderbook too thin" in e or "best ask" in e:
        return "thin_orderbook"
    if "could not resolve token" in e:
        return "token_resolve_fail"
    if "malformed market_id" in e or "expected 66" in e:
        return "malformed_market_id"
    if "exposure" in e and ("limit" in e or "cap" in e):
        return "exposure_cap"
    if "max positions" in e or "max " in e and "positions" in e:
        return "slot_cap"
    if "already hold" in e or "duplicate" in e:
        return "duplicate_position"
    if "above per-trade" in e or "exceeds per-trade" in e:
        return "above_per_trade_cap"
    if "order_version_mismatch" in e:
        return "unknown"  # The whole point — these need triage
    return "unknown"


def list_failures(limit: int = 200, untriaged_only: bool = False) -> List[Dict]:
    if not FAILURES_PATH.exists():
        return []
    out: List[Dict] = []
    for line in FAILURES_PATH.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            e = json.loads(line)
            if untriaged_only and e.get("triaged"):
                continue
            out.append(e)
        except json.JSONDecodeError:
            continue
    out.reverse()
    return out[:limit]


async def triage_failures(limit: int = 50) -> Dict:
    """For each untriaged failure, re-check the market against Polymarket's
    Gamma API. Classify whether our current pre-flight chain would now catch
    it (so we know which failures are 'fixed forward' by code we've added
    since the failure happened) vs which still need investigation.

    Updates each entry's `triaged=True` + `triage_notes` in-place by
    rewriting the whole file. Returns a summary."""
    failures = list_failures(limit=500, untriaged_only=True)
    if not failures:
        return {"triaged": 0, "summary": {}, "needs_investigation": []}

    summary = {"would_now_catch": 0, "still_unknown": 0, "by_mode": {}}
    needs_investigation: List[Dict] = []
    triaged_ids = set()

    async with httpx.AsyncClient(timeout=15.0) as client:
        for f in failures[:limit]:
            token_id = f.get("token_id")
            if not token_id:
                f["triage_notes"] = "no token_id, cannot re-check"
                f["triaged"] = True
                triaged_ids.add(f["timestamp"])
                continue

            # Re-check Gamma metadata + orderbook
            try:
                r = await client.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={"clob_token_ids": token_id},
                )
                r.raise_for_status()
                markets = r.json() or []
                meta = markets[0] if markets else None
            except Exception as e:
                meta = None
                f["triage_notes"] = f"gamma fetch error: {e}"
                f["triaged"] = True
                triaged_ids.add(f["timestamp"])
                continue

            mode = _diagnose_with_current_checks(f, meta)
            f["classified_mode"] = mode
            f["triaged"] = True
            f["triage_notes"] = f"diagnosed as {mode} — {KNOWN_MODES.get(mode, '?')}"
            triaged_ids.add(f["timestamp"])
            summary["by_mode"][mode] = summary["by_mode"].get(mode, 0) + 1
            if mode == "unknown":
                summary["still_unknown"] += 1
                needs_investigation.append({
                    "timestamp": f["timestamp"],
                    "market_question": f.get("market_question"),
                    "market_id": f.get("market_id"),
                    "token_id": token_id,
                    "amount_usd": f.get("amount_usd"),
                    "error": f.get("error"),
                    "current_market_state": meta,
                })
            else:
                summary["would_now_catch"] += 1

    # Rewrite the file with triage updates
    if triaged_ids:
        all_failures = list_failures(limit=10000)  # everything
        with open(FAILURES_PATH, "w") as fh:
            for entry in reversed(all_failures):  # back to chronological
                if entry["timestamp"] in triaged_ids:
                    # find the updated version
                    for f in failures:
                        if f["timestamp"] == entry["timestamp"]:
                            entry = f
                            break
                fh.write(json.dumps(entry, default=str) + "\n")

    return {
        "triaged": len(triaged_ids),
        "summary": summary,
        "needs_investigation": needs_investigation[:20],
    }


def _diagnose_with_current_checks(failure: Dict, current_meta: Optional[Dict]) -> str:
    """Apply our current pre-flight chain mentally to figure out which check
    would now catch the failure. If none would, return 'unknown' so the user
    knows it still needs a new check."""
    # Original mode might already be informative
    original = failure.get("classified_mode")
    if original and original != "unknown":
        return original

    if not current_meta:
        return "unknown"

    if current_meta.get("closed"):
        return "market_closed"
    if current_meta.get("archived"):
        return "market_archived"
    if current_meta.get("active") is False:
        return "market_closed"
    if current_meta.get("acceptingOrders") is False:
        return "not_accepting_orders"
    uma = (current_meta.get("umaResolutionStatus") or "").lower()
    if uma in ("disputed", "challenged"):
        return "uma_disputed"
    if uma == "proposed":
        return "uma_proposed"
    if uma == "resolved":
        return "uma_resolved"
    min_size = float(current_meta.get("orderMinSize") or 0)
    if min_size and failure.get("amount_usd", 0) < min_size:
        return "below_min_size"
    return "unknown"
