"""
SEC EDGAR feeds — Form 4 (insider transactions) + Schedule 13D/13G (5%+
activist/passive ownership). Free public APIs; SEC fair-access policy
requires a contact User-Agent.

Uses EFTS (EDGAR Full-Text Search) for historical filings rather than
the cgi-bin Atom feed which only shows the last few minutes.
"""
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import httpx
from loguru import logger

# Per SEC: include real contact in UA. Identifies us as a polite client.
SEC_USER_AGENT = "Polymarket Bot research@jorisfalter.com"

EFTS_SEARCH = "https://efts.sec.gov/LATEST/search-index"

# 30 minute cache — SEC asks for ≤10 req/sec sustained, and these feeds
# only refresh every few minutes anyway.
_cache: Dict[str, Dict] = {}
_cache_ttl = timedelta(minutes=30)

# Known activist funds to flag in 13D output. Not exhaustive but covers
# the players whose filings actually move stocks.
KNOWN_ACTIVISTS = {
    "pershing square": "Pershing Square",
    "elliott": "Elliott",
    "starboard": "Starboard Value",
    "engine": "Engine Capital",
    "trian": "Trian Partners",
    "valueact": "ValueAct",
    "icahn": "Carl Icahn",
    "third point": "Third Point",
    "jana": "Jana Partners",
    "engine no. 1": "Engine No. 1",
    "ancora": "Ancora",
    "blue harbour": "Blue Harbour",
    "irenic": "Irenic Capital",
    "macellum": "Macellum Capital",
    "scopia": "Scopia Capital",
}

async def _efts_search(forms: str, limit: int = 60) -> List[Dict]:
    """Query EDGAR Full-Text Search for the most recent filings of given forms."""
    cache_key = f"{forms}:{limit}"
    cached = _cache.get(cache_key)
    if cached and datetime.utcnow() - cached["timestamp"] < _cache_ttl:
        return cached["entries"]

    # EFTS encodes spaces in form names as URL spaces; httpx handles encoding.
    params = {"q": "", "forms": forms}
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": SEC_USER_AGENT}) as client:
            r = await client.get(EFTS_SEARCH, params=params)
            r.raise_for_status()
            data = r.json() or {}
    except Exception as e:
        logger.warning(f"EFTS fetch failed for {forms}: {e}")
        return cached["entries"] if cached else []

    hits = (data.get("hits") or {}).get("hits") or []
    entries: List[Dict] = []
    for h in hits[:limit]:
        src = h.get("_source") or {}
        adsh = src.get("adsh") or ""
        cik_match = re.search(r"\(CIK\s*0*(\d+)\)", str(src.get("display_names") or ""))
        cik = cik_match.group(1) if cik_match else None
        link = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&dateb=&owner=include&count=40"
            if cik else "https://www.sec.gov/cgi-bin/browse-edgar"
        )
        # Build clickable filing-index URL when possible
        if cik and adsh:
            adsh_compact = adsh.replace("-", "")
            link = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh_compact}/{adsh}-index.htm"
        entries.append({
            "form": src.get("form"),
            "file_date": src.get("file_date"),
            "display_names": src.get("display_names") or [],
            "adsh": adsh,
            "link": link,
        })
    _cache[cache_key] = {"timestamp": datetime.utcnow(), "entries": entries}
    return entries


def _parse_display_name(name: str) -> Dict:
    """display_names entries look like:
    'APPLE INC  (AAPL)  (CIK 0000320193)' or
    'Apple Inc.  (CIK 0000320193)' (no ticker)"""
    out = {"raw": name}
    m_ticker = re.search(r"\(([A-Z]{1,5})\)", name)
    if m_ticker:
        out["ticker"] = m_ticker.group(1)
    m_company = re.match(r"^\s*([^(]+?)\s*\(", name)
    if m_company:
        out["company"] = m_company.group(1).strip()
    return out


def _flag_activist(name: str) -> Optional[str]:
    if not name:
        return None
    lower = name.lower()
    for key, label in KNOWN_ACTIVISTS.items():
        if key in lower:
            return label
    return None


async def fetch_form4_buys(limit: int = 30) -> List[Dict]:
    """Recent Form 4 (insider transactions). We can't determine purchase vs
    sale from the search index alone — the user clicks through to read
    detail. Each entry has issuer (with ticker if available)."""
    entries = await _efts_search("4", limit=limit * 2)
    out: List[Dict] = []
    for e in entries:
        # Pick the entity with a ticker (the issuer) over the reporting person
        names = e.get("display_names") or []
        issuer = None
        reporter = None
        for n in names:
            parsed = _parse_display_name(n)
            if parsed.get("ticker"):
                issuer = parsed
            else:
                reporter = parsed
        out.append({
            "form": e.get("form"),
            "file_date": e.get("file_date"),
            "ticker": issuer.get("ticker") if issuer else None,
            "issuer": (issuer or reporter or {}).get("company"),
            "reporter": reporter.get("company") if reporter else None,
            "link": e.get("link"),
            "adsh": e.get("adsh"),
        })
    return out[:limit]


async def fetch_13d_filings(limit: int = 30) -> List[Dict]:
    """Recent 13D/13G filings. Activist filers are flagged + ranked first."""
    items: List[Dict] = []
    for form_type in ("SC 13D", "SC 13G"):
        entries = await _efts_search(form_type, limit=60)
        for e in entries:
            names = e.get("display_names") or []
            subject = None
            filer = None
            for n in names:
                parsed = _parse_display_name(n)
                if parsed.get("ticker"):
                    subject = parsed
                else:
                    filer = parsed
            filer_name = (filer or {}).get("company") or ""
            items.append({
                "form": e.get("form"),
                "is_amendment": "/A" in (e.get("form") or ""),
                "file_date": e.get("file_date"),
                "ticker": subject.get("ticker") if subject else None,
                "subject": (subject or {}).get("company"),
                "filer": filer_name,
                "activist": _flag_activist(filer_name),
                "link": e.get("link"),
            })
    items.sort(key=lambda x: x.get("file_date", ""), reverse=True)
    activist_first = [i for i in items if i.get("activist")]
    rest = [i for i in items if not i.get("activist")]
    return (activist_first + rest)[:limit]
