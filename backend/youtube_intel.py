"""
YouTube transcript ingestion for the research agent.

Pulls recent video transcripts from a curated channel list via
youtube-transcript-api (free, no auth, no API key). Combined with the
channel's RSS feed (free, also no auth) for video discovery, this gives
us a zero-cost feed of finance/macro/crypto commentary that often surfaces
ideas before they hit equity-research notes.

Channel discovery RSS URL pattern:
    https://www.youtube.com/feeds/videos.xml?channel_id=<CHANNEL_ID>

Channel IDs are visible on the channel page source or via tools like
commentpicker.com. Keep this list small (5-10) — each channel = 1 RSS
fetch + 1 transcript fetch per new video.
"""
import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx
from loguru import logger


# (channel_id, friendly_label). Channel IDs are stable; channel handles are not.
# Two earlier IDs (Real Vision UC9Jzcw..., Wendover UC2hCmG...) 404'd on RSS —
# possibly renamed. Drop them; add back when verified via youtube.com/feeds/videos.xml.
CHANNELS = [
    ("UCASM0XgcQk5SkbMtb1jQQVw", "Patrick Boyle"),       # macro + market structure
    ("UCUMZ7gohGI9HcU9VNsr2FJQ", "Bloomberg Odd Lots"),  # macro / commodities
    ("UCV0qA-eDDICsRR9rPcnG7tw", "Joseph Wang"),         # ex-Fed plumbing
    ("UCb1emEjPgZ_NA4ZX_qZJqxg", "Bankless HQ"),         # crypto / DeFi
    ("UCFp1vaKzpfvoGai0vE5VJ0w", "Coin Bureau"),         # crypto majors
    ("UCp0hYYBW6IMayGgR-WeoCvQ", "TLDR News"),           # geopolitics signal
]


def _atom_text(item: ET.Element, tag: str) -> str:
    el = item.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
    return el.text or "" if el is not None else ""


async def _fetch_channel_videos(channel_id: str, since_hours: int = 48) -> List[Dict]:
    """Read a channel's public XML feed and return videos newer than cutoff."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
        root = ET.fromstring(r.text)
        videos: List[Dict] = []
        for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
            video_id = ""
            id_el = entry.find("{http://www.youtube.com/xml/schemas/2015}videoId")
            if id_el is not None and id_el.text:
                video_id = id_el.text
            published_str = _atom_text(entry, "published")
            try:
                published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            except Exception:
                published = datetime.now(timezone.utc)
            if published < cutoff:
                continue
            videos.append({
                "video_id": video_id,
                "title": _atom_text(entry, "title"),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published_at": published.isoformat(),
            })
        return videos
    except Exception as e:
        logger.debug(f"YouTube feed fetch failed for {channel_id}: {e}")
        return []


def _fetch_transcript_sync(video_id: str) -> Optional[str]:
    """Blocking call — used inside asyncio.to_thread.

    youtube-transcript-api v1.x switched from static
    `YouTubeTranscriptApi.get_transcript(video_id)` to instance
    `YouTubeTranscriptApi().fetch(video_id)`. We support both so we
    don't break if requirements.txt pins differ between dev and prod."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        parts = None
        # New API (v1.x)
        if hasattr(YouTubeTranscriptApi, "fetch") and not hasattr(YouTubeTranscriptApi, "get_transcript"):
            inst = YouTubeTranscriptApi()
            fetched = inst.fetch(video_id, languages=["en", "en-US"])
            # fetched is a FetchedTranscript with .snippets list, each .text
            parts = [{"text": s.text} for s in fetched.snippets]
        else:
            # Legacy API (v0.x) — static method returning list of dicts
            parts = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US"])
        if not parts:
            return None
        text = " ".join(p.get("text", "") for p in parts)
        return text[:25000]
    except Exception as e:
        logger.debug(f"Transcript fetch failed for {video_id}: {e}")
        return None


async def fetch_youtube_intel(since_hours: int = 48, max_videos_per_channel: int = 2) -> List[Dict]:
    """Top-level: discover videos per channel + grab transcripts.

    Returns flat list of {source, title, body, url, ts} matching the shape
    that intel_feeds / reddit_data emit so research_agent can merge them.
    """
    out: List[Dict] = []
    # Discover videos in parallel
    discovery = await asyncio.gather(
        *(_fetch_channel_videos(cid, since_hours) for cid, _ in CHANNELS),
        return_exceptions=True,
    )

    fetch_jobs: List = []  # (channel_label, video_dict) for transcript fetch
    for (cid, label), videos in zip(CHANNELS, discovery):
        if isinstance(videos, Exception) or not videos:
            continue
        # Most recent first, cap per channel
        for v in videos[:max_videos_per_channel]:
            fetch_jobs.append((label, v))

    # Fetch transcripts in parallel (blocking lib → to_thread)
    async def _one(label: str, video: Dict) -> Optional[Dict]:
        text = await asyncio.to_thread(_fetch_transcript_sync, video["video_id"])
        if not text or len(text) < 200:  # skip if auto-captions absent
            return None
        return {
            "source": f"YouTube: {label}",
            "title": video["title"],
            "body": text,
            "url": video["url"],
            "ts": video["published_at"],
        }

    transcripts = await asyncio.gather(
        *(_one(label, v) for label, v in fetch_jobs),
        return_exceptions=True,
    )
    for t in transcripts:
        if t and not isinstance(t, Exception):
            out.append(t)

    return out
