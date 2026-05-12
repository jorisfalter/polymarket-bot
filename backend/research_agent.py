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

    bucket: List[Dict] = []
    results = await asyncio.gather(_gmail(), _rss(), _reddit(), _youtube(), return_exceptions=True)
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

def _persist(ideas: List[Dict]) -> None:
    IDEAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().isoformat()
    with open(IDEAS_PATH, "a") as f:
        for idea in ideas:
            row = {
                "id": uuid.uuid4().hex[:12],
                "discovered_at": now,
                "status": "open",  # open / acted / archived / dismissed
                **idea,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _format_digest(ideas: List[Dict]) -> str:
    if not ideas:
        return "📭 <b>Research digest</b> — geen nieuwe ideeën vandaag."
    today = datetime.utcnow().strftime("%Y-%m-%d")
    lines = [f"📰 <b>Research digest — {today}</b>", f"Top {len(ideas)} ideas van vandaag:"]
    for i, idea in enumerate(ideas[:5], start=1):
        mt = (idea.get("market_type") or "?").upper()
        ticker = idea.get("ticker_or_event") or "?"
        conv = "★" * int(idea.get("conviction") or 0)
        thesis = (idea.get("thesis") or "")[:200]
        why = (idea.get("why_now") or "")[:150]
        src = idea.get("source") or "?"
        lines.append(f"\n<b>{i}. [{mt}] {ticker}</b> {conv}")
        lines.append(f"  {thesis}")
        if why:
            lines.append(f"  <i>Why now:</i> {why}")
        lines.append(f"  <i>via {src}</i>")
    lines.append("\n→ Dashboard: https://polymarket.ai-tigers.com/ideas")
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

async def run_daily() -> Dict:
    """Full pipeline. Returns a summary dict suitable for an API response."""
    started = datetime.utcnow()
    items = await _ingest_all()
    if not items:
        await _send_digest([])
        return {"ingested": 0, "ideas": 0, "ms": 0}
    ideas = await _filter_all(items)
    top = await _dedupe_and_rank(ideas)
    if top:
        _persist(top)
    await _send_digest(top)
    elapsed = int((datetime.utcnow() - started).total_seconds() * 1000)
    return {
        "ingested": len(items),
        "filtered": len(ideas),
        "top": len(top),
        "ms": elapsed,
        "ideas": top,
    }


def list_ideas(limit: int = 100, status: Optional[str] = None,
               market_type: Optional[str] = None) -> List[Dict]:
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
