"""
Auditor mapping for earnings insider detection.

Based on the EventWaves analysis: wallets that systematically bet big
only on companies with the same auditor (e.g., KPMG) are likely insiders
with access to pre-release earnings data through the audit firm.

Pattern: wallet bets $5k on KPMG-audited company earnings, $50 on others.
"""

# Major public companies mapped to their Big 4 auditor
# Source: SEC filings, 10-K annual reports
COMPANY_AUDITORS = {
    # KPMG clients (the ones flagged in the EventWaves article)
    "wells fargo": "KPMG",
    "carmax": "KPMG",
    "five below": "KPMG",
    "general electric": "KPMG",
    "ge aerospace": "KPMG",
    "citigroup": "KPMG",
    "citi": "KPMG",
    "intel": "KPMG",
    "mastercard": "KPMG",
    "morgan stanley": "KPMG",
    "philips": "KPMG",
    "shell": "KPMG",
    "siemens": "KPMG",
    "barclays": "KPMG",
    "hp": "KPMG",
    "hewlett packard": "KPMG",
    "hsbc": "KPMG",
    "ing": "KPMG",
    "td bank": "KPMG",
    "walgreens": "KPMG",

    # Deloitte clients
    "apple": "Deloitte",
    "microsoft": "Deloitte",
    "google": "Deloitte",
    "alphabet": "Deloitte",
    "amazon": "Deloitte",
    "meta": "Deloitte",
    "facebook": "Deloitte",
    "berkshire hathaway": "Deloitte",
    "procter & gamble": "Deloitte",
    "p&g": "Deloitte",
    "boeing": "Deloitte",
    "gm": "Deloitte",
    "general motors": "Deloitte",
    "ford": "Deloitte",
    "goldman sachs": "Deloitte",
    "morgan stanley": "Deloitte",
    "comcast": "Deloitte",
    "salesforce": "Deloitte",
    "starbucks": "Deloitte",
    "target": "Deloitte",

    # EY (Ernst & Young) clients
    "nvidia": "EY",
    "tesla": "EY",
    "walmart": "EY",
    "jpmorgan": "EY",
    "jp morgan": "EY",
    "johnson & johnson": "EY",
    "j&j": "EY",
    "coca-cola": "EY",
    "coca cola": "EY",
    "bank of america": "EY",
    "pfizer": "EY",
    "at&t": "EY",
    "att": "EY",
    "verizon": "EY",
    "oracle": "EY",
    "adobe": "EY",
    "netflix": "EY",
    "t-mobile": "EY",
    "spotify": "EY",
    "uber": "EY",
    "airbnb": "EY",

    # PwC (PricewaterhouseCoopers) clients
    "disney": "PwC",
    "nike": "PwC",
    "chevron": "PwC",
    "exxon": "PwC",
    "exxonmobil": "PwC",
    "ibm": "PwC",
    "qualcomm": "PwC",
    "caterpillar": "PwC",
    "3m": "PwC",
    "american express": "PwC",
    "amex": "PwC",
    "blackrock": "PwC",
    "costco": "PwC",
    "merck": "PwC",
    "pepsico": "PwC",
    "pepsi": "PwC",
}


def get_auditor(market_question: str) -> str | None:
    """Return the auditor for a company mentioned in a market question, or None."""
    text = market_question.lower()
    for company, auditor in COMPANY_AUDITORS.items():
        if company in text:
            return auditor
    return None


def is_earnings_market(market_question: str) -> bool:
    """Check if a market is about company earnings."""
    text = market_question.lower()
    earnings_keywords = [
        "earnings", "revenue", "eps", "quarterly", "q1", "q2", "q3", "q4",
        "beat estimates", "miss estimates", "profit", "net income",
        "report", "fiscal", "guidance",
    ]
    return any(kw in text for kw in earnings_keywords)


def analyze_wallet_auditor_pattern(wallet_trades: list) -> dict | None:
    """
    Analyze a wallet's trades for auditor-clustering pattern.

    Returns a dict with the pattern details if suspicious, or None.
    The KPMG pattern: wallet bets big on one auditor's clients, small on others.
    """
    auditor_bets = {}  # auditor -> list of (notional, market)
    non_auditor_bets = []

    for trade in wallet_trades:
        question = trade.get("market_question") or trade.get("title") or trade.get("question") or ""
        notional = float(trade.get("notional_usd") or trade.get("usdcSize") or trade.get("size") or 0)

        if not is_earnings_market(question):
            continue

        auditor = get_auditor(question)
        if auditor:
            if auditor not in auditor_bets:
                auditor_bets[auditor] = []
            auditor_bets[auditor].append({"notional": notional, "market": question[:60]})
        else:
            non_auditor_bets.append({"notional": notional, "market": question[:60]})

    if not auditor_bets:
        return None

    # Check for disproportionate betting on one auditor
    for auditor, bets in auditor_bets.items():
        auditor_avg = sum(b["notional"] for b in bets) / len(bets) if bets else 0
        other_bets = []
        for other_auditor, other in auditor_bets.items():
            if other_auditor != auditor:
                other_bets.extend(other)
        other_bets.extend(non_auditor_bets)

        other_avg = sum(b["notional"] for b in other_bets) / len(other_bets) if other_bets else 0

        # If average bet on this auditor is 3x+ larger than others, flag it
        if auditor_avg > 500 and len(bets) >= 2 and (other_avg == 0 or auditor_avg / max(other_avg, 1) >= 3):
            return {
                "auditor": auditor,
                "auditor_bets": len(bets),
                "auditor_avg_size": auditor_avg,
                "other_bets": len(other_bets),
                "other_avg_size": other_avg,
                "ratio": auditor_avg / max(other_avg, 1),
                "markets": [b["market"] for b in bets],
            }

    return None
