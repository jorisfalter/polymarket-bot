"""
Market-maker mode — Pad 2 from docs/research/akey-paper-implications.md

Replaces the legacy 7-strategy AI agent. Posts GTC limit bids on a small
shortlist of crypto-price markets, waits for taker flow to fill them,
then posts exit asks to capture the spread.

Cycle (every maker_cycle_seconds):
  1. Resolve target markets (auto-pick top 3 by score, or use override).
  2. Fetch current open orders + live positions.
  3. Per target:
     a. EXIT — if we hold shares and no exit ask open, post one.
     b. RE-PRICE — if our existing bid/ask drifted from mid > threshold,
        cancel and repost.
     c. ENTRY — if we have no open bid and exposure < cap, post bid.
     d. TIMEOUT — if a position has been open > timeout_hours, FAK exit.

Two execution modes:
  - dry_run = True (default during shakedown): logs every intended
    action, makes NO real orders. Use this for 48h observation to
    validate fill assumptions.
  - dry_run = False: actually places orders via the trade-proxy.

Position tracking is dual-source:
  - Live positions from Polymarket Data API (truth for shares held)
  - In-memory entry-price map (until journal LIMIT_FILL integration
    lands — task #56)
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from .config import settings
from .polymarket_client import get_client
from . import maker_proxy
from . import maker_shortlist


# -----------------------------------------------------------------------------
# Intent model — the cycle produces Intents; the executor turns them into
# proxy calls. This split keeps dry-run honest: same decisions, no I/O.
# -----------------------------------------------------------------------------

@dataclass
class Intent:
    action: str  # "POST_BID" | "POST_ASK" | "CANCEL" | "FAK_EXIT" | "NOOP"
    token_id: str = ""
    condition_id: Optional[str] = None
    price: float = 0.0
    size: float = 0.0  # shares
    order_id: Optional[str] = None  # for CANCEL
    reason: str = ""

    def describe(self) -> str:
        if self.action == "POST_BID":
            return f"POST_BID  {self.token_id[:12]}  @ {self.price:.3f} × {self.size:.2f} sh   [{self.reason}]"
        if self.action == "POST_ASK":
            return f"POST_ASK  {self.token_id[:12]}  @ {self.price:.3f} × {self.size:.2f} sh   [{self.reason}]"
        if self.action == "CANCEL":
            return f"CANCEL    {self.token_id[:12]}  order={self.order_id}              [{self.reason}]"
        if self.action == "FAK_EXIT":
            return f"FAK_EXIT  {self.token_id[:12]}  × {self.size:.2f} sh                  [{self.reason}]"
        return f"NOOP      {self.token_id[:12]}                                       [{self.reason}]"


# -----------------------------------------------------------------------------
# State
# -----------------------------------------------------------------------------

@dataclass
class MarketState:
    """Per-market snapshot for one cycle."""
    token_id: str
    condition_id: Optional[str]
    question: str
    best_bid: float
    best_ask: float
    mid: float
    our_open_bids: list[dict] = field(default_factory=list)
    our_open_asks: list[dict] = field(default_factory=list)
    held_shares: float = 0.0
    avg_entry_price: float = 0.0
    position_age_hours: float = 0.0


class MarketMaker:
    def __init__(self):
        # Track entry prices in-memory until journal integration (task #56).
        # Persists across cycles within a process; lost on restart.
        # {token_id: {"shares": float, "avg_entry": float, "opened_at": iso8601}}
        self._entries: dict[str, dict] = {}
        self._last_cycle_at: Optional[datetime] = None
        self._cycle_count: int = 0
        # Recent intents for the dashboard.
        self._recent_intents: list[dict] = []

    # ---- Public API ---------------------------------------------------

    async def run_cycle(self):
        """Single cycle. Called by scheduler every maker_cycle_seconds."""
        if not settings.agent_enabled:
            return
        if settings.agent_mode != "maker":
            return

        self._cycle_count += 1
        self._last_cycle_at = datetime.now(timezone.utc)
        prefix = "[MAKER:DRY]" if settings.maker_dry_run else "[MAKER:LIVE]"

        try:
            targets = await maker_shortlist.resolve_targets()
            if not targets:
                logger.info(f"{prefix} cycle {self._cycle_count}: no targets — sleeping")
                return

            open_orders = await maker_proxy.list_open_orders()
            live_positions = await self._fetch_live_positions()

            intents: list[Intent] = []
            for target in targets:
                state = await self._build_state(target, open_orders, live_positions)
                if state is None:
                    continue
                intents.extend(self._decide(state))

            total_exposure = self._sum_exposure(open_orders, live_positions)
            logger.info(
                f"{prefix} cycle {self._cycle_count}: targets={len(targets)} "
                f"open_orders={len(open_orders)} exposure=${total_exposure:.2f} "
                f"intents={len(intents)}"
            )

            for intent in intents:
                self._track_intent(intent)
                logger.info(f"{prefix}   {intent.describe()}")
                if not settings.maker_dry_run:
                    await self._execute(intent)

        except Exception as e:
            logger.error(f"{prefix} cycle error: {e}", exc_info=True)

    def get_status(self) -> dict:
        return {
            "mode": settings.agent_mode,
            "dry_run": settings.maker_dry_run,
            "enabled": settings.agent_enabled,
            "cycle_count": self._cycle_count,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "tracked_entries": len(self._entries),
            "recent_intents": self._recent_intents[-20:],
        }

    # ---- State assembly -----------------------------------------------

    async def _build_state(
        self, target: dict, open_orders: list[dict], live_positions: list[dict]
    ) -> Optional[MarketState]:
        token_id = target["token_id"]
        client = await get_client()
        try:
            book = await client.get_order_book(token_id)
        except Exception as e:
            logger.warning(f"book fetch failed for {token_id[:12]}: {e}")
            return None
        if not book:
            return None

        # Polymarket Data API book shape: {"bids": [{"price","size"}], "asks": [...]}
        bids_raw = book.get("bids") or []
        asks_raw = book.get("asks") or []
        # Polymarket lists bids ASCENDING and asks DESCENDING by price — the
        # "best" of each side is the LAST element. (Verified via /book.)
        def _px(level) -> float:
            try:
                return float(level.get("price", 0)) if isinstance(level, dict) else 0
            except Exception:
                return 0
        best_bid = max((_px(b) for b in bids_raw), default=0.0)
        best_ask = min((_px(a) for a in asks_raw if _px(a) > 0), default=0.0)
        if best_bid <= 0 or best_ask <= 0 or best_ask <= best_bid:
            return None  # locked / crossed / empty
        mid = (best_bid + best_ask) / 2

        # Slice our open orders by token + side. Proxy returns side as str.
        our_bids = [
            o for o in open_orders
            if o.get("token_id") == token_id and (o.get("side") or "").upper() == "BUY"
        ]
        our_asks = [
            o for o in open_orders
            if o.get("token_id") == token_id and (o.get("side") or "").upper() == "SELL"
        ]

        # Live position for this token.
        held = 0.0
        for p in live_positions:
            # Data API uses "asset" for the token id.
            if (p.get("asset") or p.get("token_id")) == token_id:
                held = float(p.get("size") or 0)
                break

        entry = self._entries.get(token_id) or {}
        avg_entry = float(entry.get("avg_entry") or 0)
        opened_at_iso = entry.get("opened_at")
        age_h = 0.0
        if opened_at_iso:
            try:
                opened = datetime.fromisoformat(opened_at_iso)
                age_h = (datetime.now(timezone.utc) - opened).total_seconds() / 3600
            except Exception:
                pass

        return MarketState(
            token_id=token_id,
            condition_id=target.get("condition_id"),
            question=target.get("question", ""),
            best_bid=best_bid,
            best_ask=best_ask,
            mid=mid,
            our_open_bids=our_bids,
            our_open_asks=our_asks,
            held_shares=held,
            avg_entry_price=avg_entry,
            position_age_hours=age_h,
        )

    async def _fetch_live_positions(self) -> list[dict]:
        client = await get_client()
        try:
            return await client.get_user_positions(settings.poly_wallet_address or "") or []
        except Exception as e:
            logger.warning(f"live positions fetch failed: {e}")
            return []

    def _sum_exposure(self, open_orders: list[dict], live_positions: list[dict]) -> float:
        # Open-order exposure: sum of (size_remaining × price) on BUY orders.
        order_usd = 0.0
        for o in open_orders:
            if (o.get("side") or "").upper() != "BUY":
                continue
            size = float(o.get("size_original") or 0) - float(o.get("size_remaining") or 0)
            remaining = float(o.get("size_original") or 0) - size
            order_usd += remaining * float(o.get("price") or 0)
        # Held-position exposure: shares × current mid (approximated as initialValue).
        held_usd = sum(float(p.get("initialValue") or 0) for p in live_positions)
        return order_usd + held_usd

    # ---- Decision logic -----------------------------------------------

    def _decide(self, st: MarketState) -> list[Intent]:
        """Generate intents for one market. Pure function of state — no I/O."""
        intents: list[Intent] = []
        tick = 0.01  # binary; neg_risk tighter handled at proxy quantization
        drift = settings.maker_drift_threshold_cents / 100.0
        exit_spread = settings.maker_exit_spread_cents / 100.0

        # --- TIMEOUT: force-exit stale positions ---
        if (st.held_shares > 0
                and st.position_age_hours > settings.maker_position_timeout_hours):
            intents.append(Intent(
                action="FAK_EXIT", token_id=st.token_id, size=st.held_shares,
                reason=f"position open {st.position_age_hours:.1f}h > timeout"
            ))
            # Cancel any open ask too, so the FAK doesn't race.
            for ask in st.our_open_asks:
                intents.append(Intent(
                    action="CANCEL", token_id=st.token_id,
                    order_id=ask.get("order_id"), reason="clear before timeout exit",
                ))
            return intents

        # --- EXIT: have shares, post or maintain ask ---
        if st.held_shares > 0.001:
            target_ask = max(round(st.avg_entry_price + exit_spread, 4), st.best_ask)
            if not st.our_open_asks:
                intents.append(Intent(
                    action="POST_ASK", token_id=st.token_id,
                    condition_id=st.condition_id, price=target_ask,
                    size=st.held_shares, reason="post exit on held shares",
                ))
            else:
                # If our ask drifted too far from current best_ask, reprice.
                cur_ask = st.our_open_asks[0]
                cur_price = float(cur_ask.get("price") or 0)
                if abs(cur_price - target_ask) > drift:
                    intents.append(Intent(
                        action="CANCEL", token_id=st.token_id,
                        order_id=cur_ask.get("order_id"),
                        reason=f"ask drift {abs(cur_price - target_ask)*100:.1f}c",
                    ))
                    intents.append(Intent(
                        action="POST_ASK", token_id=st.token_id,
                        condition_id=st.condition_id, price=target_ask,
                        size=st.held_shares, reason="repost after drift",
                    ))

        # --- ENTRY: post bid if room under cap ---
        # Exposure on this market = open-bid notional + held value
        own_bid_usd = sum(
            (float(o.get("size_original") or 0) - float(o.get("size_remaining") or 0)) * float(o.get("price") or 0)
            for o in st.our_open_bids
        )
        held_value = st.held_shares * st.mid
        market_exposure = own_bid_usd + held_value

        room = settings.maker_max_per_market - market_exposure
        if room < 1.0:
            return intents  # no room

        # Bid price: best_bid (join queue) OR best_bid + tick (improve), but
        # only if improving still leaves >= 1 tick spread to best_ask.
        target_bid = st.best_bid
        if st.best_ask - (st.best_bid + tick) >= tick:
            target_bid = round(st.best_bid + tick, 4)
        # Size in shares: how many can we buy with `room` at target_bid?
        if target_bid <= 0:
            return intents
        size = round(min(room, settings.maker_max_per_market) / target_bid, 2)
        if size < 1.0:
            return intents  # too small after rounding

        if not st.our_open_bids:
            intents.append(Intent(
                action="POST_BID", token_id=st.token_id,
                condition_id=st.condition_id, price=target_bid, size=size,
                reason=f"entry at mid {st.mid:.3f}",
            ))
        else:
            cur_bid = st.our_open_bids[0]
            cur_price = float(cur_bid.get("price") or 0)
            if abs(cur_price - target_bid) > drift:
                intents.append(Intent(
                    action="CANCEL", token_id=st.token_id,
                    order_id=cur_bid.get("order_id"),
                    reason=f"bid drift {abs(cur_price - target_bid)*100:.1f}c",
                ))
                intents.append(Intent(
                    action="POST_BID", token_id=st.token_id,
                    condition_id=st.condition_id, price=target_bid, size=size,
                    reason="repost after drift",
                ))

        return intents

    # ---- Execution -----------------------------------------------------

    async def _execute(self, intent: Intent):
        """Send an intent to the trade-proxy. Only called when dry_run=False."""
        if intent.action == "POST_BID":
            resp = await maker_proxy.place_limit(
                token_id=intent.token_id, price=intent.price, size=intent.size,
                side="BUY", condition_id=intent.condition_id,
            )
            if resp and resp.get("success"):
                logger.info(f"[MAKER] bid posted, order_id={resp.get('order_id')}")
            else:
                logger.warning(f"[MAKER] bid post failed: {resp}")
        elif intent.action == "POST_ASK":
            resp = await maker_proxy.place_limit(
                token_id=intent.token_id, price=intent.price, size=intent.size,
                side="SELL", condition_id=intent.condition_id,
            )
            if resp and resp.get("success"):
                logger.info(f"[MAKER] ask posted, order_id={resp.get('order_id')}")
            else:
                logger.warning(f"[MAKER] ask post failed: {resp}")
        elif intent.action == "CANCEL":
            if intent.order_id:
                ok = await maker_proxy.cancel_order(intent.order_id)
                logger.info(f"[MAKER] cancel {intent.order_id[:12]}: {ok}")
        elif intent.action == "FAK_EXIT":
            # Reuse the existing /sell endpoint for emergency exits.
            import httpx
            try:
                async with httpx.AsyncClient(timeout=30.0) as cx:
                    r = await cx.post(
                        f"{settings.trade_proxy_url}/sell",
                        json={"token_id": intent.token_id, "shares": intent.size},
                        headers={"Authorization": f"Bearer {settings.trade_proxy_secret}"},
                    )
                logger.info(f"[MAKER] FAK exit response: {r.json()}")
            except Exception as e:
                logger.error(f"[MAKER] FAK exit failed: {e}")

    def _track_intent(self, intent: Intent):
        self._recent_intents.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": intent.action,
            "token_id": intent.token_id[:24],
            "price": intent.price,
            "size": intent.size,
            "reason": intent.reason,
        })
        # Keep only last 200 in memory.
        if len(self._recent_intents) > 200:
            self._recent_intents = self._recent_intents[-200:]


# Module-level singleton (matches the pattern used by ai_agent, detector, etc.)
market_maker = MarketMaker()
