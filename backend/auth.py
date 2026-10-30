"""
Dashboard authentication — magic-link login via Telegram.

Flow:
1. User opens any page → no valid session cookie → redirected to /login
2. /login has one button → POST /api/auth/request-link
3. A short-lived random token is generated and a login URL containing it
   is sent to the user's Telegram chat (the chat_id is fixed in .env, so
   only the person controlling that Telegram account ever receives it).
4. User taps the link → GET /api/auth/verify?token=... → token consumed,
   a signed 30-day session cookie is set → redirect to dashboard.

Security model:
- "Only I can log in" holds because the magic link is delivered ONLY to
  the configured Telegram chat. There is no password to leak.
- The session cookie is HMAC-signed with AUTH_SECRET; it cannot be forged
  without the secret. It carries only an expiry timestamp.
- If AUTH_SECRET is unset the app fails CLOSED: every route except
  /healthz returns 503 (security audit A-10, 2026-10-30).
- POST /api/auth/request-link is throttled (per IP + global, in-memory —
  the app runs a single uvicorn worker) so it can't spam Telegram.

Pending tokens live in-memory: a container restart between request-link
and verify invalidates an unused token. Acceptable — the window is 10 min
and the user just requests a fresh link.
"""
import hashlib
import hmac
import secrets
import time
from typing import Dict, List, Optional

from loguru import logger

from .config import settings

COOKIE_NAME = "pm_session"
COOKIE_MAX_AGE = 30 * 24 * 3600        # 30 days
MAGIC_TOKEN_TTL = 10 * 60              # 10 minutes

# token -> expiry epoch. In-memory by design (see module docstring).
_pending_tokens: Dict[str, float] = {}


def auth_enabled() -> bool:
    """True when a secret is configured. No secret = app serves 503 (fail-closed)."""
    return bool(settings.auth_secret)


# ──────────────────────────────────────────────────────────────────────
# request-link throttling (in-memory; single uvicorn worker)
# ──────────────────────────────────────────────────────────────────────

REQUEST_LINK_PER_IP_MAX = 3
REQUEST_LINK_PER_IP_WINDOW = 15 * 60       # 15 minutes
REQUEST_LINK_GLOBAL_MAX = 10
REQUEST_LINK_GLOBAL_WINDOW = 60 * 60       # 1 hour

_request_link_by_ip: Dict[str, List[float]] = {}
_request_link_global: List[float] = []


def check_request_link_rate(client_ip: str, now: Optional[float] = None) -> Optional[int]:
    """Record a request-link attempt. Returns None if allowed, otherwise the
    number of seconds until the caller may retry. Every attempt that is
    allowed counts toward both limits; rejected attempts don't extend them."""
    now = time.time() if now is None else now

    _request_link_global[:] = [t for t in _request_link_global
                               if now - t < REQUEST_LINK_GLOBAL_WINDOW]
    for ip in list(_request_link_by_ip):
        kept = [t for t in _request_link_by_ip[ip] if now - t < REQUEST_LINK_PER_IP_WINDOW]
        if kept:
            _request_link_by_ip[ip] = kept
        else:
            del _request_link_by_ip[ip]

    ip_hits = _request_link_by_ip.get(client_ip, [])
    if len(ip_hits) >= REQUEST_LINK_PER_IP_MAX:
        return max(1, int(ip_hits[0] + REQUEST_LINK_PER_IP_WINDOW - now) + 1)
    if len(_request_link_global) >= REQUEST_LINK_GLOBAL_MAX:
        return max(1, int(_request_link_global[0] + REQUEST_LINK_GLOBAL_WINDOW - now) + 1)

    _request_link_by_ip.setdefault(client_ip, []).append(now)
    _request_link_global.append(now)
    return None


# ──────────────────────────────────────────────────────────────────────
# Magic-link tokens
# ──────────────────────────────────────────────────────────────────────

def generate_magic_token() -> str:
    """Create a single-use login token valid for MAGIC_TOKEN_TTL seconds."""
    _prune_expired()
    token = secrets.token_urlsafe(32)
    _pending_tokens[token] = time.time() + MAGIC_TOKEN_TTL
    return token


def consume_magic_token(token: str) -> bool:
    """Validate + burn a magic token. True only if it existed and is fresh."""
    _prune_expired()
    expiry = _pending_tokens.pop(token, None)
    if expiry is None:
        return False
    return time.time() < expiry


def _prune_expired() -> None:
    now = time.time()
    for t in [t for t, exp in _pending_tokens.items() if exp < now]:
        _pending_tokens.pop(t, None)


# ──────────────────────────────────────────────────────────────────────
# Session cookie (HMAC-signed)
# ──────────────────────────────────────────────────────────────────────

def make_session_cookie() -> str:
    """Return a signed cookie value: '<expiry>.<hmac>'."""
    expiry = int(time.time()) + COOKIE_MAX_AGE
    payload = str(expiry)
    sig = _sign(payload)
    return f"{payload}.{sig}"


def verify_session_cookie(cookie: str) -> bool:
    """True if the cookie is well-formed, correctly signed, and not expired."""
    if not cookie or "." not in cookie:
        return False
    try:
        payload, sig = cookie.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return False
        return int(payload) > time.time()
    except Exception:
        return False


def _sign(payload: str) -> str:
    secret = (settings.auth_secret or "").encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


# ──────────────────────────────────────────────────────────────────────
# Magic-link delivery
# ──────────────────────────────────────────────────────────────────────

async def send_magic_link() -> bool:
    """Generate a token and send the login URL to Telegram. Returns success."""
    token = generate_magic_token()
    url = f"{settings.public_url.rstrip('/')}/api/auth/verify?token={token}"
    msg = (
        "🔐 <b>Dashboard login</b>\n\n"
        "Tik op de link om in te loggen (10 min geldig):\n"
        f"{url}\n\n"
        "Niet zelf aangevraagd? Negeer dit bericht."
    )
    try:
        from .integrations import send_telegram
        # disable_web_page_preview: stop Telegram's crawler from prefetching
        # the link — that prefetch would consume the single-use token.
        ok = await send_telegram(msg, disable_web_page_preview=True)
        if ok:
            logger.info("Magic-link sent to Telegram")
        else:
            logger.warning("Magic-link Telegram send returned falsy")
        return bool(ok)
    except Exception as e:
        logger.error(f"Magic-link send failed: {e}")
        return False
