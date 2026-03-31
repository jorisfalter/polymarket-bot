"""
External integrations for the AI Trading Agent.
- Twitter/X: posts thinking summaries each cycle
- Google Sheets: logs all trades to a shared spreadsheet
"""
import json
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger

from .config import settings

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
        # Telegram limit is 4096 chars
        if len(text) > 4096:
            # Split into multiple messages
            chunks = [text[i:i+4096] for i in range(0, len(text), 4096)]
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


def format_thinking_telegram(decision: Dict) -> str:
    """Format agent's thinking for Telegram (HTML). Structured and concise."""
    lines = []

    now = datetime.utcnow().strftime("%H:%M UTC")
    lines.append(f"🧠 <b>Agent Cycle</b> — {now}")

    # Trades first (most important)
    trades = decision.get("trades", [])
    if trades:
        lines.append("")
        lines.append("💰 <b>TRADES:</b>")
        for t in trades:
            action = t.get("action", "?")
            question = t.get("market_question", "?")[:55]
            amount = t.get("amount_usd", 0)
            conf = t.get("confidence", 0)
            thesis = t.get("thesis", "")[:80]
            emoji = "🟢" if action == "BUY" else "🔴"
            lines.append(f"{emoji} {action} ${amount:.2f} — <i>{question}</i>")
            lines.append(f"   {conf:.0%} confidence: {thesis}")

    # Thinking — structured per strategy
    thinking = decision.get("thinking", "")
    if thinking:
        lines.append("")
        lines.append("📊 <b>ANALYSIS:</b>")
        # Keep it concise
        lines.append(thinking[:1200])

    # Thesis updates
    theses = decision.get("thesis_updates", [])
    if theses:
        lines.append("")
        lines.append("📋 <b>THESES:</b>")
        for t in theses:
            action = t.get("action", "?").upper()
            title = t.get("title", "") or t.get("id", "?")
            conviction = t.get("conviction", "")
            note = t.get("note", "")[:120]
            emoji = {"CREATE": "🆕", "UPDATE": "🔄", "CLOSE": "✅"}.get(action, "📋")
            conv_str = f" [{conviction}]" if conviction else ""
            lines.append(f"{emoji} <b>{title[:50]}</b>{conv_str}")
            if note:
                lines.append(f"   {note}")

    # Watchlist (brief)
    watchlist = decision.get("watchlist_notes", "")
    if watchlist:
        lines.append("")
        lines.append(f"👀 {watchlist[:250]}")

    # Risk (brief)
    risk = decision.get("risk_assessment", "")
    if risk:
        lines.append("")
        lines.append(f"⚠️ {risk[:200]}")

    return "\n".join(lines)


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
):
    """Append a trade row to the Trades tab."""
    ws = _get_or_create_tab("Trades", [
        "Timestamp", "Strategy", "Action", "Market",
        "Outcome", "Price", "Shares", "Amount USD",
        "Confidence", "Thesis/Reason", "Order ID", "P&L"
    ])
    if not ws:
        return

    try:
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
        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.debug(f"Trade logged to Sheets: {action} {market_question[:30]}")
    except Exception as e:
        logger.warning(f"Sheets trade log failed: {e}")


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
