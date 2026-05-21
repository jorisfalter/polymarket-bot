"""
Direct congress-data scrapers — House Clerk + Senate efdsearch.

Built 2026-05-21 after the free third-party sources all went dark:
- Finnhub's congress endpoint → 403 on free tier
- House/Senate Stock Watcher S3 buckets → 403
- senate-stock-watcher GitHub repo → last data Nov 2020
- CapitolTrades' BFF → CloudFront 503

These functions hit the OFFICIAL disclosure portals directly. Slower
and more fragile than a paid API, but durable: as long as the disclosure
law (STOCK Act 2012) stands, these portals serve fresh data.

House flow:
  1. Annual ZIP (disclosures-clerk.house.gov/.../{YEAR}FD.zip) → FD.xml
  2. Filter FilingType=P (Periodic Transaction Report)
  3. For each PTR: fetch PDF → pdfplumber → regex extract transactions

Senate flow:
  1. Accept disclaimer (POST /search/home/, sets _gov_efd session cookie)
  2. POST /search/report/data/ with PTR filter → JSON with rows
  3. Per row, fetch HTML view + parse transaction table
"""
from __future__ import annotations

import asyncio
import io
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from loguru import logger

# ──────────────────────────────────────────────────────────────────────
# Disk cache for parsed PTRs — PDFs are expensive to re-fetch + parse.
# ──────────────────────────────────────────────────────────────────────
_CACHE_DIR = Path(__file__).parent.parent / "data" / "congress_cache"
_CACHE_TTL_HOURS = 7 * 24  # 1 week


def _cache_get(key: str) -> Optional[Dict]:
    p = _CACHE_DIR / f"{key}.json"
    if not p.exists():
        return None
    try:
        import json
        d = json.loads(p.read_text())
        ts = datetime.fromisoformat(d.get("cached_at", ""))
        if datetime.utcnow() - ts < timedelta(hours=_CACHE_TTL_HOURS):
            return d.get("data")
    except Exception:
        pass
    return None


def _cache_put(key: str, data) -> None:
    import json
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _CACHE_DIR / f"{key}.json"
    try:
        p.write_text(json.dumps({"cached_at": datetime.utcnow().isoformat(), "data": data}))
    except Exception as e:
        logger.debug(f"cache write failed for {key}: {e}")


# ──────────────────────────────────────────────────────────────────────
# House Clerk
# ──────────────────────────────────────────────────────────────────────

HOUSE_FD_ZIP = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
HOUSE_PTR_PDF = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"

# Match a transaction line in House PTR text. The PDF text is
# linearized so each transaction occupies a line like:
#   "Asset Name (TICKER) [ST]  P  04/14/2026  05/07/2026  $1,001 - $15,000"
# Multi-line wraps are possible — we tolerate via DOTALL and \s+.
_HOUSE_TX_RE = re.compile(
    r"\(([A-Z][A-Z0-9.\-]{0,5})\)\s*(?:\[[A-Z]{1,3}\])?\s+"          # (TICKER) [ST]
    r"(P|S\s*\(partial\)|S|E)\s+"                                    # type
    r"(\d{2}/\d{2}/\d{4})\s+"                                        # txn date
    r"(\d{2}/\d{2}/\d{4})\s+"                                        # notification date
    r"(\$[\d,]+\s*-\s*\$?[\d,]+|Over\s+\$[\d,]+|\$[\d,]+\+)"          # amount range
)


async def fetch_house_ptr_metadata(year: Optional[int] = None) -> List[Dict]:
    """Download the annual House FD index, return all FilingType=P entries
    with rep name + DocID + FilingDate."""
    yr = year or datetime.utcnow().year
    cache_key = f"house_index_{yr}"
    cached = _cache_get(cache_key)
    if cached is not None:
        # Only honour cache when source ZIP hasn't moved on (cheap HEAD check)
        return cached
    url = HOUSE_FD_ZIP.format(year=yr)
    try:
        async with httpx.AsyncClient(timeout=60.0,
                                     headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = await c.get(url)
            r.raise_for_status()
            data = r.content
    except Exception as e:
        logger.warning(f"House FD zip fetch failed: {e}")
        return []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml_name = next((n for n in zf.namelist() if n.endswith(".xml")), None)
            if not xml_name:
                return []
            xml_bytes = zf.read(xml_name)
    except Exception as e:
        logger.warning(f"House FD zip parse failed: {e}")
        return []
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        logger.warning(f"House FD XML parse failed: {e}")
        return []
    out: List[Dict] = []
    for m in root.findall("Member"):
        if (m.findtext("FilingType") or "") != "P":
            continue
        first = (m.findtext("First") or "").strip()
        last = (m.findtext("Last") or "").strip()
        prefix = (m.findtext("Prefix") or "").strip()
        rep_name = " ".join(p for p in (prefix, first, last) if p)
        out.append({
            "representative": rep_name,
            "doc_id": m.findtext("DocID") or "",
            "filing_date": _iso_date(m.findtext("FilingDate") or ""),
            "state": m.findtext("StateDst") or "",
            "year": yr,
        })
    out.sort(key=lambda x: x["filing_date"] or "", reverse=True)
    _cache_put(cache_key, out)
    logger.info(f"House PTR index ({yr}): {len(out)} filings")
    return out


async def parse_house_ptr_pdf(doc_id: str, year: Optional[int] = None) -> List[Dict]:
    """Fetch + parse one PTR PDF. Returns list of transactions or [] on
    failure (scanned-image PDFs return no text)."""
    if not doc_id:
        return []
    yr = year or datetime.utcnow().year
    cache_key = f"house_ptr_{yr}_{doc_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    url = HOUSE_PTR_PDF.format(year=yr, doc_id=doc_id)
    try:
        async with httpx.AsyncClient(timeout=30.0,
                                     headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = await c.get(url)
            if r.status_code != 200:
                return []
            pdf_bytes = r.content
    except Exception as e:
        logger.debug(f"PTR PDF fetch failed for {doc_id}: {e}")
        return []
    try:
        import pdfplumber
        text_parts: List[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        full = "\n".join(text_parts)
    except Exception as e:
        logger.debug(f"PTR PDF parse failed for {doc_id}: {e}")
        return []

    transactions: List[Dict] = []
    for match in _HOUSE_TX_RE.finditer(full):
        ticker, type_raw, tx_date, notif_date, amount = match.groups()
        # Resolve asset_description from the line preceding the ticker
        # (best-effort — useful when ticker is ambiguous).
        ctx_start = max(0, match.start() - 120)
        ctx = full[ctx_start:match.start()].rsplit("\n", 1)[-1].strip()
        type_norm = "purchase" if type_raw == "P" else "sale" if type_raw.startswith("S") else "exchange"
        transactions.append({
            "ticker": ticker.upper(),
            "type": type_norm,
            "type_raw": type_raw,
            "transaction_date": _iso_date(tx_date),
            "notification_date": _iso_date(notif_date),
            "amount": amount,
            "asset_description": ctx[:200],
        })
    _cache_put(cache_key, transactions)
    return transactions


async def fetch_house_transactions(days_back: int = 30, max_filings: int = 60) -> List[Dict]:
    """Top-level House fetcher. Returns trades in the common shape used by
    stocks_data.fetch_politician_trades."""
    yr = datetime.utcnow().year
    index = await fetch_house_ptr_metadata(yr)
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    recent = [m for m in index if m["filing_date"] and m["filing_date"] >= cutoff]
    recent = recent[:max_filings]
    logger.info(f"House: parsing {len(recent)} recent PTR PDFs (cutoff {cutoff})")

    sem = asyncio.Semaphore(4)
    async def _one(meta: Dict) -> List[Dict]:
        async with sem:
            txs = await parse_house_ptr_pdf(meta["doc_id"], year=yr)
        return [_to_common_shape(meta, t, chamber="House") for t in txs]

    results = await asyncio.gather(*(_one(m) for m in recent), return_exceptions=True)
    out: List[Dict] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    out.sort(key=lambda t: t.get("transaction_date", ""), reverse=True)
    logger.info(f"House: {len(out)} transactions parsed from {len(recent)} PTRs")
    return out


# ──────────────────────────────────────────────────────────────────────
# CapitolTrades — React Server Component scraper (covers House + Senate)
# ──────────────────────────────────────────────────────────────────────
#
# Discovered 2026-05-21 while looking for a Senate-data path after
# efdsearch.senate.gov turned out to be Akamai-blocked from any
# datacenter IP. The capitoltrades.com Next.js app SSR's its data
# into React Server Component payloads — those are HTTP-fetchable
# without any session or anti-bot bypass. The trick is the `_rsc=`
# query parameter + the `RSC: 1` header; the response is a stream
# of lines like `id:value` and the "0:" line contains the page data
# with trades embedded as clean JSON objects.
#
# Each trade looks like:
#   {"_issuerId":429914,"_politicianId":"M001236","_txId":...,
#    "chamber":"house","issuer":{"issuerName":"AT&T Inc",
#    "issuerTicker":"T:US","sector":"..."},"politician":{
#    "firstName":"Tim","lastName":"Moore","party":"republican",
#    "chamber":"house"},"price":24.43,"txDate":"2026-05-18",
#    "txType":"buy","value":32500}
#
# Way cleaner than parsing House PDFs and covers Senate too.

CAPITOLTRADES_BASE = "https://www.capitoltrades.com"
_CT_RSC_PARAM = "bx0x8"  # build ID; if their build changes we may need to update

_CT_TRADE_RE = re.compile(
    r'\{"_issuerId":\d+,"_politicianId":"[^"]+","_txId":\d+,'
    r'(?:[^{}]|\{[^{}]*\})*?\}'
)


async def _fetch_capitoltrades_rsc(path: str, params: Optional[Dict] = None) -> str:
    """Fetch an RSC payload from capitoltrades.com. Returns raw text or ""."""
    url = f"{CAPITOLTRADES_BASE}{path}"
    query = dict(params or {})
    query["_rsc"] = _CT_RSC_PARAM
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/x-component",
        "RSC": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as c:
            r = await c.get(url, params=query)
            r.raise_for_status()
            return r.text
    except Exception as e:
        logger.debug(f"capitoltrades RSC fetch failed for {url}: {e}")
        return ""


def _parse_capitoltrades_trades(rsc_text: str) -> List[Dict]:
    """Extract trade JSON objects from a CapitolTrades RSC payload."""
    import json
    out: List[Dict] = []
    for raw in _CT_TRADE_RE.findall(rsc_text):
        try:
            obj = json.loads(raw)
            out.append(obj)
        except json.JSONDecodeError:
            continue
    return out


def _normalize_capitoltrades_trade(t: Dict) -> Dict:
    """CapitolTrades trade → our common shape."""
    pol = t.get("politician") or {}
    iss = t.get("issuer") or {}
    full_name = " ".join(p for p in (pol.get("firstName"), pol.get("lastName")) if p)
    tx_type = (t.get("txType") or "").lower()
    if tx_type == "buy":
        type_norm = "purchase"
    elif tx_type == "sell":
        type_norm = "sale"
    elif tx_type == "exchange":
        type_norm = "exchange"
    else:
        type_norm = tx_type
    # CapitolTrades tickers look like "T:US" / "IHG:US" — strip suffix.
    ticker = (iss.get("issuerTicker") or "").upper().split(":")[0]
    value = t.get("value")
    return {
        "chamber": (t.get("chamber") or pol.get("chamber") or "").title(),
        "representative": full_name or "?",
        "party": pol.get("party") or "",
        "ticker": ticker,
        "asset": iss.get("issuerName") or "",
        "type": type_norm,
        "amount": f"${value:,}" if isinstance(value, (int, float)) else "",
        "amount_usd": float(value or 0),
        "transaction_date": t.get("txDate") or "",
        "disclosure_date": (t.get("pubDate") or "")[:10],
        "excess_return": None,
        "price_change": None,
        "_txId": t.get("_txId"),
        "_politicianId": t.get("_politicianId"),
    }


async def fetch_capitoltrades_transactions(
    days_back: int = 30, max_pages: int = 30,
) -> List[Dict]:
    """Paginate CapitolTrades' /trades feed until we've covered days_back.
    Returns deduped + normalized trades (House + Senate)."""
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    seen_tx: set = set()
    out: List[Dict] = []
    for page in range(1, max_pages + 1):
        rsc = await _fetch_capitoltrades_rsc("/trades", {
            "page": str(page),
            "pageSize": "96",  # what their site uses
            "sortBy": "-publishDate",
        })
        if not rsc:
            break
        trades = _parse_capitoltrades_trades(rsc)
        if not trades:
            break
        oldest_on_page = ""
        for t in trades:
            tx_id = t.get("_txId")
            if tx_id is not None:
                if tx_id in seen_tx:
                    continue
                seen_tx.add(tx_id)
            norm = _normalize_capitoltrades_trade(t)
            tx_date = norm["transaction_date"]
            if tx_date and tx_date < cutoff:
                continue
            out.append(norm)
            if tx_date and (not oldest_on_page or tx_date < oldest_on_page):
                oldest_on_page = tx_date
        # Stop if entire page is older than cutoff
        if oldest_on_page and oldest_on_page < cutoff:
            break
    out.sort(key=lambda t: t.get("transaction_date", ""), reverse=True)
    logger.info(f"CapitolTrades: {len(out)} trades in last {days_back}d "
                f"({len(seen_tx)} unique _txIds, {page} pages scanned)")
    return out


# ──────────────────────────────────────────────────────────────────────
# Senate efdsearch — DEPRECATED 2026-05-21
# Akamai blocks every datacenter IP we tested with 403. Kept for
# reference; not wired into fetch_all_congress anymore.
# ──────────────────────────────────────────────────────────────────────

SENATE_BASE = "https://efdsearch.senate.gov"


async def _senate_session() -> Optional[httpx.AsyncClient]:
    """Build an httpx client that has accepted the disclaimer. Returns
    None on failure."""
    client = httpx.AsyncClient(
        timeout=30.0, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        # Land on the disclaimer page to seed cookies + CSRF
        r = await client.get(f"{SENATE_BASE}/search/home/")
        r.raise_for_status()
        csrf = client.cookies.get("csrftoken") or ""
        # Accept the disclaimer
        r2 = await client.post(
            f"{SENATE_BASE}/search/home/",
            data={"prohibition_agreement": "1", "csrfmiddlewaretoken": csrf},
            headers={"Referer": f"{SENATE_BASE}/search/home/"},
        )
        if r2.status_code not in (200, 302):
            logger.warning(f"Senate disclaimer POST failed: {r2.status_code}")
            await client.aclose()
            return None
        return client
    except Exception as e:
        logger.warning(f"Senate session init failed: {e}")
        await client.aclose()
        return None


async def fetch_senate_transactions(days_back: int = 30) -> List[Dict]:
    """Search efdsearch for recent PTR filings and parse each detail page."""
    client = await _senate_session()
    if not client:
        return []
    try:
        cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%m/%d/%Y")
        today = datetime.utcnow().strftime("%m/%d/%Y")
        csrf = client.cookies.get("csrftoken") or ""
        # The data endpoint returns a DataTables payload
        r = await client.post(
            f"{SENATE_BASE}/search/report/data/",
            data={
                "csrfmiddlewaretoken": csrf,
                "report_types": "[11]",   # 11 = PTR
                "filer_types": "[]",
                "submitted_start_date": cutoff,
                "submitted_end_date": today,
                "candidate_state": "",
                "senator_state": "",
                "office_id": "",
                "first_name": "",
                "last_name": "",
                "start": "0",
                "length": "100",
            },
            headers={"Referer": f"{SENATE_BASE}/search/"},
        )
        if r.status_code != 200:
            logger.warning(f"Senate search failed: {r.status_code}")
            return []
        try:
            payload = r.json()
        except Exception:
            logger.warning("Senate search returned non-JSON")
            return []
        rows = payload.get("data") or []
    except Exception as e:
        logger.warning(f"Senate search error: {e}")
        await client.aclose()
        return []
    logger.info(f"Senate: {len(rows)} PTR filings in last {days_back}d")

    # Each row is a list — DataTables format: [first, last, office, report, filed_at, link_html]
    # The link_html contains an <a href="/search/view/ptr/UUID/"> link.
    filings: List[Dict] = []
    for row in rows:
        try:
            first = _html_text(row[0])
            last = _html_text(row[1])
            report_html = row[3]
            filed = _html_text(row[4]) if len(row) > 4 else ""
            link_match = re.search(r'href="([^"]+/ptr/[^"]+)"', report_html or "")
            if not link_match:
                continue
            filings.append({
                "representative": f"{first} {last}".strip(),
                "filing_date": _iso_date(filed),
                "detail_url": SENATE_BASE + link_match.group(1),
            })
        except Exception:
            continue

    sem = asyncio.Semaphore(4)
    async def _one(f: Dict) -> List[Dict]:
        async with sem:
            txs = await _parse_senate_ptr(client, f["detail_url"])
        return [_to_common_shape({
            "representative": f["representative"],
            "filing_date": f["filing_date"],
        }, t, chamber="Senate") for t in txs]

    results = await asyncio.gather(*(_one(f) for f in filings), return_exceptions=True)
    await client.aclose()
    out: List[Dict] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    out.sort(key=lambda t: t.get("transaction_date", ""), reverse=True)
    logger.info(f"Senate: {len(out)} transactions parsed from {len(filings)} PTRs")
    return out


async def _parse_senate_ptr(client: httpx.AsyncClient, url: str) -> List[Dict]:
    """Senate PTR detail pages are HTML with a transactions table. Older
    paper filings link to PDFs — we skip those (out of scope for v1)."""
    try:
        r = await client.get(url)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        logger.debug(f"Senate PTR detail fetch failed {url}: {e}")
        return []
    if "/paper/" in url or url.lower().endswith(".pdf"):
        return []  # scanned paper filing — skipped
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("bs4 not installed — cannot parse senate PTR")
        return []
    soup = BeautifulSoup(html, "html.parser")
    txs: List[Dict] = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not any("ticker" in h or "asset" in h for h in headers):
            continue
        # Map header positions
        def _idx(label_part: str) -> int:
            for i, h in enumerate(headers):
                if label_part in h:
                    return i
            return -1
        i_ticker = _idx("ticker")
        i_asset = _idx("asset")
        i_type = _idx("type")
        i_date = _idx("transaction date") if _idx("transaction date") >= 0 else _idx("date")
        i_amount = _idx("amount")
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if not cells:
                continue
            tk = cells[i_ticker] if i_ticker >= 0 and i_ticker < len(cells) else ""
            tk = (tk or "").upper().strip()
            if not tk or tk in ("--", "N/A"):
                continue
            type_raw = cells[i_type] if i_type >= 0 and i_type < len(cells) else ""
            type_norm = "purchase" if "purchase" in type_raw.lower() else "sale" if "sale" in type_raw.lower() else type_raw.lower()
            txs.append({
                "ticker": tk,
                "type": type_norm,
                "type_raw": type_raw,
                "transaction_date": _iso_date(cells[i_date] if i_date >= 0 and i_date < len(cells) else ""),
                "amount": cells[i_amount] if i_amount >= 0 and i_amount < len(cells) else "",
                "asset_description": cells[i_asset] if i_asset >= 0 and i_asset < len(cells) else "",
            })
    return txs


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _iso_date(s: str) -> str:
    """MM/DD/YYYY → YYYY-MM-DD. Already-ISO strings pass through."""
    if not s:
        return ""
    s = s.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        mm, dd, yyyy = m.groups()
        return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
    return s


def _html_text(html_or_text: str) -> str:
    """Strip HTML tags from a cell value (rows come with anchor markup)."""
    if not html_or_text:
        return ""
    return re.sub(r"<[^>]+>", "", str(html_or_text)).strip()


def _to_common_shape(meta: Dict, tx: Dict, chamber: str) -> Dict:
    """Map a parsed transaction to the shape stocks_data already uses,
    so the rest of the codebase keeps working unchanged."""
    return {
        "chamber": chamber,
        "representative": meta.get("representative") or "?",
        "party": "",
        "ticker": (tx.get("ticker") or "").upper(),
        "asset": tx.get("asset_description") or "",
        "type": tx.get("type") or "?",
        "amount": tx.get("amount") or "",
        "amount_usd": 0,  # source gives a range string, not a number
        "transaction_date": tx.get("transaction_date") or "",
        "disclosure_date": meta.get("filing_date") or "",
        "excess_return": None,
        "price_change": None,
    }


# ──────────────────────────────────────────────────────────────────────
# Top-level combined fetcher
# ──────────────────────────────────────────────────────────────────────

async def fetch_all_congress(days_back: int = 30) -> List[Dict]:
    """Combined source: CapitolTrades RSC (House+Senate, clean dollar
    values, fast) + House Clerk PDFs (fallback / cross-check, slower).

    Dedupes by (chamber, representative, ticker, transaction_date) since
    the two sources have different _txId schemes.
    """
    capitol, house = await asyncio.gather(
        fetch_capitoltrades_transactions(days_back=days_back),
        fetch_house_transactions(days_back=days_back),
        return_exceptions=True,
    )
    out: List[Dict] = []
    seen: set = set()
    def _key(t: Dict) -> tuple:
        rep = (t.get("representative") or "").strip().lower()
        # Strip "Hon." prefix that House PDFs sometimes include
        for p in ("hon.", "rep.", "sen."):
            if rep.startswith(p):
                rep = rep[len(p):].strip()
        return (rep, t.get("ticker", "").upper(), t.get("transaction_date", ""), t.get("type", ""))
    for src in (capitol, house):
        if isinstance(src, list):
            for t in src:
                k = _key(t)
                if k in seen:
                    continue
                seen.add(k)
                out.append(t)
    out.sort(key=lambda t: t.get("transaction_date", ""), reverse=True)
    return out
