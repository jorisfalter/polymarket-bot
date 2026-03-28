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
        # Skip meta-sentences about portfolio state, find market analysis
        good_sentences = [s for s in sentences if not any(skip in s.lower() for skip in ["my portfolio", "my rules", "my exposure", "i have", "i need to", "i must"])]
        if not good_sentences:
            good_sentences = sentences
        if good_sentences:
            # Take up to 4 substantive sentences — threading handles overflow
            analysis = ". ".join(good_sentences[:4]) + "."
            lines.append(analysis[:500])

    if not lines:
        lines.append("Scanning markets. No actionable signals this cycle. Patience.")

    tweet = "\n".join(lines)

    # Add timestamp to avoid duplicate content errors + hashtags
    now = datetime.utcnow().strftime("%H:%M UTC")
    tweet += f"\n\n[{now}] #Polymarket #AITrading"

    # No need to truncate — post_tweet handles threading
    return tweet


# ==================== GOOGLE SHEETS ====================

_sheets_client = None
_worksheet = None


def _get_worksheet():
    """Lazy-init Google Sheets worksheet."""
    global _sheets_client, _worksheet
    if _worksheet is not None:
        return _worksheet

    if not settings.google_sheets_id:
        return None

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        # Try service account file, then OAuth user creds, then default
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

        _sheets_client = gspread.authorize(creds)
        spreadsheet = _sheets_client.open_by_key(settings.google_sheets_id)

        # Get or create "Trades" sheet
        try:
            _worksheet = spreadsheet.worksheet("Trades")
        except gspread.WorksheetNotFound:
            _worksheet = spreadsheet.add_worksheet("Trades", rows=1000, cols=12)
            # Add headers
            _worksheet.update("A1:L1", [[
                "Timestamp", "Strategy", "Action", "Market",
                "Outcome", "Price", "Shares", "Amount USD",
                "Confidence", "Thesis/Reason", "Order ID", "P&L"
            ]])
            _worksheet.format("A1:L1", {"textFormat": {"bold": True}})

        logger.info("Google Sheets connected")
        return _worksheet
    except Exception as e:
        logger.warning(f"Google Sheets init failed: {e}")
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
    """Append a trade row to Google Sheets."""
    ws = _get_worksheet()
    if not ws:
        return

    try:
        row = [
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            strategy,
            action,
            market_question[:80],
            outcome,
            f"{price:.4f}",
            f"{shares:.4f}",
            f"{amount_usd:.2f}",
            f"{confidence:.0%}" if confidence else "",
            reason[:100],
            order_id or "",
            f"{pnl:.2f}" if pnl else "",
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.debug(f"Trade logged to Sheets: {action} {market_question[:30]}")
    except Exception as e:
        logger.warning(f"Sheets log failed: {e}")


def log_thinking_to_sheets(decision: Dict):
    """Log thinking summary to a 'Thinking' tab."""
    if not settings.google_sheets_id:
        return

    try:
        ws_thinking = None
        spreadsheet = _sheets_client.open_by_key(settings.google_sheets_id) if _sheets_client else None
        if not spreadsheet:
            return

        import gspread
        try:
            ws_thinking = spreadsheet.worksheet("Thinking")
        except gspread.WorksheetNotFound:
            ws_thinking = spreadsheet.add_worksheet("Thinking", rows=1000, cols=6)
            ws_thinking.update("A1:F1", [[
                "Timestamp", "Thinking", "Trades", "Thesis Updates",
                "Watchlist", "Risk Assessment"
            ]])
            ws_thinking.format("A1:F1", {"textFormat": {"bold": True}})

        trades_summary = "; ".join(
            f"{t.get('action')} {t.get('market_question', '?')[:30]}"
            for t in decision.get("trades", [])
        ) or "None"

        thesis_summary = "; ".join(
            f"{t.get('action')} [{t.get('id')}]"
            for t in decision.get("thesis_updates", [])
        ) or "None"

        row = [
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            decision.get("thinking", "")[:500],
            trades_summary,
            thesis_summary,
            decision.get("watchlist_notes", "")[:200],
            decision.get("risk_assessment", "")[:200],
        ]
        ws_thinking.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        logger.warning(f"Sheets thinking log failed: {e}")
