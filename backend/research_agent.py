"""
Research Agent — daily hedge-fund-analyst loop.

Once a day (default 06:00 UTC) this:
  1. Aggregates intel from every source we have access to:
       - Gmail newsletters (intel_feeds.fetch_gmail_newsletters)
       - Public RSS feeds (intel_feeds.fetch_rss_intel)
       - Reddit DD across 6-8 subs (reddit_data.fetch_multi_subreddit_intel)
       - YouTube transcripts (youtube_intel.fetch_youtube_intel)
  2. Filters every item via a cheap LLM call: "is this an actionable
     trading idea?". Discards 90%+ as noise.
  3. Dedupes ideas that point at the same ticker/event using a second
     LLM grouping pass (cheaper than embeddings for v1, fewer deps).
  4. Re-ranks survivors on novelty × conviction × actionability.
  5. Persists to data/research_ideas.jsonl (append-only with provenance).
  6. Sends a Telegram morning digest with the top 5.

Designed to cost ~$0.50/day at current DeepSeek pricing via OpenRouter.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

from .config import settings

# Separate file from the manual /api/research/ideas inbox (different schema).
# Agent-generated ideas have provenance + LLM analysis fields; manual ones
# are free-form text from Matt Levine excerpts the user pastes in.
IDEAS_PATH = Path(__file__).parent.parent / "data" / "research_agent_ideas.jsonl"


# ──────────────────────────────────────────────────────────────────────
# LLM client (lazy)
# ──────────────────────────────────────────────────────────────────────

_llm = None


def _get_llm():
    """Return an OpenAI-compatible client targeting OpenRouter (or Anthropic
    as fallback). Mirrors ai_agent.py setup so we share the same model + key."""
    global _llm
    if _llm is not None:
        return _llm
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai SDK not available; research_agent disabled")
        return None
    key = settings.openrouter_api_key or settings.anthropic_api_key
    if not key:
        logger.warning("No LLM key configured; research_agent disabled")
        return None
    base_url = (
        "https://openrouter.ai/api/v1"
        if settings.openrouter_api_key
        else "https://api.anthropic.com/v1"
    )
    _llm = OpenAI(api_key=key, base_url=base_url)
    return _llm


def _call_llm(system: str, user: str, max_tokens: int = 600, temperature: float = 0.2) -> str:
    """Synchronous LLM call. Wrap with asyncio.to_thread when called from async."""
    client = _get_llm()
    if not client:
        return ""
    try:
        resp = client.chat.completions.create(
            model=settings.agent_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
        return ""


# ──────────────────────────────────────────────────────────────────────
# Stage 1: ingest
# ──────────────────────────────────────────────────────────────────────

async def _ingest_all() -> List[Dict]:
    """Pull every available source in parallel. Each item is normalized to
    {source, title, body, url, ts}. Missing fields are filled with ''."""
    from . import intel_feeds, reddit_data, youtube_intel

    async def _gmail() -> List[Dict]:
        items = await intel_feeds.fetch_gmail_newsletters()
        return [{
            "source": it.get("source") or "Gmail",
            "title": it.get("subject", "")[:300],
            "body": it.get("body", "")[:8000],
            "url": "",
            "ts": it.get("date", ""),
        } for it in items]

    async def _rss() -> List[Dict]:
        items = await intel_feeds.fetch_rss_intel()
        return [{
            "source": it.get("source") or "RSS",
            "title": it.get("title", "")[:300],
            "body": it.get("summary", "")[:2000],
            "url": "",
            "ts": "",
        } for it in items]

    async def _reddit() -> List[Dict]:
        return await reddit_data.fetch_multi_subreddit_intel(per_sub=12, min_score=50)

    async def _youtube() -> List[Dict]:
        return await youtube_intel.fetch_youtube_intel(since_hours=48, max_videos_per_channel=2)

    async def _congress() -> List[Dict]:
        """Senate disclosures as Scout items. Purchases only — sales are
        mostly portfolio cleanup, weaker signal."""
        from . import stocks_data
        try:
            trades = await stocks_data.fetch_politician_trades(days_back=14)
        except Exception as e:
            logger.warning(f"congress ingest failed: {e}")
            return []
        items: List[Dict] = []
        for t in trades:
            if (t.get("type") or "") != "purchase":
                continue
            tk = (t.get("ticker") or "").strip()
            if not tk or tk in ("?", "N/A"):
                continue
            rep = t.get("representative") or "?"
            amt = t.get("amount") or ""
            date = t.get("transaction_date") or ""
            items.append({
                "source": f"Congress: {rep}",
                "title": f"{rep} kocht {tk} ({amt})",
                "body": (f"{rep} bought {tk} on {date}. Amount range: {amt}. "
                          f"Asset: {(t.get('asset') or '')[:200]}"),
                "url": "",
                "ts": date,
            })
        return items

    bucket: List[Dict] = []
    results = await asyncio.gather(
        _gmail(), _rss(), _reddit(), _youtube(), _congress(),
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"ingest source errored: {r}")
            continue
        bucket.extend(r)
    logger.info(f"research_agent ingested {len(bucket)} items across all sources")
    return bucket


# ──────────────────────────────────────────────────────────────────────
# Stage 2: filter
# ──────────────────────────────────────────────────────────────────────

FILTER_SYSTEM = (
    "Je bent een hedge-fund analyst die door content scrolt op zoek naar "
    "actionable trading ideeën. Voor élk item dat je krijgt, beslis je of "
    "het een concreet idee bevat. Wees streng: 90%+ van de items moet je "
    "afwijzen. Wat is GEEN idea: macro-commentaar zonder ticker, hot takes, "
    "lijstjes van algemene trends. Wat WEL: specifieke ticker met thesis, "
    "een event-driven setup, een squeeze candidate, een filing/insider buy, "
    "een prediction-market arbitrage, een crypto governance-vote, etc.\n\n"
    "Geef ALTIJD valid JSON terug, niets anders. Schema:\n"
    "{\"is_idea\": bool, \"market_type\": \"stocks\"|\"crypto\"|\"polymarket\"|\"macro\"|null, "
    "\"ticker_or_event\": string|null, \"thesis\": string|null, "
    "\"conviction\": 1-5 int|null, \"why_now\": string|null, "
    "\"resolves_when\": string|null}\n"
    "Conviction 5 = sterk, concreet, eigentijds; 1 = vaag of stale."
)


async def _filter_one(item: Dict) -> Optional[Dict]:
    """Returns the parsed idea dict (with source provenance) or None if not
    a tradable idea."""
    text = f"[{item.get('source', '?')}] {item.get('title', '')}\n\n{item.get('body', '')[:3500]}"
    raw = await asyncio.to_thread(_call_llm, FILTER_SYSTEM, text, 350, 0.1)
    if not raw:
        return None
    # Tolerant JSON parsing — LLMs sometimes wrap in ```json fences
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not data.get("is_idea"):
        return None
    if (data.get("conviction") or 0) < 2:
        return None
    return {
        "source": item.get("source", "?"),
        "source_title": item.get("title", "")[:200],
        "source_url": item.get("url", ""),
        "source_ts": item.get("ts", ""),
        "market_type": data.get("market_type"),
        "ticker_or_event": data.get("ticker_or_event"),
        "thesis": data.get("thesis"),
        "conviction": data.get("conviction"),
        "why_now": data.get("why_now"),
        "resolves_when": data.get("resolves_when"),
    }


async def _filter_all(items: List[Dict], concurrency: int = 6) -> List[Dict]:
    sem = asyncio.Semaphore(concurrency)
    async def _bound(it: Dict):
        async with sem:
            return await _filter_one(it)
    results = await asyncio.gather(*(_bound(it) for it in items), return_exceptions=True)
    keepers = [r for r in results if r and not isinstance(r, Exception)]
    logger.info(f"research_agent filtered {len(items)} → {len(keepers)} ideas")
    return keepers


# ──────────────────────────────────────────────────────────────────────
# Stage 3: dedupe + rerank
# ──────────────────────────────────────────────────────────────────────

DEDUPE_SYSTEM = (
    "Je krijgt een JSON-lijst van trading ideeën. Sommige gaan over hetzelfde "
    "ticker of event vanuit meerdere bronnen. Cluster ze, kies per cluster het "
    "sterkst-onderbouwde idee (hoogste conviction × beste why-now), en gooi de "
    "rest weg. Geef terug: een JSON-lijst met dezelfde shape, alleen de gekozen "
    "representanten. NIETS anders dan valid JSON."
)


RANK_SYSTEM = (
    "Je krijgt een JSON-lijst trading ideeën. Rank ze van best-naar-slechtst op "
    "drie criteria gewogen: NOVELTY (vooral als 't NIET in mainstream news zat), "
    "ACTIONABILITY (kan ik vandaag een trade hierop doen?), CONVICTION (klopt de "
    "thesis?). Geef terug EEN JSON-lijst (geen prose) met de top 10 in volgorde. "
    "Voeg per item een veld 'rank_reason' toe in 1 zin waarom 't deze plek krijgt."
)


async def _dedupe_and_rank(ideas: List[Dict]) -> List[Dict]:
    if not ideas:
        return []
    if len(ideas) <= 3:
        return ideas

    blob = json.dumps(ideas, ensure_ascii=False)[:18000]
    dedup_raw = await asyncio.to_thread(_call_llm, DEDUPE_SYSTEM, blob, 2400, 0.2)
    cleaned = re.sub(r"^```(?:json)?|```$", "", dedup_raw.strip(), flags=re.M).strip()
    try:
        deduped = json.loads(cleaned)
        if not isinstance(deduped, list):
            deduped = ideas
    except json.JSONDecodeError:
        logger.warning("dedupe step returned invalid JSON, falling back to raw ideas")
        deduped = ideas

    if len(deduped) <= 1:
        return deduped

    blob2 = json.dumps(deduped, ensure_ascii=False)[:18000]
    rank_raw = await asyncio.to_thread(_call_llm, RANK_SYSTEM, blob2, 2400, 0.2)
    cleaned2 = re.sub(r"^```(?:json)?|```$", "", rank_raw.strip(), flags=re.M).strip()
    try:
        ranked = json.loads(cleaned2)
        if not isinstance(ranked, list):
            ranked = deduped
    except json.JSONDecodeError:
        logger.warning("rank step returned invalid JSON, falling back to deduped order")
        ranked = deduped
    return ranked[:10]


# ──────────────────────────────────────────────────────────────────────
# Stage 4: persist + notify
# ──────────────────────────────────────────────────────────────────────

def _persist(ideas: List[Dict]) -> List[Dict]:
    """Append each idea as a row with id + discovered_at + status + stage.
    Returns the same list with id/stage populated."""
    IDEAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().isoformat()
    rows = []
    with open(IDEAS_PATH, "a") as f:
        for idea in ideas:
            row = {
                "id": uuid.uuid4().hex[:12],
                "discovered_at": now,
                "status": "open",       # open / acted / archived / dismissed
                "stage": "raw",         # raw / validated / staked / implement / rejected
                **idea,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows.append(row)
    return rows


def update_idea_pipeline(idea_id: str, fields: Dict) -> bool:
    """Update an idea row with new pipeline fields (skeptic/stakes/trader/stage).
    Rewrites the file in place — fine while the JSONL stays small."""
    if not IDEAS_PATH.exists():
        return False
    rows = []
    found = False
    for line in IDEAS_PATH.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("id") == idea_id:
            row.update(fields)
            found = True
        rows.append(row)
    if not found:
        return False
    with open(IDEAS_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return True


def _format_digest(ideas: List[Dict]) -> str:
    if not ideas:
        return "📭 <b>Research digest</b> — geen nieuwe ideeën vandaag."
    today = datetime.utcnow().strftime("%Y-%m-%d")
    by_stage = {s: [i for i in ideas if i.get("stage") == s]
                for s in ("implement", "staked", "validated", "rejected")}
    lines = [
        f"🔬 <b>Research pipeline — {today}</b>",
        f"{len(ideas)} ideas door pipeline · "
        f"{len(by_stage['implement'])}🎯 · {len(by_stage['staked'])}💰 · "
        f"{len(by_stage['validated'])}✅ · {len(by_stage['rejected'])}❌",
    ]
    if by_stage["implement"]:
        lines.append("\n🎯 <b>READY TO TRADE</b>")
        for i, idea in enumerate(by_stage["implement"][:5], start=1):
            ticker = idea.get("ticker_or_event") or "?"
            tr = idea.get("trader") or {}
            st = idea.get("stakes") or {}
            url = tr.get("target_market_url") or ""
            url_part = f' <a href="{url}">[market]</a>' if url else ""
            lines.append(f"\n<b>{i}. {ticker}</b>{url_part}")
            lines.append(f"  → {(tr.get('action_summary') or '')[:180]}")
            stake = st.get("stake_usd")
            entry = tr.get("entry_price")
            if stake or entry:
                lines.append(f"  <i>Stake:</i> ${stake} @ entry {entry}")
            ex = tr.get("exit_triggers")
            if ex:
                lines.append(f"  <i>Exit:</i> {ex[:120]}")
    if by_stage["staked"]:
        lines.append(f"\n💰 <b>STAKED ({len(by_stage['staked'])})</b>")
        for idea in by_stage["staked"][:5]:
            ticker = idea.get("ticker_or_event") or "?"
            st = idea.get("stakes") or {}
            lines.append(f"  • {ticker} — ${st.get('stake_usd')} ({(st.get('rationale') or '')[:80]})")
    if by_stage["validated"]:
        lines.append(f"\n✅ <b>VALIDATED ({len(by_stage['validated'])})</b>")
        for idea in by_stage["validated"][:5]:
            ticker = idea.get("ticker_or_event") or "?"
            sk = idea.get("skeptic") or {}
            lines.append(f"  • {ticker} — {(sk.get('strong_thesis') or '')[:100]}")
    lines.append("\n→ Dashboard: https://polymarket.ai-tigers.com/research")
    return "\n".join(lines)


async def _send_digest(ideas: List[Dict]) -> None:
    try:
        from .integrations import send_telegram
        await send_telegram(_format_digest(ideas))
    except Exception as e:
        logger.warning(f"telegram digest failed: {e}")


# ──────────────────────────────────────────────────────────────────────
# Public entry points
# ──────────────────────────────────────────────────────────────────────

def _congress_fast_path(items: List[Dict]) -> tuple:
    """Pre-filter congress items where the ticker is on the stocks-watchlist
    OR the senator is on the politicians-watchlist. These bypass the LLM
    pipeline and become Implement-stage ideas directly: the signal is
    already validated by two independent filters (your handpicked stocks +
    your handpicked politicians).

    Returns (fast_path_ideas, remaining_items)."""
    try:
        from . import stocks_data
        stock_watchlist = {t.upper() for t in (stocks_data.get_watchlist() or [])}
        pol_watchlist = {p.lower() for p in (stocks_data.get_politician_watchlist() or [])}
    except Exception:
        return [], items

    fast: List[Dict] = []
    remain: List[Dict] = []
    for it in items:
        src = (it.get("source") or "")
        if not src.startswith("Congress:"):
            remain.append(it)
            continue
        rep = src.replace("Congress:", "").strip()
        title = it.get("title") or ""
        # Extract ticker from title — "Rep kocht TICKER (range)"
        import re
        m = re.search(r"kocht\s+([A-Z][A-Z0-9.\-]{0,5})\b", title)
        ticker = m.group(1) if m else None
        on_stock_wl = ticker and ticker.upper() in stock_watchlist
        on_pol_wl = rep.lower() in pol_watchlist
        if not (on_stock_wl or on_pol_wl):
            remain.append(it)
            continue
        reasons = []
        if on_stock_wl: reasons.append(f"{ticker} on stocks watchlist")
        if on_pol_wl:   reasons.append(f"{rep} on politicians watchlist")
        # Synthetic Implement-stage idea — no LLM needed
        fast.append({
            "market_type": "stocks",
            "ticker_or_event": ticker or "?",
            "thesis": f"Congressional disclosure: {it.get('body','')[:180]}",
            "conviction": 4,
            "why_now": "Fresh STOCK Act disclosure; double-filtered ({}).".format(" + ".join(reasons)),
            "source": src,
            "source_title": title,
            "source_url": it.get("url",""),
            "source_ts": it.get("ts",""),
            # Pre-built pipeline payload — skips Skeptic/Stakes/Trader
            "stage": "implement",
            "skeptic": {"pass": True, "score": 0.8,
                          "strong_thesis": f"Congressional purchase of {ticker} matches a hand-curated filter ({', '.join(reasons)}).",
                          "rejected_reason": None,
                          "devils_advocate": "Disclosure can lag actual trade by 30-45 days; alpha may be stale.",
                          "at": datetime.utcnow().isoformat()},
            "stakes": {"stake_usd": 100.0, "max_exposure_pct": 5.0,
                         "rationale": "Default stocks stake. Double-filter signal.",
                         "skip": False,
                         "at": datetime.utcnow().isoformat()},
            "trader": {"target_market_url": None,
                          "entry_price": None,
                          "exit_triggers": "TP +20% / SL -10% / 90d max-hold (hardcoded paper rules)",
                          "stop_loss": None,
                          "time_to_resolution": "90 days",
                          "action_summary": f"Follow {rep} into {ticker}.",
                          "at": datetime.utcnow().isoformat()},
        })
    return fast, remain


async def run_daily() -> Dict:
    """Full Scout→Skeptic→Stakes→Trader pipeline. Returns summary for API."""
    started = datetime.utcnow()
    items = await _ingest_all()
    if not items:
        await _send_digest([])
        return {"ingested": 0, "filtered": 0, "top": 0, "ms": 0, "ideas": []}

    # Fast-path: congress trades on the stocks/politician watchlists skip the
    # LLM pipeline — the double-filter is enough signal on its own.
    fast_path_ideas, items = _congress_fast_path(items)
    if fast_path_ideas:
        logger.info(f"research_agent fast-path: {len(fast_path_ideas)} congress watchlist-overlap ideas")

    ideas = await _filter_all(items)
    top = await _dedupe_and_rank(ideas)

    # Persist first so rows get ids — then the 3-stage pipeline updates
    # each row in place with skeptic/stakes/trader/stage fields.
    # Fast-path ideas (pre-validated by the double-filter) are persisted
    # separately and SKIP run_pipeline — otherwise Skeptic would re-judge
    # them from scratch and might override the synthetic pipeline data.
    piped: List[Dict] = []
    if fast_path_ideas:
        piped.extend(_persist(fast_path_ideas))
    if top:
        persisted = _persist(top)
        try:
            from .pipeline import run_pipeline
            run_through = await run_pipeline(persisted, concurrency=2)
            for it in run_through:
                upd = {k: it.get(k) for k in ("skeptic", "stakes", "trader", "stage") if it.get(k) is not None}
                if upd and it.get("id"):
                    update_idea_pipeline(it["id"], upd)
            piped.extend(run_through)
        except Exception as e:
            logger.warning(f"pipeline failed (ideas persisted as raw): {e}")
            piped.extend(persisted)

    # Auto-open paper-trade positions for every Implement-stage idea
    # (whether from the LLM pipeline or the fast-path).
    try:
        from .research_paper_trader import open_paper_position
        for it in piped:
            if it.get("stage") == "implement":
                await open_paper_position(it)
    except Exception as e:
        logger.warning(f"paper-trader open failed: {e}")

    await _send_digest(piped or top)
    elapsed = int((datetime.utcnow() - started).total_seconds() * 1000)

    # Counters for API + Telegram digest
    def _count_stage(s: str) -> int:
        return sum(1 for it in piped if it.get("stage") == s)
    return {
        "ingested": len(items),
        "filtered": len(ideas),
        "top": len(top),
        "validated": _count_stage("validated"),
        "staked": _count_stage("staked"),
        "implement": _count_stage("implement"),
        "rejected": _count_stage("rejected"),
        "ms": elapsed,
        "ideas": piped,
    }


def list_ideas(limit: int = 100, status: Optional[str] = None,
               market_type: Optional[str] = None,
               stage: Optional[str] = None) -> List[Dict]:
    """List ideas, filterable by user-status (open/acted/...), market_type,
    and/or pipeline stage (raw/validated/staked/implement/rejected)."""
    if not IDEAS_PATH.exists():
        return []
    out: List[Dict] = []
    for line in IDEAS_PATH.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if status and row.get("status") != status:
            continue
        if market_type and row.get("market_type") != market_type:
            continue
        if stage and row.get("stage") != stage:
            continue
        out.append(row)
    out.reverse()
    return out[:limit]


def update_idea_status(idea_id: str, new_status: str) -> bool:
    """Rewrite the JSONL in place (small file, fine). Returns True if found."""
    if not IDEAS_PATH.exists():
        return False
    rows = []
    found = False
    for line in IDEAS_PATH.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("id") == idea_id:
            row["status"] = new_status
            row["status_updated_at"] = datetime.utcnow().isoformat()
            found = True
        rows.append(row)
    if not found:
        return False
    with open(IDEAS_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return True
