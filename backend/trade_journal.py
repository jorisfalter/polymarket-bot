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


# Singleton
journal = TradeJournal()
