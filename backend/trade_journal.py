"""
Trade Journal — Append-only audit trail for all strategy trades.

Every entry/exit is logged to data/trade_journal.jsonl with full context.
This file is the source of truth for what the strategy engine has done.
"""
import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from loguru import logger

JOURNAL_PATH = Path(__file__).parent.parent / "data" / "trade_journal.jsonl"


class TradeJournal:
    """Append-only trade journal with query methods."""

    def log_entry(
        self,
        strategy: str,
        action: str,  # ENTER or EXIT
        market_question: str,
        market_slug: str,
        token_id: str,
        side: str,  # BUY or SELL
        price: float,
        shares: float,
        amount_usd: float,
        reason: str,
        order_id: Optional[str] = None,
        # Exit-specific fields
        entry_price: Optional[float] = None,
        pnl_usd: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        exit_reason: Optional[str] = None,
    ):
        """Append a trade entry to the journal."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "strategy": strategy,
            "action": action,
            "market_question": market_question,
            "market_slug": market_slug,
            "token_id": token_id,
            "side": side,
            "price": price,
            "shares": shares,
            "amount_usd": amount_usd,
            "reason": reason,
            "order_id": order_id,
        }
        if action == "EXIT":
            entry["entry_price"] = entry_price
            entry["pnl_usd"] = pnl_usd
            entry["pnl_pct"] = pnl_pct
            entry["exit_reason"] = exit_reason

        try:
            JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(JOURNAL_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
            logger.info(f"📓 Journal: {action} {strategy} | {market_question[:50]} | ${amount_usd:.2f}")
        except Exception as e:
            logger.error(f"Failed to write trade journal: {e}")

    def get_history(self, limit: int = 100) -> List[dict]:
        """Return all journal entries, most recent first."""
        if not JOURNAL_PATH.exists():
            return []
        entries = []
        for line in JOURNAL_PATH.read_text().strip().split("\n"):
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        entries.reverse()
        return entries[:limit]

    def get_open_positions(self) -> List[dict]:
        """Return positions that have an ENTER but no matching EXIT.

        Aggregates duplicate ENTERs on the same token_id: amount_usd and shares
        are summed, all other fields come from the most recent ENTER. This
        prevents the historical duplicate-trade bug (Apr 2026, 9× same Iran
        market in 5 hours) from corrupting downstream P&L math — the legacy
        version overwrote prior ENTERs and hid the real total exposure.
        """
        if not JOURNAL_PATH.exists():
            return []

        enters = {}  # token_id -> aggregated entry
        for line in JOURNAL_PATH.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            token_id = entry.get("token_id", "")
            if entry["action"] == "ENTER":
                if token_id in enters:
                    # Aggregate dollar exposure and shares; keep latest entry
                    # for descriptive fields (timestamp, reason).
                    prev = enters[token_id]
                    entry = dict(entry)
                    entry["amount_usd"] = (prev.get("amount_usd") or 0) + (entry.get("amount_usd") or 0)
                    entry["shares"] = (prev.get("shares") or 0) + (entry.get("shares") or 0)
                    entry["_entries_aggregated"] = (prev.get("_entries_aggregated") or 1) + 1
                enters[token_id] = entry
            elif entry["action"] == "EXIT" and token_id in enters:
                del enters[token_id]

        return list(enters.values())

    def get_performance(self) -> dict:
        """Compute P&L summary from journal. EXIT entries with pnl_usd=None
        (unresolved / couldn't determine outcome) are excluded from win/loss
        counts so the win rate isn't polluted by unknowns."""
        if not JOURNAL_PATH.exists():
            return {"total_pnl": 0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "unresolved": 0, "by_strategy": {}}

        exits = []
        for line in JOURNAL_PATH.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry["action"] == "EXIT":
                    exits.append(entry)
            except json.JSONDecodeError:
                continue

        # Resolved = has a real P&L number. Unknown = pnl_usd is None.
        resolved = [e for e in exits if e.get("pnl_usd") is not None]
        unresolved = [e for e in exits if e.get("pnl_usd") is None]

        total_pnl = sum(e["pnl_usd"] for e in resolved)
        wins = sum(1 for e in resolved if e["pnl_usd"] > 0)
        losses = sum(1 for e in resolved if e["pnl_usd"] <= 0)

        by_strategy = {}
        for e in resolved:
            strat = e.get("strategy", "unknown")
            if strat not in by_strategy:
                by_strategy[strat] = {"pnl": 0, "trades": 0, "wins": 0}
            by_strategy[strat]["pnl"] += e["pnl_usd"]
            by_strategy[strat]["trades"] += 1
            if e["pnl_usd"] > 0:
                by_strategy[strat]["wins"] += 1

        return {
            "total_pnl": round(total_pnl, 2),
            "trades": len(resolved),
            "wins": wins,
            "losses": losses,
            "unresolved": len(unresolved),
            "win_rate": round(wins / len(resolved), 2) if resolved else 0,
            "by_strategy": by_strategy,
        }

    def has_open_position(self, token_id: str) -> bool:
        """Check if there's already an open position for this token."""
        return any(p["token_id"] == token_id for p in self.get_open_positions())

    def get_total_exposure(self) -> float:
        """Sum of amount_usd for all open positions."""
        return sum(p.get("amount_usd", 0) for p in self.get_open_positions())

    # ------------------------------------------------------------------
    # Market-maker events (Pad 2)
    # ------------------------------------------------------------------
    # Three new actions, separate from ENTER/EXIT to keep legacy P&L
    # reports clean:
    #   LIMIT_POST   — we placed a GTC limit order
    #   LIMIT_CANCEL — we cancelled an open limit order
    #   LIMIT_FILL   — an open order filled (partial or full)
    #
    # Position state for maker mode is derived from LIMIT_FILL records:
    # BUY fills increase shares; SELL fills decrease them. Avg entry price
    # is share-weighted across BUY fills since the last time shares hit
    # zero. Open orders are LIMIT_POST records minus matching LIMIT_CANCEL
    # and minus orders whose order_id has a fully-matched LIMIT_FILL.

    def log_maker_event(
        self,
        event_type: str,  # LIMIT_POST | LIMIT_CANCEL | LIMIT_FILL
        token_id: str,
        order_id: str,
        side: str,         # BUY or SELL
        price: float,
        size: float,       # shares posted/cancelled/filled
        market_question: str = "",
        market_slug: str = "",
        reason: str = "",
        fill_price: Optional[float] = None,  # only for LIMIT_FILL — may differ from posted price
    ):
        if event_type not in ("LIMIT_POST", "LIMIT_CANCEL", "LIMIT_FILL"):
            logger.error(f"Unknown maker event type: {event_type}")
            return
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "strategy": "maker",
            "action": event_type,
            "market_question": market_question,
            "market_slug": market_slug,
            "token_id": token_id,
            "order_id": order_id,
            "side": (side or "").upper(),
            "price": price,
            "size": size,
        }
        if event_type == "LIMIT_FILL":
            entry["fill_price"] = fill_price if fill_price is not None else price
            entry["amount_usd"] = round(size * (fill_price or price), 4)
        if reason:
            entry["reason"] = reason
        try:
            JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(JOURNAL_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
            logger.info(
                f"📓 Journal: {event_type} {side} {market_question[:40]} "
                f"@ {price:.3f} × {size:.2f} sh  ord={order_id[:12] if order_id else '-'}"
            )
        except Exception as e:
            logger.error(f"Failed to write maker journal: {e}")

    def _iter_maker_events(self) -> List[dict]:
        """All maker journal entries in file order."""
        if not JOURNAL_PATH.exists():
            return []
        out = []
        for line in JOURNAL_PATH.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("strategy") == "maker":
                out.append(entry)
        return out

    def get_maker_open_orders(self) -> List[dict]:
        """Return LIMIT_POST records whose order_id has not been cancelled or
        fully filled. Each result includes how much has been filled so far."""
        posts: dict[str, dict] = {}
        filled_size: dict[str, float] = {}
        cancelled: set = set()
        for e in self._iter_maker_events():
            oid = e.get("order_id") or ""
            if not oid:
                continue
            action = e["action"]
            if action == "LIMIT_POST":
                posts[oid] = e
                filled_size.setdefault(oid, 0.0)
            elif action == "LIMIT_FILL":
                filled_size[oid] = filled_size.get(oid, 0.0) + float(e.get("size") or 0)
            elif action == "LIMIT_CANCEL":
                cancelled.add(oid)

        out = []
        for oid, post in posts.items():
            if oid in cancelled:
                continue
            posted_size = float(post.get("size") or 0)
            already_filled = filled_size.get(oid, 0.0)
            remaining = posted_size - already_filled
            if remaining <= 0.0001:
                continue  # fully filled
            row = dict(post)
            row["size_remaining"] = round(remaining, 4)
            row["size_filled"] = round(already_filled, 4)
            out.append(row)
        return out

    def get_maker_position(self, token_id: str) -> dict:
        """Compute shares held + avg entry price for a token from LIMIT_FILL
        records. Resets on every zero-crossing (FIFO-ish — sells close out
        whatever's open at their average cost).

        Returns: {"shares": float, "avg_entry_price": float, "opened_at": iso8601|None}
        """
        shares = 0.0
        cost_basis = 0.0  # USD invested in current position
        opened_at: Optional[str] = None
        for e in self._iter_maker_events():
            if e["action"] != "LIMIT_FILL":
                continue
            if e.get("token_id") != token_id:
                continue
            side = (e.get("side") or "").upper()
            sz = float(e.get("size") or 0)
            px = float(e.get("fill_price") or e.get("price") or 0)
            if side == "BUY":
                if shares <= 0.0001:
                    opened_at = e.get("timestamp")
                    cost_basis = 0.0
                shares += sz
                cost_basis += sz * px
            elif side == "SELL":
                shares -= sz
                if shares <= 0.0001:
                    shares = 0.0
                    cost_basis = 0.0
                    opened_at = None
                else:
                    # partial close — reduce cost basis proportionally
                    cost_basis = max(0.0, cost_basis - sz * (cost_basis / (shares + sz)))
        avg = (cost_basis / shares) if shares > 0.0001 else 0.0
        return {"shares": round(shares, 4), "avg_entry_price": round(avg, 4), "opened_at": opened_at}

    def get_maker_performance(self) -> dict:
        """Cumulative maker P&L from LIMIT_FILL records. P&L is realized
        only on SELL fills against the running BUY cost basis."""
        per_token_shares: dict[str, float] = {}
        per_token_cost: dict[str, float] = {}
        realized_pnl = 0.0
        buys = sells = 0
        for e in self._iter_maker_events():
            if e["action"] != "LIMIT_FILL":
                continue
            tok = e.get("token_id", "")
            side = (e.get("side") or "").upper()
            sz = float(e.get("size") or 0)
            px = float(e.get("fill_price") or e.get("price") or 0)
            shares = per_token_shares.get(tok, 0.0)
            cost = per_token_cost.get(tok, 0.0)
            if side == "BUY":
                shares += sz
                cost += sz * px
                buys += 1
            elif side == "SELL" and shares > 0.0001:
                avg = cost / shares
                realized_pnl += sz * (px - avg)
                shares -= sz
                cost -= sz * avg
                sells += 1
                if shares <= 0.0001:
                    shares = 0.0
                    cost = 0.0
            per_token_shares[tok] = shares
            per_token_cost[tok] = cost
        return {
            "realized_pnl": round(realized_pnl, 4),
            "buys": buys,
            "sells": sells,
            "open_tokens": {k: round(v, 4) for k, v in per_token_shares.items() if v > 0.0001},
        }


# Singleton
journal = TradeJournal()
