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
from .polymarket_client import PolymarketClient
from .trade_journal import journal
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
        # Previous-cycle open orders snapshot — used to detect fills by
        # diffing against the current cycle's open orders. Order_id ->
        # {size_original, size_remaining, side, price, ...}
        self._prev_open_orders: dict[str, dict] = {}
        # Map token_id -> question for human-readable journal entries.
        self._token_question: dict[str, str] = {}
        # Set of order_ids we cancelled this run — used to distinguish
        # 'order disappeared because we cancelled' from 'order filled'.
        self._cancelled_order_ids: set = set()
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

            # Refresh question map for journal entries
            for t in targets:
                self._token_question[t["token_id"]] = t.get("question", "")

            open_orders = await maker_proxy.list_open_orders()

            # Fill detection — compare prev snapshot to current. Any order
            # that was open last cycle but isn't now (and wasn't cancelled by
            # us) is a full fill at its posted price. Orders still open but
            # with extra size_matched are partial fills.
            self._detect_and_log_fills(open_orders)
            # Snapshot current open orders for next cycle's diff
            self._prev_open_orders = {
                (o.get("order_id") or ""): o for o in open_orders if o.get("order_id")
            }

            target_ids = {t["token_id"] for t in targets}
            async with PolymarketClient() as client:
                live_positions = await self._fetch_live_positions(client)
                running_exposure = self._sum_exposure(open_orders, live_positions, target_ids)
                maker_exposure = running_exposure
                intents: list[Intent] = []
                for target in targets:
                    state = await self._build_state(target, client, open_orders, live_positions)
                    if state is None:
                        continue
                    market_intents = self._decide(state, running_exposure)
                    for it in market_intents:
                        if it.action == "POST_BID":
                            running_exposure += it.price * it.size
                    intents.extend(market_intents)

            wallet_exposure = self._sum_exposure(open_orders, live_positions, None)
            logger.info(
                f"{prefix} cycle {self._cycle_count}: targets={len(targets)} "
                f"open_orders={len(open_orders)} maker_exp=${maker_exposure:.2f} "
                f"wallet_exp=${wallet_exposure:.2f} intents={len(intents)}"
            )

            for intent in intents:
                self._track_intent(intent)
                logger.info(f"{prefix}   {intent.describe()}")
                if not settings.maker_dry_run:
                    await self._execute(intent)

        except Exception as e:
            logger.error(f"{prefix} cycle error: {e}", exc_info=True)

    def get_status(self) -> dict:
        open_orders = journal.get_maker_open_orders()
        perf = journal.get_maker_performance()
        return {
            "mode": settings.agent_mode,
            "dry_run": settings.maker_dry_run,
            "enabled": settings.agent_enabled,
            "cycle_count": self._cycle_count,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "open_orders_count": len(open_orders),
            "open_orders": open_orders[:20],
            "open_positions": perf.get("open_tokens", {}),
            "realized_pnl": perf.get("realized_pnl", 0),
            "fills_buy": perf.get("buys", 0),
            "fills_sell": perf.get("sells", 0),
            "recent_intents": self._recent_intents[-20:],
        }

    # ---- State assembly -----------------------------------------------

    async def _build_state(
        self, target: dict, client, open_orders: list[dict], live_positions: list[dict]
    ) -> Optional[MarketState]:
        token_id = target["token_id"]
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

        pos = journal.get_maker_position(token_id)
        # Prefer journal-derived shares if it disagrees with live API (e.g.
        # if the maker just filled a batch but Polymarket's API hasn't
        # propagated yet). Journal is the source of truth for entry price.
        if pos.get("shares", 0) > 0.0001:
            held = max(held, pos["shares"])
        avg_entry = float(pos.get("avg_entry_price") or 0)
        opened_at_iso = pos.get("opened_at")
        age_h = 0.0
        if opened_at_iso:
            try:
                opened = datetime.fromisoformat(opened_at_iso)
                if opened.tzinfo is None:
                    opened = opened.replace(tzinfo=timezone.utc)
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

    async def _fetch_live_positions(self, client) -> list[dict]:
        try:
            return await client.get_user_positions(settings.poly_wallet_address or "") or []
        except Exception as e:
            logger.warning(f"live positions fetch failed: {e}")
            return []

    def _sum_exposure(
        self, open_orders: list[dict], live_positions: list[dict],
        only_tokens: Optional[set[str]] = None,
    ) -> float:
        """Sum USD exposure. If only_tokens is set, restrict to those token
        IDs (used to compute maker-mode exposure vs whole-wallet exposure)."""
        order_usd = 0.0
        for o in open_orders:
            if (o.get("side") or "").upper() != "BUY":
                continue
            if only_tokens and o.get("token_id") not in only_tokens:
                continue
            size = float(o.get("size_original") or 0) - float(o.get("size_remaining") or 0)
            remaining = float(o.get("size_original") or 0) - size
            order_usd += remaining * float(o.get("price") or 0)
        held_usd = 0.0
        for p in live_positions:
            tok = p.get("asset") or p.get("token_id")
            if only_tokens and tok not in only_tokens:
                continue
            held_usd += float(p.get("initialValue") or 0)
        return order_usd + held_usd

    # ---- Decision logic -----------------------------------------------

    def _decide(self, st: MarketState, total_maker_exposure: float = 0.0) -> list[Intent]:
        """Generate intents for one market. Pure function of state — no I/O.

        total_maker_exposure is the running sum across markets evaluated this
        cycle so far — used to enforce maker_max_total without leaking past
        the cap when multiple targets all want to post fresh bids.
        """
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

        room_market = settings.maker_max_per_market - market_exposure
        room_total = settings.maker_max_total - total_maker_exposure
        room = min(room_market, room_total)
        if room < 1.0:
            return intents  # no room (per-market or total cap)

        # Bid price: best_bid (join queue) OR best_bid + tick (improve), but
        # only if improving still leaves >= 1 tick spread to best_ask.
        target_bid = st.best_bid
        if st.best_ask - (st.best_bid + tick) >= tick:
            target_bid = round(st.best_bid + tick, 4)
        # Size in shares. Polymarket enforces a per-market minimum notional
        # ($1 binary / $5 multi-outcome); float math like 17.36 * 0.288 lands
        # at 4.9996 and fails the strict `< min` check. Ceil-up the shares
        # AND add one extra cent of size so notional always strictly clears.
        if target_bid <= 0:
            return intents
        import math
        target_notional = min(room, settings.maker_max_per_market)
        size = (math.ceil((target_notional / target_bid) * 100) + 1) / 100
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
        question = self._token_question.get(intent.token_id, "")
        if intent.action == "POST_BID":
            resp = await maker_proxy.place_limit(
                token_id=intent.token_id, price=intent.price, size=intent.size,
                side="BUY", condition_id=intent.condition_id,
            )
            if resp and resp.get("success"):
                oid = resp.get("order_id") or ""
                logger.info(f"[MAKER] bid posted, order_id={oid}")
                journal.log_maker_event(
                    event_type="LIMIT_POST", token_id=intent.token_id,
                    order_id=oid, side="BUY", price=intent.price,
                    size=intent.size, market_question=question,
                    reason=intent.reason,
                )
            else:
                logger.warning(f"[MAKER] bid post failed: {resp}")
        elif intent.action == "POST_ASK":
            resp = await maker_proxy.place_limit(
                token_id=intent.token_id, price=intent.price, size=intent.size,
                side="SELL", condition_id=intent.condition_id,
            )
            if resp and resp.get("success"):
                oid = resp.get("order_id") or ""
                logger.info(f"[MAKER] ask posted, order_id={oid}")
                journal.log_maker_event(
                    event_type="LIMIT_POST", token_id=intent.token_id,
                    order_id=oid, side="SELL", price=intent.price,
                    size=intent.size, market_question=question,
                    reason=intent.reason,
                )
            else:
                logger.warning(f"[MAKER] ask post failed: {resp}")
        elif intent.action == "CANCEL":
            if intent.order_id:
                ok = await maker_proxy.cancel_order(intent.order_id)
                logger.info(f"[MAKER] cancel {intent.order_id[:12]}: {ok}")
                if ok:
                    self._cancelled_order_ids.add(intent.order_id)
                    # Look up posted side/price from prev snapshot for log clarity
                    prev = self._prev_open_orders.get(intent.order_id, {})
                    journal.log_maker_event(
                        event_type="LIMIT_CANCEL", token_id=intent.token_id,
                        order_id=intent.order_id,
                        side=str(prev.get("side") or ""),
                        price=float(prev.get("price") or 0),
                        size=float(prev.get("size_original") or 0),
                        market_question=question, reason=intent.reason,
                    )
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

    def _detect_and_log_fills(self, current_open_orders: list[dict]):
        """Diff current open orders against last cycle's snapshot. Log
        LIMIT_FILL records for:
          - Orders no longer open that weren't cancelled by us (full fill)
          - Orders still open but with extra size_matched since last cycle
            (partial fill)

        GTC limit orders always fill at YOUR posted price (you're the
        maker), so we use the previously-recorded price as the fill price.
        """
        current_by_id = {(o.get("order_id") or ""): o for o in current_open_orders if o.get("order_id")}

        # Pull already-logged fill sizes per order so partial-fill accounting
        # doesn't double-count across cycles.
        already_filled: dict[str, float] = {}
        for e in journal._iter_maker_events():
            if e["action"] == "LIMIT_FILL":
                oid = e.get("order_id") or ""
                already_filled[oid] = already_filled.get(oid, 0.0) + float(e.get("size") or 0)

        # 1) Orders that disappeared from open list
        for oid, prev in self._prev_open_orders.items():
            if oid in current_by_id:
                continue
            if oid in self._cancelled_order_ids:
                continue  # we cancelled it ourselves
            posted = float(prev.get("size_original") or 0)
            unfilled = posted - already_filled.get(oid, 0.0)
            if unfilled <= 0.0001:
                continue  # already fully accounted for
            journal.log_maker_event(
                event_type="LIMIT_FILL",
                token_id=prev.get("token_id") or "",
                order_id=oid,
                side=str(prev.get("side") or ""),
                price=float(prev.get("price") or 0),
                size=unfilled,
                fill_price=float(prev.get("price") or 0),
                market_question=self._token_question.get(prev.get("token_id") or "", ""),
                reason="detected: order disappeared from book",
            )

        # 2) Orders still open but with new matches
        for oid, cur in current_by_id.items():
            posted = float(cur.get("size_original") or 0)
            remaining = float(cur.get("size_remaining") or 0)
            # Polymarket's /orders returns 'size_matched' separately in V2 — be
            # defensive about which field carries the filled amount:
            filled_proxy = posted - remaining
            if filled_proxy <= 0.0001:
                continue
            delta = filled_proxy - already_filled.get(oid, 0.0)
            if delta <= 0.0001:
                continue
            journal.log_maker_event(
                event_type="LIMIT_FILL",
                token_id=cur.get("token_id") or "",
                order_id=oid,
                side=str(cur.get("side") or ""),
                price=float(cur.get("price") or 0),
                size=delta,
                fill_price=float(cur.get("price") or 0),
                market_question=self._token_question.get(cur.get("token_id") or "", ""),
                reason="detected: partial fill",
            )

        # Reset cancellation flags — they apply to this cycle's fill check only.
        self._cancelled_order_ids = set()

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
