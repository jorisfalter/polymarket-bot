"""
Dynamic shortlist of crypto-price markets for maker mode.

⚠️ 2026-06-16: maker mode FROZEN after losing ~$70 in 6 days (5-11 June)
on crypto daily-price markets. Root cause was adverse selection — takers
who could see live spot prices dumped YES-side shares onto our wide-spread
bids right before those markets resolved NO. Wide spreads on time-decaying
directional markets ≠ maker edge; they're the *price of insurance against
informed flow*. We mistook that for opportunity.

`fetch_shortlist` is left in place so the dashboard endpoint still works,
but `config.agent_mode = "frozen"` keeps the bot from posting orders.
DO NOT re-enable maker mode on crypto-prices without first solving the
informed-flow problem (e.g. cancel bids when spot moves against the
market direction).

Why the original design was dynamic: daily-resolving markets expire every
24-48h, so a hardcoded token_id list in config goes stale instantly. We
query Gamma each cycle and pick the top N candidates by spread × volume.

Selection criteria (paper-validated, but contradicted by live results):
- Tag: crypto-prices (footnote 13 in Akey et al. — these markets have
  maker rebates since 2026-03-06, which widens spreads to compensate
  takers for fees, leaving room for makers to capture).
- Mid price 0.15-0.85: avoid extremes where favorite-longshot bias dominates
  and 1-tick spreads dominate.
- 24h volume >= MIN_VOLUME: need actual flow to get filled.
- Spread >= MIN_SPREAD_CENTS: need room to post inside or capture the
  bid-ask round-trip.
- End date in the future and > MIN_HOURS_TO_END from now: avoid markets
  hours from resolution (CLOB starts rejecting orders ~1h pre-resolve).

Override via config.maker_target_token_ids — if set, skip the auto-pick
and use exactly those.
"""
from __future__ import annotations
import json
import httpx
from loguru import logger
from datetime import datetime, timezone
from typing import Optional

from .config import settings


GAMMA = "https://gamma-api.polymarket.com"
MIN_VOLUME_USD = 1500.0
MIN_SPREAD_CENTS = 2.0
MIN_HOURS_TO_END = 6.0    # too-close = CLOB rejects orders
MAX_HOURS_TO_END = 168.0  # cap at 1 week — long-dated markets tie up capital;
                          # opt in via config.maker_target_token_ids override.
PRICE_LOW = 0.15
PRICE_HIGH = 0.85
DEFAULT_TOP_N = 3


async def _fetch_crypto_events(limit: int = 50) -> list[dict]:
    """Pull active crypto-prices events from Gamma."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.get(
                f"{GAMMA}/events",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "tag_slug": "crypto-prices",
                    "order": "volume24hr",
                    "ascending": "false",
                },
            )
            r.raise_for_status()
            return r.json() or []
    except Exception as e:
        logger.error(f"maker_shortlist fetch failed: {e}")
        return []


def _hours_to_end(end_date: Optional[str]) -> float:
    if not end_date:
        return 9999.0
    try:
        end_dt = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return max(0.0, (end_dt - now).total_seconds() / 3600.0)
    except Exception:
        return 9999.0


def _score(candidate: dict) -> float:
    """Higher = better. Spread is the primary driver (paper finding:
    maker P&L = spread captured × fill rate); volume is the multiplier
    for fill rate."""
    spread_c = candidate["spread_cents"]
    volume = candidate["volume_24h"]
    return spread_c * (volume ** 0.5)


async def fetch_shortlist(
    top_n: int = DEFAULT_TOP_N,
    min_volume: float = MIN_VOLUME_USD,
    min_spread_cents: float = MIN_SPREAD_CENTS,
) -> list[dict]:
    """Return the top N market candidates for maker mode.

    Each candidate dict has: token_id, condition_id, question, mid, spread_cents,
    volume_24h, hours_to_end, score.
    """
    events = await _fetch_crypto_events()
    candidates = []
    for e in events:
        for m in e.get("markets") or []:
            try:
                bid = float(m.get("bestBid") or 0)
                ask = float(m.get("bestAsk") or 0)
            except (ValueError, TypeError):
                continue
            spread = ask - bid
            spread_c = round(spread * 100, 2)
            mid = (bid + ask) / 2 if (bid and ask) else 0
            volume_24h = float(m.get("volume24hr") or 0)
            hours_left = _hours_to_end(m.get("endDate"))

            if not (PRICE_LOW < mid < PRICE_HIGH):
                continue
            if volume_24h < min_volume:
                continue
            if spread_c < min_spread_cents:
                continue
            if hours_left < MIN_HOURS_TO_END:
                continue
            if hours_left > MAX_HOURS_TO_END:
                continue  # long-dated markets opt-in only via config override
            try:
                tok_ids = json.loads(m.get("clobTokenIds") or "[]")
                token_id = tok_ids[0] if tok_ids else None
            except Exception:
                token_id = None
            if not token_id:
                continue

            candidates.append({
                "token_id": token_id,
                "condition_id": m.get("conditionId"),
                "question": (m.get("question") or "")[:120],
                "mid": mid,
                "bid": bid,
                "ask": ask,
                "spread_cents": spread_c,
                "volume_24h": volume_24h,
                "hours_to_end": round(hours_left, 1),
            })

    for c in candidates:
        c["score"] = round(_score(c), 2)
    candidates.sort(key=lambda c: -c["score"])
    return candidates[:top_n]


async def resolve_targets() -> list[dict]:
    """Return the list of target market dicts the maker should target this
    cycle.

    Each dict has at minimum {token_id, condition_id, question, mid,
    spread_cents}. condition_id is required by the trade-proxy's pre-flight.

    If config.maker_target_token_ids is non-empty, use those (with empty
    condition_id — pre-flight will skip gracefully).  Otherwise auto-pick.
    """
    override = settings.maker_target_token_ids or []
    if override:
        logger.info(f"maker targets from config override: {len(override)} ids")
        return [{"token_id": tid, "condition_id": None, "question": "(override)",
                 "mid": 0.5, "spread_cents": 0.0} for tid in override]
    shortlist = await fetch_shortlist()
    logger.info(f"maker targets auto-picked: {len(shortlist)} markets — "
                f"{[c['question'][:50] for c in shortlist]}")
    return shortlist
