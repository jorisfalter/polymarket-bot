"""
Trade Proxy — Runs on Fly.io (Dublin) to bypass Polymarket geoblock.

The main app on Hetzner (Germany, blocked) sends trade requests here.
This proxy executes them via the CLOB API from an allowed region.
Protected by a shared secret token.
"""
import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from loguru import logger

app = FastAPI(title="Polymarket Trade Proxy")

# Auth
PROXY_SECRET = os.environ.get("PROXY_SECRET", "")

# Lazy-init CLOB client
_client = None


def get_client():
    """Initialize the CLOB V2 client.

    Migration from py-clob-client v0.34.6 → py-clob-client-v2 on 2026-05-14
    because the V1 SDK was permanently rejected by Polymarket after their
    CLOB V2 launch on 2026-04-28 (EIP-712 domain version bumped 1→2).
    The V1 package was archived 2026-05-11. Every order from V1 returned
    `order_version_mismatch` for ~3 weeks.

    Param names + signature_type=1 (proxy wallet) flow are preserved in V2.
    """
    global _client
    if _client is not None:
        return _client

    from py_clob_client_v2 import ClobClient, ApiCreds

    creds = ApiCreds(
        api_key=os.environ["POLY_API_KEY"],
        api_secret=os.environ["POLY_API_SECRET"],
        api_passphrase=os.environ.get("POLY_PASSPHRASE", ""),
    )

    _client = ClobClient(
        host="https://clob.polymarket.com",
        chain_id=137,
        key=os.environ["POLY_PRIVATE_KEY"],
        creds=creds,
        signature_type=1,  # Proxy wallet (Magic.link)
        funder=os.environ.get("POLY_WALLET_ADDRESS"),
    )

    try:
        _client.set_api_creds(_client.derive_api_key())
    except Exception:
        pass

    logger.info("CLOB V2 client initialized")
    return _client


def verify_auth(authorization: str = Header(None)):
    if not PROXY_SECRET:
        raise HTTPException(500, "PROXY_SECRET not configured")
    if authorization != f"Bearer {PROXY_SECRET}":
        raise HTTPException(401, "Unauthorized")


def post_market_order_with_retry(client, order_args, options, max_attempts: int = 4):
    """Submit a market order via V2's create_and_post_market_order with retry.

    V2 collapses V1's two-step (create_market_order + post_order) into one
    call. Retry is kept for transient errors (network blips, momentary
    matcher state issues) but we expect order_version_mismatch to be gone
    now that we're on the correct EIP-712 domain version (V2).

    Returns (response, attempt_count) — caller checks response.get('success').
    """
    import time
    backoff = [0, 1.5, 3, 6]
    last_response = None
    for attempt in range(max_attempts):
        if attempt > 0:
            time.sleep(backoff[min(attempt, len(backoff) - 1)])
        try:
            response = client.create_and_post_market_order(
                order_args=order_args, options=options,
            )
            last_response = response
            if response and response.get("success"):
                logger.info(f"Market order succeeded on attempt {attempt + 1}")
                return response, attempt + 1
            err = (response or {}).get("error") or (response or {}).get("errorMsg") or ""
            # Retry only on a small allowlist of transient errors. Non-retryable
            # errors (e.g. insufficient balance, market closed) should bail fast.
            if not _is_retryable_error(str(err)):
                return response, attempt + 1
            logger.info(f"Attempt {attempt + 1} transient error: {str(err)[:120]}, retrying...")
        except Exception as e:
            err_str = str(e)
            if not _is_retryable_error(err_str):
                raise
            logger.info(f"Attempt {attempt + 1} raised: {err_str[:120]}, retrying...")
            last_response = {"success": False, "error": err_str}
    return last_response, max_attempts


def _is_retryable_error(err: str) -> bool:
    """Errors worth retrying — almost-empty list since V2 fixes the main
    chronic offender (order_version_mismatch). Keep generic transient
    network/timing signals only."""
    e = (err or "").lower()
    # Keep order_version_mismatch in here defensively — if it still happens
    # post-V2 it might mean another schema bump and we want a few retries.
    return any(x in e for x in (
        "order_version_mismatch",
        "matcher unavailable",
        "timeout",
        "temporarily",
    ))


# Cache neg-risk lookups per token (immutable so safe to cache forever)
_neg_risk_cache: dict = {}


def is_neg_risk(token_id: str) -> bool:
    """Polymarket has two Exchange contracts: regular and Neg-Risk.
    Multi-outcome events use Neg-Risk; binary YES/NO markets use regular.
    Authoritative source is the CLOB itself via client.get_neg_risk()."""
    if token_id in _neg_risk_cache:
        return _neg_risk_cache[token_id]
    try:
        client = get_client()
        result = bool(client.get_neg_risk(token_id))
    except Exception as e:
        logger.warning(f"CLOB neg_risk lookup failed for {token_id[:12]}: {e}")
        result = False
    _neg_risk_cache[token_id] = result
    logger.info(f"neg_risk[{token_id[:12]}] = {result}")
    return result


def check_orderbook_feasibility(token_id: str, expected_price: float) -> tuple:
    """Pre-flight orderbook checks before signing/posting.

    Refuses for two distinct reasons:
    1. **No orderbook** (404 from CLOB) — the market has expired or never had
       one. Polymarket's old short-window crypto markets fall here once their
       resolution window passes.
    2. **Cheapest ask is much worse than displayed price** — the asymmetric-bet
       thesis only works if you can actually buy at the displayed cheap price.
       If only expensive asks exist, the trade isn't the bet the agent thinks
       it is, and CLOB usually rejects with order_version_mismatch anyway.
    """
    try:
        client = get_client()
        book = client.get_order_book(token_id)
    except Exception as e:
        # Distinguish 404 ("no orderbook") from generic API failures.
        msg = str(e).lower()
        if "404" in msg or "no orderbook" in msg or "not found" in msg:
            return False, "no orderbook exists (market likely expired/closed)"
        logger.debug(f"orderbook feasibility check failed (proceeding): {e}")
        return True, "orderbook unreachable"

    # V2 returns a dict with 'asks'/'bids' lists. V1 returned an OrderBookSummary
    # object with .asks / .bids attributes. Handle both for safety.
    asks = book.get("asks") if isinstance(book, dict) else getattr(book, "asks", None)
    if not book or not asks:
        return False, "empty orderbook (no asks available)"

    def _ask_price(a):
        # V2: dict {'price': '0.99', 'size': '...'} ; V1: object with .price
        if isinstance(a, dict):
            return float(a.get("price", 0))
        return float(getattr(a, "price", 0))

    try:
        first_ask = _ask_price(asks[0])
        last_ask = _ask_price(asks[-1])
        best_ask = min(first_ask, last_ask)
    except Exception:
        return True, "could not parse asks"

    if expected_price <= 0:
        return True, "no expected price to compare"
    # For sub-10c tokens (asymmetric bets): refuse if ask > 5x displayed price.
    if expected_price < 0.10 and best_ask > expected_price * 5:
        return False, f"orderbook too thin: best ask {best_ask*100:.2f}¢ vs displayed {expected_price*100:.3f}¢ ({best_ask/expected_price:.0f}× worse)"
    # For mid-range tokens: refuse if ask is >50% above displayed.
    if expected_price >= 0.10 and best_ask > expected_price * 1.5:
        return False, f"orderbook too thin: best ask {best_ask*100:.1f}¢ vs displayed {expected_price*100:.1f}¢"
    return True, "ok"


def check_market_tradeable(token_id: str, amount_usd: float = 0, condition_id: str = "") -> tuple:
    """Pre-flight check: is the market actually tradeable AND does our order
    meet its minimum size?

    Looks up market metadata via Gamma `?condition_ids=` (the only query-param
    that actually filters — `?clob_token_ids=` is silently ignored and returns
    the Rihanna×GTA-VI default for every call, which was poisoning this
    function from day 1).

    Falls back to CLOB `/markets/{condition_id}` if Gamma fails.

    Without condition_id we can't filter (Gamma `clob_token_ids=` is broken),
    so we skip the pre-flight gracefully — CLOB will still reject orders on
    closed/UMA/archived markets via the actual order submission.
    """
    import httpx
    if not condition_id:
        return True, "no condition_id, skipping gamma pre-flight"
    try:
        r = httpx.get(
            "https://gamma-api.polymarket.com/markets",
            params={"condition_ids": condition_id, "limit": 1},
            timeout=10.0,
        )
        r.raise_for_status()
        markets = r.json() or []
        if not markets:
            return True, "no metadata, proceeding"
        m = markets[0]
        if m.get("closed"):
            return False, "market closed"
        if m.get("archived"):
            return False, "market archived"
        if not m.get("active", True):
            return False, "market inactive"
        # acceptingOrders=False is the most authoritative tradeability signal.
        if m.get("acceptingOrders") is False:
            return False, "market not accepting orders"
        # UMA states that block trading: 'proposed' (in liveness window),
        # 'disputed' / 'challenged' (under dispute), 'resolved' (final, no
        # more trading). 'None' / 'pending' / 'open' / 'unproposed' are fine.
        uma_status = (m.get("umaResolutionStatus") or "").lower()
        if uma_status in ("disputed", "challenged", "proposed", "resolved"):
            return False, f"UMA {uma_status} (no orders accepted)"
        # Resolution-window check. 2026-05-08/09: 25 of 46 order_version_mismatch
        # failures were on markets resolving same-day ("Bitcoin > $78k on May 8",
        # "Iran peace deal by May 8"). Polymarket's CLOB starts rejecting orders
        # ~1h before resolution while Gamma's `acceptingOrders` flag hasn't
        # flipped yet — version_mismatch becomes a generic "too late" signal.
        # Refuse early so we don't burn 4 retries on doomed orders.
        end_date = m.get("endDate") or m.get("endDateIso")
        if end_date:
            try:
                from datetime import datetime as _dt
                end_dt = _dt.fromisoformat(str(end_date).replace("Z", "+00:00"))
                now = _dt.now(end_dt.tzinfo) if end_dt.tzinfo else _dt.utcnow()
                hours_left = (end_dt - now).total_seconds() / 3600
                if hours_left < 1:
                    return False, f"market resolves in {hours_left:.1f}h (too close — CLOB likely rejecting already)"
            except Exception:
                pass  # bad date format, proceed
        # Order minimum (in USD-equivalent). Multi-outcome neg_risk markets
        # typically require $5+; standard binaries accept $1.
        order_min = float(m.get("orderMinSize") or 0)
        if amount_usd and order_min and amount_usd < order_min:
            return False, f"order below market minimum (need ≥${order_min:.2f}, got ${amount_usd:.2f})"
        return True, "ok"
    except Exception as e:
        logger.debug(f"tradeable check failed (proceeding anyway): {e}")
        return True, "metadata unreachable"


def _build_failure_diagnostics(client, token_id: str, neg_risk: bool, midpoint: float, condition_id: str = "") -> dict:
    """Build a rich snapshot of WHY a trade likely failed. Only called on the
    failure path so it doesn't slow successful trades.

    Captures: orderbook depth (top 3 asks/bids), gamma metadata flags,
    multi-outcome status, time-to-resolution. Persisted into trade_failures
    so we can pattern-match later (e.g. 'all version_mismatch happens on
    neg_risk markets with <5 asks').
    """
    diag = {"neg_risk": neg_risk, "midpoint": midpoint, "token_id_short": token_id[:20]}
    # Orderbook depth — V2 returns dict {asks: [{price,size}], bids: [...]}
    def _px(x): return float(x.get("price", 0)) if isinstance(x, dict) else float(getattr(x, "price", 0))
    def _sz(x): return float(x.get("size", 0)) if isinstance(x, dict) else float(getattr(x, "size", 0))
    try:
        book = client.get_order_book(token_id)
        if book:
            asks = list((book.get("asks") if isinstance(book, dict) else getattr(book, "asks", None)) or [])
            bids = list((book.get("bids") if isinstance(book, dict) else getattr(book, "bids", None)) or [])
            asks_sorted = sorted(asks, key=_px)[:3]
            bids_sorted = sorted(bids, key=lambda x: -_px(x))[:3]
            diag["best_ask"] = _px(asks_sorted[0]) if asks_sorted else None
            diag["best_bid"] = _px(bids_sorted[0]) if bids_sorted else None
            diag["ask_levels"] = [{"price": _px(a), "size": _sz(a)} for a in asks_sorted]
            diag["bid_levels"] = [{"price": _px(b), "size": _sz(b)} for b in bids_sorted]
            diag["ask_count_total"] = len(asks)
            diag["bid_count_total"] = len(bids)
    except Exception as e:
        diag["orderbook_error"] = str(e)[:120]

    # Gamma metadata snapshot. ?clob_token_ids= is silently broken so we use
    # ?condition_ids= which actually filters. Caller must pass condition_id.
    if not condition_id:
        diag["gamma_skipped"] = "no condition_id passed"
        return diag
    try:
        import httpx
        r = httpx.get(
            "https://gamma-api.polymarket.com/markets",
            params={"condition_ids": condition_id, "limit": 1},
            timeout=6.0,
        )
        if r.status_code == 200:
            markets = r.json() or []
            if markets:
                m = markets[0]
                # Multi-outcome detection: if the market belongs to an event
                # with several markets, version_mismatch is more likely.
                event_markets = m.get("events", [])
                diag["gamma"] = {
                    "question": m.get("question", "")[:120],
                    "accepting_orders": m.get("acceptingOrders"),
                    "active": m.get("active"),
                    "closed": m.get("closed"),
                    "archived": m.get("archived"),
                    "end_date": m.get("endDate"),
                    "uma_status": m.get("umaResolutionStatus"),
                    "order_min_size": m.get("orderMinSize"),
                    "volume": m.get("volume"),
                    "liquidity": m.get("liquidity"),
                    "n_markets_in_event": len(event_markets) if isinstance(event_markets, list) else None,
                    "outcomes_raw": m.get("outcomes"),
                }
    except Exception as e:
        diag["gamma_error"] = str(e)[:120]

    return diag


class BuyRequest(BaseModel):
    token_id: str
    amount_usd: float
    max_price: Optional[float] = None
    # conditionId (0x-prefixed hex) — required for Gamma pre-flight checks
    # since `?clob_token_ids=` is silently broken. Backward-compat: None means
    # skip the Gamma metadata check.
    condition_id: Optional[str] = None


class SellRequest(BaseModel):
    token_id: str
    shares: float
    min_price: Optional[float] = None


# Limit-order requests (GTC) used by market-maker mode. Maker posts into the
# book, so size is in SHARES not USD — caller computes shares = stake / price.
class LimitOrderRequest(BaseModel):
    token_id: str
    price: float          # 0.0-1.0; will be quantized to market tick_size
    size: float           # shares (NOT usd). For a BUY: usd_stake / price.
    side: str             # "BUY" or "SELL"
    condition_id: Optional[str] = None


@app.get("/health")
async def health():
    return {"status": "ok", "region": os.environ.get("FLY_REGION", "unknown")}


@app.get("/version")
async def version():
    """Return installed CLOB SDK version. Useful when Polymarket bumps
    their order schema (as happened 2026-04-28 with V1→V2)."""
    try:
        import importlib.metadata as md
        clob_v = md.version("py-clob-client-v2")
        return {"py_clob_client_v2": clob_v, "sdk_version": "v2"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/buy")
async def buy(req: BuyRequest, authorization: str = Header(None)):
    verify_auth(authorization)
    client = get_client()

    try:
        from py_clob_client_v2 import MarketOrderArgs, OrderType, PartialCreateOrderOptions, Side

        # Pre-flight: skip clearly untradeable markets so callers see a
        # useful error rather than Polymarket's confusing version_mismatch.
        ok, reason = check_market_tradeable(
            req.token_id, amount_usd=req.amount_usd, condition_id=req.condition_id or ""
        )
        if not ok:
            logger.warning(f"Buy refused: {reason} ({req.token_id[:12]})")
            return {"success": False, "error": f"market not tradeable: {reason}"}

        try:
            # V2 returns {'mid': '0.095'} dict; V1 returned a float string.
            _mp = client.get_midpoint(req.token_id)
            midpoint = float(_mp.get("mid", 0)) if isinstance(_mp, dict) else float(_mp)
        except Exception:
            midpoint = 0

        # Pre-flight orderbook check: if the displayed price is far from the
        # cheapest available ask, buying makes no sense (asymmetric bet thesis
        # collapses, and CLOB usually rejects with order_version_mismatch).
        ok, reason = check_orderbook_feasibility(req.token_id, midpoint)
        if not ok:
            logger.warning(f"Buy refused: {reason} ({req.token_id[:12]})")
            return {"success": False, "error": f"orderbook unfavorable: {reason}"}

        neg_risk = is_neg_risk(req.token_id)
        # V2 PartialCreateOrderOptions takes tick_size; neg_risk is still accepted
        # but tick_size is now expected for accurate price quantization.
        # Use 0.01 default — most binaries; 0.001 for some neg-risk multi-outcome.
        tick_size = "0.001" if neg_risk else "0.01"
        options = PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk)

        # V2: order_type moves INTO MarketOrderArgs.
        order_args = MarketOrderArgs(
            token_id=req.token_id,
            amount=req.amount_usd,
            side=Side.BUY,
            order_type=OrderType.FAK,
        )
        response, attempts = post_market_order_with_retry(client, order_args, options)
        logger.info(f"Buy response after {attempts} attempt(s): success={response.get('success') if response else 'no-response'}")

        if response and response.get("success"):
            order_id = response.get("orderID") or response.get("order_id")
            shares = req.amount_usd / midpoint if midpoint > 0 else 0
            return {
                "success": True,
                "order_id": order_id,
                "price": midpoint,
                "shares": shares,
                "neg_risk": neg_risk,
                "attempts": attempts,
            }
        else:
            # Surface the FULL response so we can diagnose ambiguous errors
            error = (response or {}).get("errorMsg") or (response or {}).get("error") or "Unknown"
            # Capture rich diagnostics for failure analysis. Only on failure
            # to keep success path fast. order_version_mismatch is our prime
            # suspect for neg-risk multi-outcome markets — these fields will
            # let us correlate failures with market characteristics.
            diag = _build_failure_diagnostics(
                client, req.token_id, neg_risk, midpoint, condition_id=req.condition_id or ""
            )
            return {
                "success": False,
                "error": f"{error} (after {attempts} attempts)",
                "price": midpoint,
                "neg_risk": neg_risk,
                "full_response": response,
                "attempts": attempts,
                "diagnostics": diag,
            }

    except Exception as e:
        logger.error(f"Buy error: {e}")
        return {"success": False, "error": str(e), "exception_type": type(e).__name__}


@app.post("/sell")
async def sell(req: SellRequest, authorization: str = Header(None)):
    verify_auth(authorization)
    client = get_client()

    try:
        from py_clob_client_v2 import MarketOrderArgs, OrderType, PartialCreateOrderOptions, Side

        ok, reason = check_market_tradeable(req.token_id)
        if not ok:
            logger.warning(f"Sell refused: {reason} ({req.token_id[:12]})")
            return {"success": False, "error": f"market not tradeable: {reason}"}

        try:
            # V2 returns {'mid': '0.095'} dict; V1 returned a float string.
            _mp = client.get_midpoint(req.token_id)
            midpoint = float(_mp.get("mid", 0)) if isinstance(_mp, dict) else float(_mp)
        except Exception:
            midpoint = 0

        amount_usd = req.shares * midpoint if midpoint > 0 else req.shares

        neg_risk = is_neg_risk(req.token_id)
        tick_size = "0.001" if neg_risk else "0.01"
        options = PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk)

        order_args = MarketOrderArgs(
            token_id=req.token_id,
            amount=amount_usd,
            side=Side.SELL,
            order_type=OrderType.FAK,
        )
        response, attempts = post_market_order_with_retry(client, order_args, options)

        if response and response.get("success"):
            order_id = response.get("orderID") or response.get("order_id")
            return {
                "success": True,
                "order_id": order_id,
                "price": midpoint,
                "shares": req.shares,
                "neg_risk": neg_risk,
                "attempts": attempts,
            }
        else:
            error = (response or {}).get("errorMsg") or (response or {}).get("error") or "Unknown"
            return {"success": False, "error": f"{error} (after {attempts} attempts)", "price": midpoint, "neg_risk": neg_risk, "attempts": attempts}

    except Exception as e:
        logger.error(f"Sell error: {e}")
        return {"success": False, "error": str(e)}


@app.post("/limit")
async def limit(req: LimitOrderRequest, authorization: str = Header(None)):
    """Post a GTC limit order. Used by market-maker mode (Pad 2).

    Unlike /buy and /sell (which use FAK to fill immediately), GTC sits in
    the orderbook until filled or cancelled — this is how we provide
    liquidity and earn the spread.
    """
    verify_auth(authorization)
    client = get_client()

    side_upper = (req.side or "").upper()
    if side_upper not in ("BUY", "SELL"):
        return {"success": False, "error": f"invalid side {req.side!r}, expected BUY or SELL"}

    try:
        from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions, Side

        ok, reason = check_market_tradeable(
            req.token_id,
            amount_usd=req.price * req.size,
            condition_id=req.condition_id or "",
        )
        if not ok:
            logger.warning(f"Limit refused: {reason} ({req.token_id[:12]})")
            return {"success": False, "error": f"market not tradeable: {reason}"}

        neg_risk = is_neg_risk(req.token_id)
        # Tick size: 0.01 standard; switches to 0.001 inside [0.04, 0.96] only
        # AFTER a market trades there (per paper footnote 12). For maker posts
        # we'd rather quantize too coarse than have CLOB reject. Conservative:
        # 0.01 unless neg_risk (which often allows finer).
        tick_size = "0.001" if neg_risk else "0.01"
        options = PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk)

        order_args = OrderArgs(
            token_id=req.token_id,
            price=req.price,
            size=req.size,
            side=Side.BUY if side_upper == "BUY" else Side.SELL,
            order_type=OrderType.GTC,
        )
        response = client.create_and_post_order(order_args=order_args, options=options)

        if response and response.get("success"):
            return {
                "success": True,
                "order_id": response.get("orderID") or response.get("order_id"),
                "price": req.price,
                "size": req.size,
                "side": side_upper,
                "neg_risk": neg_risk,
            }
        error = (response or {}).get("errorMsg") or (response or {}).get("error") or "Unknown"
        return {
            "success": False,
            "error": error,
            "full_response": response,
            "neg_risk": neg_risk,
        }
    except Exception as e:
        logger.error(f"Limit error: {e}")
        return {"success": False, "error": str(e), "exception_type": type(e).__name__}


@app.get("/orders")
async def list_orders(authorization: str = Header(None), token_id: Optional[str] = None):
    """List open orders on our wallet. Optional ?token_id=... filter."""
    verify_auth(authorization)
    client = get_client()
    try:
        from py_clob_client_v2 import OpenOrderParams
        params = OpenOrderParams(asset_id=token_id) if token_id else None
        orders = client.get_open_orders(params=params) if params else client.get_open_orders()
        # Normalize to a thin shape the maker loop can consume.
        out = []
        for o in (orders or []):
            if not isinstance(o, dict):
                o = getattr(o, "__dict__", {}) or {}
            out.append({
                "order_id": o.get("id") or o.get("orderID") or o.get("order_id"),
                "token_id": o.get("asset_id") or o.get("token_id"),
                "side": o.get("side"),
                "price": float(o.get("price", 0) or 0),
                "size_original": float(o.get("original_size", o.get("size", 0)) or 0),
                "size_remaining": float(o.get("size_matched", 0) or 0),  # caller computes remaining
                "status": o.get("status"),
                "created_at": o.get("created_at"),
            })
        return {"success": True, "count": len(out), "orders": out}
    except Exception as e:
        logger.error(f"list_orders error: {e}")
        return {"success": False, "error": str(e), "orders": []}


@app.delete("/orders/{order_id}")
async def cancel_order(order_id: str, authorization: str = Header(None)):
    """Cancel a single open order by ID."""
    verify_auth(authorization)
    client = get_client()
    try:
        from py_clob_client_v2 import OrderPayload
        response = client.cancel_order(OrderPayload(orderID=order_id))
        return {"success": True, "order_id": order_id, "response": response}
    except Exception as e:
        logger.error(f"cancel error for {order_id}: {e}")
        return {"success": False, "order_id": order_id, "error": str(e)}


@app.get("/reddit/{subreddit}/{sort}")
async def reddit_proxy(subreddit: str, sort: str, limit: int = 50, authorization: str = Header(None)):
    """Reddit blocks Hetzner / data-center IPs. Proxy through Tokyo."""
    verify_auth(authorization)
    if sort not in ("hot", "new", "top", "rising"):
        raise HTTPException(400, "bad sort")
    import httpx
    headers = {"User-Agent": "polymarket-bot/1.0 (proxy; research@jorisfalter.com)"}
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            r = await client.get(url, params={"limit": limit})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"error": str(e), "data": {"children": []}}


@app.get("/balance")
async def balance(authorization: str = Header(None)):
    verify_auth(authorization)
    client = get_client()

    try:
        from py_clob_client_v2 import BalanceAllowanceParams, AssetType
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=1)
        result = client.get_balance_allowance(params)
        raw = result.get("balance", 0) if isinstance(result, dict) else 0
        return {"balance": float(raw) / 1e6}
    except Exception as e:
        return {"balance": 0, "error": str(e)}
