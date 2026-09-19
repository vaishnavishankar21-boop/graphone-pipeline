"""
News vertical.

Sources: 5 real, verified-active RSS feeds covering AI news:
  1. TechCrunch AI       - techcrunch.com/category/artificial-intelligence/feed/
  2. VentureBeat AI      - venturebeat.com/category/ai/feed/
  3. arXiv cs.AI         - rss.arxiv.org/rss/cs.AI (new-paper announcements)
  4. Google DeepMind Blog - deepmind.google/blog/feed/basic/
  5. Hugging Face Blog   - huggingface.co/blog/feed.xml

RSS is deliberately chosen over raw HTML scraping for this vertical:
every one of these feeds provides a genuine, structured <pubDate> or
<published> field, which solves most of the "date normalization"
requirement for free -- no anti-bot fighting needed, no guessing at page
structure per-site.

Freshness: only articles published within the last 24 hours are kept.
This filtering happens at ingestion time (not applied later as a query
filter), per the architecture's freshness-as-ingestion-invariant design.

Full-text: RSS feeds typically only provide a summary/excerpt, not full
article text (publishers reserve full text for their own site, and many
paywall it). We store the summary and the article URL; a genuine
full-text fetch would require per-site scraping with real anti-bot risk
(see Phase V) which is out of scope for the free-tier RSS-first design
used here. This is stated explicitly rather than fabricating full text
that wasn't actually retrieved.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional

import aiohttp

from src.schemas.models import NewsContent, NewsRecord, Source
from src.utils.retry import PermanentError, RetryableError, parse_retry_after, with_retries

logger = logging.getLogger("graphone.scrapers.news")

NEWS_SOURCES = [
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/"},
    {"name": "arXiv cs.AI", "url": "https://rss.arxiv.org/rss/cs.AI"},
    {"name": "Google DeepMind Blog", "url": "https://deepmind.google/blog/feed/basic/"},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml"},
]

FRESHNESS_WINDOW = timedelta(hours=24)

# Handles both RSS 2.0 (<item>/<pubDate>) and Atom (<entry>/<published>)
# feed formats, since real-world feeds mix both.
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

_RELATIVE_PATTERN = re.compile(
    r"(\d+)\s*(second|minute|hour|day)s?\s*ago", re.IGNORECASE
)


def parse_flexible_date(raw: Optional[str]) -> Optional[datetime]:
    """
    Normalize a publication date from any of several formats seen in the
    wild:
      - RFC 822 (standard RSS pubDate, e.g. "Mon, 15 Sep 2026 10:00:00 GMT")
      - ISO 8601 (standard Atom <published>, e.g. "2026-09-15T10:00:00Z")
      - Relative phrases (e.g. "2 hours ago") -- some sources without a
        proper feed use these; resolved relative to now (UTC).

    Returns a timezone-aware UTC datetime, or None if the value is missing
    or unparseable (letting the caller fall back to a heuristic, per the
    "Intelligent Heuristics" requirement, rather than fabricating a date).
    """
    if not raw:
        return None
    raw = raw.strip()

    # Relative phrase, e.g. "2 hours ago"
    m = _RELATIVE_PATTERN.search(raw)
    if m:
        amount, unit = int(m.group(1)), m.group(2).lower()
        delta_kwargs = {f"{unit}s": amount}
        return datetime.now(timezone.utc) - timedelta(**delta_kwargs)

    # RFC 822 (standard for RSS pubDate)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass

    # ISO 8601 (standard for Atom <published>)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    logger.warning(f"Could not parse date: {raw!r}")
    return None


class NewsScraper:
    def __init__(self, session: aiohttp.ClientSession, max_concurrency: int = 5):
        self.session = session
        self.sem = asyncio.Semaphore(max_concurrency)

    async def fetch_feed(self, source: dict) -> List[NewsRecord]:
        """Fetch and parse one RSS/Atom feed, returning only fresh (<=24h) items."""
        async def _do_fetch():
            async with self.sem:
                async with self.session.get(source["url"], timeout=20) as resp:
                    if resp.status == 429:
                        raise RetryableError(f"{source['name']} rate limited", retry_after=parse_retry_after(resp) or 10)
                    if resp.status >= 500:
                        raise RetryableError(f"{source['name']} server error {resp.status}")
                    if resp.status != 200:
                        raise PermanentError(f"{source['name']} returned {resp.status}")
                    return await resp.text()

        try:
            xml_text = await with_retries(_do_fetch, op_name=f"news:{source['name']}", max_attempts=4)
        except (PermanentError, RetryableError) as e:
            logger.error(f"Giving up on {source['name']}: {e}")
            return []

        return self._parse_feed(xml_text, source)

    def _parse_feed(self, xml_text: str, source: dict) -> List[NewsRecord]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"Could not parse XML from {source['name']}: {e}")
            return []

        records = []
        now = datetime.now(timezone.utc)
        cutoff = now - FRESHNESS_WINDOW

        # RSS 2.0 items
        items = root.findall(".//item")
        # Atom entries (used by e.g. some blog feeds)
        items += root.findall(".//atom:entry", NS)

        skipped_stale = 0
        for item in items:
            title = self._text(item, "title", NS)
            link = self._text(item, "link", NS) or self._atom_link(item)
            summary = (
                self._text(item, "description", NS)
                or self._text(item, "summary", NS)
                or self._text(item, "content:encoded", NS)
            )
            date_raw = (
                self._text(item, "pubDate", NS)
                or self._text(item, "published", NS)
                or self._text(item, "updated", NS)
                or self._text(item, "dc:date", NS)
            )

            if not title or not link:
                continue  # no usable identity/source -- skip rather than fabricate

            published = parse_flexible_date(date_raw)
            if published is None:
                # Intelligent heuristic: no parseable date at all -- treat
                # as NOT fresh (conservative) rather than assuming it's new,
                # since we cannot verify freshness without a real timestamp.
                skipped_stale += 1
                continue
            if published < cutoff:
                skipped_stale += 1
                continue

            content = NewsContent(
                title=title.strip(),
                summary=(summary or "").strip()[:2000] or None,
                full_text=None,  # see module docstring: not fabricated, RSS doesn't provide it
                published_date=published,
                article_url=link.strip(),
            )
            records.append(NewsRecord(source=Source(name=source["name"], url=link.strip()), content=content))

        logger.info(f"{source['name']}: {len(items)} items in feed, {len(records)} within 24h "
                    f"({skipped_stale} skipped as stale/undated)")
        return records

    @staticmethod
    def _text(item, tag, ns) -> Optional[str]:
        el = item.find(tag, ns) if ":" in tag else item.find(tag)
        if el is None:
            return None
        return "".join(el.itertext()).strip() or None

    @staticmethod
    def _atom_link(item) -> Optional[str]:
        el = item.find("atom:link", NS)
        if el is not None:
            return el.attrib.get("href")
        return None

    async def collect(self) -> List[NewsRecord]:
        """Fetch all 5 sources concurrently, return combined fresh results."""
        results = await asyncio.gather(*(self.fetch_feed(s) for s in NEWS_SOURCES))
        all_records = [r for batch in results for r in batch]
        logger.info(f"Total fresh (<=24h) news articles across {len(NEWS_SOURCES)} sources: {len(all_records)}")
        return all_records


async def run_news_scraper() -> List[NewsRecord]:
    """Entry point used by the pipeline runner."""
    async with aiohttp.ClientSession() as session:
        scraper = NewsScraper(session)
        return await scraper.collect()

