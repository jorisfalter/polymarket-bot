"""
External integrations for the AI Trading Agent.
- Twitter/X: posts thinking summaries each cycle
- Google Sheets: logs all trades to a shared spreadsheet
"""
import csv
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger

from .config import settings

TRADES_BACKUP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "trades_backup.csv"
)
_BACKUP_HEADERS = [
    "Timestamp", "Strategy", "Action", "Market", "Outcome",
    "Price", "Shares", "Amount USD", "Confidence", "Thesis/Reason", "Order ID", "P&L"
]


def _write_trade_backup(row: list):
    """Write trade to local CSV backup — always called, regardless of Sheets."""
    try:
        os.makedirs(os.path.dirname(TRADES_BACKUP_PATH), exist_ok=True)
        write_header = not os.path.exists(TRADES_BACKUP_PATH)
        with open(TRADES_BACKUP_PATH, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(_BACKUP_HEADERS)
            writer.writerow(row)
    except Exception as e:
        logger.warning(f"Trade backup write failed: {e}")

# ==================== TELEGRAM ====================

_telegram_bot = None


def _get_telegram_bot():
    """Lazy-init Telegram bot."""
    global _telegram_bot
    if _telegram_bot is not None:
        return _telegram_bot

    if not settings.telegram_bot_token:
        return None

    try:
        import telegram
        _telegram_bot = telegram.Bot(token=settings.telegram_bot_token)
        logger.info("Telegram bot initialized")
        return _telegram_bot
    except Exception as e:
        logger.warning(f"Telegram init failed: {e}")
        return None


async def send_telegram(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message to the configured Telegram chat."""
    if not settings.telegram_enabled or not settings.telegram_chat_id:
        return False

    bot = _get_telegram_bot()
    if not bot:
        return False

    try:
        # Telegram limit is 4096 chars — split at newlines if needed
        if len(text) > 4000:
            chunks = []
            remaining = text
            while remaining:
                if len(remaining) <= 4000:
                    chunks.append(remaining)
                    break
                cut = remaining[:4000].rfind("\n")
                if cut < 500:
                    cut = 4000
                chunks.append(remaining[:cut])
                remaining = remaining[cut:].lstrip()
            for chunk in chunks:
                await bot.send_message(
                    chat_id=settings.telegram_chat_id,
                    text=chunk,
                    parse_mode=parse_mode,
                )
        else:
            await bot.send_message(
                chat_id=settings.telegram_chat_id,
                text=text,
                parse_mode=parse_mode,
            )
        logger.debug("Telegram message sent")
        return True
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")
        return False


def _esc(text: str) -> str:
    """Escape HTML special chars so Telegram doesn't break parsing."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _trim(text: str, limit: int) -> str:
    """Trim to limit chars, cutting at last sentence/newline boundary. Adds … if trimmed."""
    if len(text) <= limit:
        return text
    chunk = text[:limit]
    # Try to cut at last newline or sentence end
    for sep in ("\n", ". ", "! ", "? ", "; "):
        pos = chunk.rfind(sep)
        if pos > limit // 2:
            return chunk[:pos + len(sep)].rstrip() + " …"
    return chunk.rstrip() + " …"


def format_thinking_telegram(decision: Dict) -> List[str]:
    """Format agent thinking as 1-4 separate Telegram messages.
    Each message stays under Telegram's 4096-char limit via send_telegram's splitter.
    Returns a list of message strings (each safe to send independently)."""
    now = datetime.utcnow().strftime("%H:%M UTC")
    messages = []

    # Message 1: Header + Portfolio/Exposure snapshot + Trades
    lines = [f"🧠 <b>Agent Cycle</b> — {now}"]

    portfolio = decision.get("_portfolio") or {}
    if portfolio:
        balance = portfolio.get("balance", 0) or 0
        exposure = portfolio.get("exposure", 0) or 0
        positions = portfolio.get("positions") or []
        max_exp = portfolio.get("max_exposure", 100) or 100
        max_pos = portfolio.get("max_positions", 10) or 10
        pct = (exposure / max_exp * 100) if max_exp else 0
        lines.append(
            f"\n💼 <b>EXPOSURE:</b> ${exposure:.2f} / ${max_exp:.0f} ({pct:.0f}%)"
            f" | Positions: {len(positions)}/{max_pos}"
            f" | Balance: ${balance:.2f}"
        )
        if positions:
            lines.append("<b>Open positions:</b>")
            for p in positions[:10]:
                q = _esc((p.get("market_question") or "?")[:55])
                side = p.get("side") or p.get("outcome") or "?"
                amt = p.get("amount_usd", 0) or 0
                entry = p.get("price", 0) or 0
                lines.append(f"  • {q} — {side} @ {entry:.2f}, ${amt:.2f}")

    trades = decision.get("trades", [])
    if trades:
        lines.append("\n💰 <b>TRADES:</b>")
        for t in trades:
            emoji = "🟢" if t.get("action") == "BUY" else "🔴"
            q = _esc((t.get("market_question") or "?")[:70])
            lines.append(f"{emoji} {t.get('action')} ${t.get('amount_usd',0):.2f} {t.get('outcome','?')} — <i>{q}</i>")
            lines.append(f"   conf {t.get('confidence',0):.0%} — {_esc(t.get('thesis','')[:200])}")

    messages.append("\n".join(lines))

    # Message 2: Full analysis (the agent's thinking, untrimmed)
    thinking = decision.get("thinking", "")
    if thinking:
        messages.append(f"📊 <b>ANALYSIS</b>\n\n{_esc(thinking)}")

    # Message 3: Theses (only if there are updates)
    theses = [t for t in decision.get("thesis_updates", []) if t.get("action","").upper() in ("CREATE","UPDATE","CLOSE")][:5]
    if theses:
        t_lines = ["📋 <b>THESES:</b>"]
        for t in theses:
            act = t.get("action","").upper()
            emoji = {"CREATE":"🆕","UPDATE":"🔄","CLOSE":"✅"}.get(act,"📋")
            conv = f" [{_esc(t.get('conviction',''))}]" if t.get("conviction") else ""
            note = _esc(t.get("note",""))
            t_lines.append(f"{emoji} <b>{_esc(t.get('title', t.get('id','?'))[:80])}</b>{conv}")
            if note:
                t_lines.append(f"   {note}")
        messages.append("\n".join(t_lines))

    # Message 4: Risk + watchlist (full, not trimmed)
    risk = decision.get("risk_assessment", "")
    watchlist = decision.get("watchlist_notes", "")
    if risk or watchlist:
        r_lines = []
        if risk:
            r_lines.append(f"⚠️ <b>RISK</b>\n{_esc(risk)}")
        if watchlist:
            r_lines.append(f"\n👀 <b>WATCHLIST</b>\n{_esc(watchlist)}")
        messages.append("\n".join(r_lines))

    return messages


def format_trade_telegram(
    strategy: str, action: str, market_question: str,
    outcome: str, price: float, amount_usd: float,
    reason: str, order_id: str = "",
) -> str:
    """Format a trade execution for Telegram."""
    emoji = "🟢" if action == "BUY" else "🔴"
    return (
        f"{emoji} <b>TRADE EXECUTED</b>\n\n"
        f"Strategy: {strategy}\n"
        f"Action: {action} {outcome}\n"
        f"Market: <i>{market_question[:80]}</i>\n"
        f"Price: {price:.4f} | Amount: ${amount_usd:.2f}\n"
        f"Reason: {reason[:150]}\n"
        + (f"Order: {order_id}" if order_id else "")
    )


# ==================== TWITTER/X ====================

_twitter_client = None


def _get_twitter_client():
    """Lazy-init Twitter client."""
    global _twitter_client
    if _twitter_client is not None:
        return _twitter_client

    if not all([
        settings.twitter_api_key,
        settings.twitter_api_secret,
        settings.twitter_access_token,
        settings.twitter_access_secret,
    ]):
        return None

    try:
        import tweepy
        _twitter_client = tweepy.Client(
            consumer_key=settings.twitter_api_key,
            consumer_secret=settings.twitter_api_secret,
            access_token=settings.twitter_access_token,
            access_token_secret=settings.twitter_access_secret,
        )
        logger.info("Twitter client initialized")
        return _twitter_client
    except Exception as e:
        logger.warning(f"Twitter init failed: {e}")
        return None


def post_tweet(text: str) -> Optional[str]:
    """Post a tweet or thread if over 280 chars. Returns first tweet ID or None."""
    if not settings.twitter_enabled:
        return None

    client = _get_twitter_client()
    if not client:
        return None

    try:
        if len(text) <= 280:
            response = client.create_tweet(text=text)
            tweet_id = response.data.get("id") if response.data else None
            logger.info(f"Tweet posted: {tweet_id}")
            return tweet_id

        # Split into thread
        chunks = _split_into_thread(text)
        first_id = None
        reply_to = None

        for i, chunk in enumerate(chunks):
            if reply_to:
                response = client.create_tweet(text=chunk, in_reply_to_tweet_id=reply_to)
            else:
                response = client.create_tweet(text=chunk)

            tweet_id = response.data.get("id") if response.data else None
            if i == 0:
                first_id = tweet_id
            reply_to = tweet_id
            logger.info(f"Thread {i+1}/{len(chunks)} posted: {tweet_id}")

        return first_id
    except Exception as e:
        logger.warning(f"Tweet failed: {e}")
        return None


def _split_into_thread(text: str, max_len: int = 275) -> list:
    """Split text into tweet-sized chunks, breaking at newlines or sentences."""
    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Try to break at newline
        cut = remaining[:max_len].rfind("\n")
        if cut < 100:
            # Try sentence break
            cut = remaining[:max_len].rfind(". ")
            if cut < 100:
                # Try space
                cut = remaining[:max_len].rfind(" ")
                if cut < 100:
                    cut = max_len

        chunk = remaining[:cut + 1].rstrip()
        remaining = remaining[cut + 1:].lstrip()
        if chunk:
            chunks.append(chunk)

    return chunks


def format_thinking_tweet(decision: Dict) -> str:
    """Format the agent's thinking into a rich tweet."""
    thinking = decision.get("thinking", "")
    trades = decision.get("trades", [])
    theses = decision.get("thesis_updates", [])
    watchlist = decision.get("watchlist_notes", "")
    risk = decision.get("risk_assessment", "")

    lines = []

    # Trade actions first (most interesting)
    if trades:
        for t in trades[:2]:
            action = t.get("action", "?")
            question = t.get("market_question", "?")[:45]
            amount = t.get("amount_usd", 0)
            conf = t.get("confidence", 0)
            lines.append(f"{'🟢' if action == 'BUY' else '🔴'} {action} ${amount:.2f} on \"{question}\" ({conf:.0%} confidence)")

    # Thesis updates
    if theses:
        for t in theses[:2]:
            action = t.get("action", "").upper()
            title = t.get("title", "")[:40]
            conviction = t.get("conviction", "")
            emoji = {"CREATE": "📋", "UPDATE": "🔄", "CLOSE": "✅"}.get(action, "📋")
            lines.append(f"{emoji} Thesis {action}: {title}" + (f" [{conviction}]" if conviction else ""))

    # Main thinking — take the meatiest part
    if thinking:
        # Skip boring openers, find substance
        sentences = [s.strip() for s in thinking.replace("\n", ". ").split(". ") if len(s.strip()) > 20]
        # Skip meta-sentences about portfolio/discipline, find market analysis
        skip_words = [
            "my portfolio", "my rules", "my exposure", "i have", "i need to",
            "i must", "this discipline", "zero-trade cycle", "cycle ",
            "consecutive", "portfolio stable", "portfolio:", "this is correct",
        ]
        good_sentences = [s for s in sentences if not any(skip in s.lower() for skip in skip_words)]
        if not good_sentences:
            good_sentences = sentences
        if good_sentences:
            analysis = ". ".join(good_sentences[:6]) + "."
            lines.append(analysis[:600])

    if not lines:
        lines.append("Scanning markets. No actionable signals this cycle. Patience.")

    tweet = "\n".join(lines)

    # Add timestamp to avoid duplicate content errors + hashtags
    now = datetime.utcnow().strftime("%H:%M UTC")
    tweet += f"\n\n[{now}] #Polymarket #AITrading"

    # No need to truncate — post_tweet handles threading
    return tweet


# ==================== GOOGLE SHEETS ====================

_spreadsheet = None


def _get_spreadsheet():
    """Lazy-init Google Sheets connection."""
    global _spreadsheet
    if _spreadsheet is not None:
        return _spreadsheet

    if not settings.google_sheets_id:
        return None

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        if settings.google_service_account_file:
            creds = Credentials.from_service_account_file(
                settings.google_service_account_file, scopes=scopes
            )
        elif settings.google_oauth_creds_file:
            import json as _json
            from google.oauth2.credentials import Credentials as UserCredentials
            from google.auth.transport.requests import Request
            with open(settings.google_oauth_creds_file) as f:
                cred_data = _json.load(f)
            creds = UserCredentials(
                token=None,
                refresh_token=cred_data.get("refresh_token"),
                client_id=cred_data.get("client_id"),
                client_secret=cred_data.get("client_secret"),
                token_uri="https://oauth2.googleapis.com/token",
            )
            creds.refresh(Request())
        else:
            from google.auth import default
            creds, _ = default(scopes=scopes)

        client = gspread.authorize(creds)
        _spreadsheet = client.open_by_key(settings.google_sheets_id)
        logger.info("Google Sheets connected")
        return _spreadsheet
    except Exception as e:
        logger.warning(f"Google Sheets init failed: {e}")
        return None


def _get_or_create_tab(name: str, headers: list) -> "gspread.Worksheet | None":
    """Get or create a worksheet tab with headers."""
    spreadsheet = _get_spreadsheet()
    if not spreadsheet:
        return None
    try:
        import gspread
        try:
            return spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(name, rows=2000, cols=len(headers))
            ws.update(f"A1:{chr(64 + len(headers))}1", [headers])
            ws.format(f"A1:{chr(64 + len(headers))}1", {"textFormat": {"bold": True}})
            return ws
    except Exception as e:
        logger.warning(f"Failed to get/create tab '{name}': {e}")
        return None


def log_trade_to_sheets(
    strategy: str,
    action: str,
    market_question: str,
    outcome: str = "",
    price: float = 0,
    shares: float = 0,
    amount_usd: float = 0,
    confidence: float = 0,
    reason: str = "",
    order_id: str = "",
    pnl: float = 0,
) -> bool:
    """Append a trade row to the Trades tab. Always writes local CSV backup. Returns True if Sheets succeeded."""
    global _spreadsheet

    row = [
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        strategy,
        action,
        market_question[:100],
        outcome,
        f"{price:.4f}",
        f"{shares:.4f}",
        f"{amount_usd:.2f}",
        f"{confidence:.0%}" if confidence else "",
        reason[:150],
        order_id or "",
        f"{pnl:.2f}" if pnl else "",
    ]

    # Always write to local backup first
    _write_trade_backup(row)

    # Then try Sheets
    ws = _get_or_create_tab("Trades", [
        "Timestamp", "Strategy", "Action", "Market",
        "Outcome", "Price", "Shares", "Amount USD",
        "Confidence", "Thesis/Reason", "Order ID", "P&L"
    ])
    if not ws:
        logger.warning(f"Sheets unavailable — trade saved to local backup only: {action} {market_question[:30]}")
        return False

    try:
        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.debug(f"Trade logged to Sheets: {action} {market_question[:30]}")
        return True
    except Exception as e:
        logger.warning(f"Sheets trade log failed: {e} — saved to local backup")
        # Reset connection so next call tries to reconnect
        _spreadsheet = None
        return False


def log_thinking_to_sheets(decision: Dict):
    """Log full thinking to the Agent Log tab — runs every 5 min."""
    ws = _get_or_create_tab("Agent Log", [
        "Timestamp", "Thinking", "Trades", "Thesis Updates",
        "Watchlist", "Risk Assessment", "Active Theses"
    ])
    if not ws:
        return

    try:
        trades_summary = "\n".join(
            f"{t.get('action')} ${t.get('amount_usd', 0):.2f} on {t.get('market_question', '?')[:50]} [{t.get('confidence', 0):.0%}] — {t.get('thesis', '')[:60]}"
            for t in decision.get("trades", [])
        ) or "No trades"

        thesis_summary = "\n".join(
            f"{t.get('action')} [{t.get('id')}] {t.get('title', '')[:40]} — {t.get('note', '')[:60]}"
            for t in decision.get("thesis_updates", [])
        ) or "No updates"

        row = [
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            decision.get("thinking", "")[:2000],
            trades_summary,
            thesis_summary,
            decision.get("watchlist_notes", "")[:500],
            decision.get("risk_assessment", "")[:500],
            ", ".join(
                f"[{t.get('id')}] {t.get('conviction', '?')}"
                for t in decision.get("_active_theses", [])
            ) or "",
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.debug("Thinking logged to Sheets")
    except Exception as e:
        logger.warning(f"Sheets thinking log failed: {e}")


# ==================== AIRTABLE ====================

_AIRTABLE_TABLE_NAME = "Trades"
_airtable_table_id: Optional[str] = None  # Cached after first lookup/create


def _get_airtable_table_id() -> Optional[str]:
    """Get or create the Trades table in Airtable. Returns table ID."""
    global _airtable_table_id
    if _airtable_table_id:
        return _airtable_table_id

    if not settings.airtable_pat or not settings.airtable_base_id:
        return None

    import httpx
    headers = {
        "Authorization": f"Bearer {settings.airtable_pat}",
        "Content-Type": "application/json",
    }

    # Check if table already exists
    try:
        r = httpx.get(
            f"https://api.airtable.com/v0/meta/bases/{settings.airtable_base_id}/tables",
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        for table in r.json().get("tables", []):
            if table["name"] == _AIRTABLE_TABLE_NAME:
                _airtable_table_id = table["id"]
                logger.info(f"Airtable: found existing '{_AIRTABLE_TABLE_NAME}' table")
                return _airtable_table_id
    except Exception as e:
        logger.warning(f"Airtable table lookup failed: {e}")
        return None

    # Create the table
    try:
        payload = {
            "name": _AIRTABLE_TABLE_NAME,
            "fields": [
                {"name": "Timestamp", "type": "singleLineText"},
                {"name": "Action", "type": "singleLineText"},
                {"name": "Market", "type": "multilineText"},
                {"name": "Outcome", "type": "singleLineText"},
                {"name": "Amount USD", "type": "number", "options": {"precision": 2}},
                {"name": "Price", "type": "number", "options": {"precision": 4}},
                {"name": "Shares", "type": "number", "options": {"precision": 4}},
                {"name": "Confidence", "type": "singleLineText"},
                {"name": "Thesis", "type": "multilineText"},
                {"name": "Order ID", "type": "singleLineText"},
                {"name": "P&L USD", "type": "number", "options": {"precision": 2}},
            ],
        }
        r = httpx.post(
            f"https://api.airtable.com/v0/meta/bases/{settings.airtable_base_id}/tables",
            headers=headers, json=payload, timeout=10,
        )
        r.raise_for_status()
        _airtable_table_id = r.json()["id"]
        logger.info(f"Airtable: created '{_AIRTABLE_TABLE_NAME}' table")
        return _airtable_table_id
    except Exception as e:
        logger.warning(f"Airtable table create failed: {e}")
        return None


def log_trade_to_airtable(
    action: str,
    market_question: str,
    outcome: str,
    price: float,
    shares: float,
    amount_usd: float,
    confidence: float,
    reason: str,
    order_id: str = "",
    pnl_usd: Optional[float] = None,
) -> bool:
    """Log a trade entry/exit to Airtable. Returns True on success."""
    table_id = _get_airtable_table_id()
    if not table_id:
        return False

    import httpx
    headers = {
        "Authorization": f"Bearer {settings.airtable_pat}",
        "Content-Type": "application/json",
    }
    record = {
        "fields": {
            "Timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "Action": action,
            "Market": market_question,
            "Outcome": outcome,
            "Amount USD": round(amount_usd, 2),
            "Price": round(price, 4),
            "Shares": round(shares, 4),
            "Confidence": f"{confidence:.0%}" if confidence else "",
            "Thesis": reason[:1000] if reason else "",
            "Order ID": order_id or "",
        }
    }
    if pnl_usd is not None:
        record["fields"]["P&L USD"] = round(pnl_usd, 2)

    try:
        r = httpx.post(
            f"https://api.airtable.com/v0/{settings.airtable_base_id}/{table_id}",
            headers=headers,
            json={"records": [record]},
            timeout=10,
        )
        r.raise_for_status()
        logger.info(f"Airtable: logged {action} ${amount_usd:.2f} on {market_question[:40]}")
        return True
    except Exception as e:
        logger.warning(f"Airtable trade log failed: {e}")
        return False
