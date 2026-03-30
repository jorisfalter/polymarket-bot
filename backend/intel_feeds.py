"""
Intelligence Feeds — Twitter accounts and RSS newsletters.

Fetches recent tweets from followed accounts and RSS newsletter items,
then formats them as context for the AI agent.
"""
import httpx
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from loguru import logger

from .config import settings

# Twitter accounts to follow for market intelligence
TWITTER_ACCOUNTS = [
    "unusual_whales",    # Options flow, insider trades
    "DeItaone",          # Breaking financial news
    "Fxhedgers",         # Macro, geopolitics
    "zaborado",          # Polymarket watcher
    "EventWavesPM",      # Polymarket insider analysis
    "elikiiii",          # Polymarket analytics
]

# RSS feeds for newsletters
RSS_FEEDS = [
    ("https://eventwaves.substack.com/feed", "EventWaves (Polymarket Insiders)"),
    ("https://www.axios.com/feeds/feed.rss", "Axios (Breaking News)"),
]

_twitter_client = None


def _get_twitter_reader():
    """Get a Twitter client for reading (uses bearer token)."""
    global _twitter_client
    if _twitter_client is not None:
        return _twitter_client

    if not settings.twitter_bearer_token:
        return None

    try:
        import tweepy
        _twitter_client = tweepy.Client(bearer_token=settings.twitter_bearer_token)
        logger.info("Twitter reader initialized (read-only)")
        return _twitter_client
    except Exception as e:
        logger.warning(f"Twitter reader init failed: {e}")
        return None


async def fetch_twitter_intel() -> List[Dict]:
    """Fetch recent tweets from followed accounts."""
    client = _get_twitter_reader()
    if not client:
        return []

    results = []
    for username in TWITTER_ACCOUNTS:
        try:
            user = client.get_user(username=username)
            if not user.data:
                continue

            tweets = client.get_users_tweets(
                user.data.id,
                max_results=5,
                tweet_fields=["created_at", "public_metrics"],
            )
            if not tweets.data:
                continue

            for tweet in tweets.data[:3]:
                created = tweet.created_at
                # Only tweets from last 2 hours
                if created and (datetime.utcnow() - created.replace(tzinfo=None)) > timedelta(hours=2):
                    continue

                results.append({
                    "source": f"@{username}",
                    "text": tweet.text[:300],
                    "time": created.strftime("%H:%M UTC") if created else "",
                    "likes": tweet.public_metrics.get("like_count", 0) if tweet.public_metrics else 0,
                })
        except Exception as e:
            logger.debug(f"Failed to fetch @{username}: {e}")
            continue

    return results


async def fetch_rss_intel() -> List[Dict]:
    """Fetch recent RSS items from newsletters."""
    results = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        for url, source_name in RSS_FEEDS:
            try:
                r = await client.get(url, headers={"User-Agent": "PolymarketBot/1.0"})
                if r.status_code != 200:
                    continue

                root = ET.fromstring(r.text)

                # Handle both RSS 2.0 and Atom formats
                items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")

                for item in items[:3]:
                    # RSS 2.0
                    title = item.findtext("title") or ""
                    description = item.findtext("description") or ""
                    pub_date = item.findtext("pubDate") or ""

                    # Atom fallback
                    if not title:
                        title = item.findtext("{http://www.w3.org/2005/Atom}title") or ""
                    if not description:
                        desc_el = item.find("{http://www.w3.org/2005/Atom}content") or item.find("{http://www.w3.org/2005/Atom}summary")
                        description = desc_el.text[:200] if desc_el is not None and desc_el.text else ""

                    # Strip HTML tags from description
                    import re
                    description = re.sub(r"<[^>]+>", "", description)[:200]

                    if title:
                        results.append({
                            "source": source_name,
                            "title": title[:100],
                            "summary": description[:200],
                        })
            except Exception as e:
                logger.debug(f"Failed to fetch RSS {source_name}: {e}")
                continue

    return results


async def fetch_all_intel() -> str:
    """Fetch all intel and format for the AI agent."""
    parts = []

    # Twitter
    tweets = await fetch_twitter_intel()
    if tweets:
        lines = ["## Twitter Intel (Last 2 Hours)"]
        for t in tweets[:10]:
            lines.append(f"- **{t['source']}** [{t['time']}]: {t['text'][:150]}")
        parts.append("\n".join(lines))

    # RSS
    rss_items = await fetch_rss_intel()
    if rss_items:
        lines = ["## Newsletter Intel"]
        for item in rss_items[:5]:
            lines.append(f"- **{item['source']}**: {item['title']}")
            if item.get("summary"):
                lines.append(f"  {item['summary'][:150]}")
        parts.append("\n".join(lines))

    if not parts:
        return "No external intel available this cycle."

    return "\n\n".join(parts)
