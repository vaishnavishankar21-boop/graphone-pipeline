"""
Startups vertical.

Data source: https://github.com/yc-oss/api -- a community-maintained,
daily-updated, static JSON mirror of Y Combinator's own public company
directory (sourced from the Algolia search index that powers
ycombinator.com/companies). This is NOT a scrape of the YC website; it's
a free, public, pre-built JSON API, updated by a daily GitHub Actions job.

Why this source: no anti-bot fighting, no rate limits (static files
served from GitHub Pages), no auth required, and it's pre-tagged by
industry -- the "artificial-intelligence" tag alone covers 1000+ real,
named AI startups with genuine metadata (team size, funding stage,
description, website), which is exactly GraphOne's target vertical.

Every record traces back to the company's real ycombinator.com profile
URL, satisfying the "no hallucinated data" requirement.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

import aiohttp

from src.schemas.models import Source, StartupContent, StartupContentData, StartupRecord
from src.utils.retry import PermanentError, RetryableError, with_retries

logger = logging.getLogger("graphone.scrapers.startups")

YC_OSS_BASE = "https://yc-oss.github.io/api"

# AI-related tags on the YC directory. Fetching several (not just one) and
# deduping by company id gives broader, more representative AI-ecosystem
# coverage than a single tag alone.
AI_TAGS = [
    "artificial-intelligence",
    "ai",
    "machine-learning",
    "generative-ai",
    "deep-learning",
    "nlp",
    "computer-vision",
    "reinforcement-learning",
    "ai-assistant",
    "conversational-ai",
]


class StartupsScraper:
    def __init__(self, session: aiohttp.ClientSession, max_concurrency: int = 5):
        self.session = session
        self.sem = asyncio.Semaphore(max_concurrency)

    async def fetch_tag(self, tag: str) -> List[dict]:
        """Fetch the full company list for one YC tag."""
        url = f"{YC_OSS_BASE}/tags/{tag}.json"

        async def _do_fetch():
            async with self.sem:
                async with self.session.get(url, timeout=30) as resp:
                    if resp.status == 429:
                        raise RetryableError("yc-oss rate limited (unexpected for static JSON)")
                    if resp.status >= 500:
                        raise RetryableError(f"yc-oss server error {resp.status}")
                    if resp.status == 404:
                        logger.warning(f"Tag not found: {tag}")
                        return []
                    if resp.status != 200:
                        raise PermanentError(f"yc-oss returned {resp.status} for tag={tag}")
                    return await resp.json()

        try:
            return await with_retries(_do_fetch, op_name=f"yc-tag:{tag}", max_attempts=4)
        except (PermanentError, RetryableError) as e:
            logger.error(f"Giving up on tag={tag}: {e}")
            return []

    @staticmethod
    def _to_startup_record(company: dict) -> Optional[StartupRecord]:
        """Map one raw yc-oss company object to our canonical StartupRecord."""
        name = company.get("name")
        url = company.get("url")
        if not name or not url:
            # No usable identity/source URL -- skip rather than fabricate
            return None

        founded_year = None
        launched_at = company.get("launched_at")
        if launched_at:
            try:
                founded_year = datetime.fromtimestamp(launched_at, tz=timezone.utc).year
            except (ValueError, OSError, OverflowError):
                pass

        description = company.get("long_description") or company.get("one_liner")

        content = StartupContent(
            entityName=name,  # will be overwritten with canonical name by entity resolver later
            rawName=name,
            description=description,
            website=company.get("website"),
            data=StartupContentData(
                employeeCount=company.get("team_size"),
                foundedYear=founded_year,
                hq=company.get("all_locations") or None,
                industry=company.get("industry"),
            ),
        )

        return StartupRecord(
            source=Source(name="Y Combinator (via yc-oss.github.io)", url=url),
            content=content,
        )

    async def collect(self, tags: List[str] = None) -> List[StartupRecord]:
        """
        Fetch all AI-tagged companies across the given tags, dedupe by
        company id (a company can carry multiple AI-adjacent tags), and
        return canonical StartupRecords.
        """
        tags = tags or AI_TAGS
        results = await asyncio.gather(*(self.fetch_tag(t) for t in tags))

        seen_ids = set()
        records: List[StartupRecord] = []
        for tag, companies in zip(tags, results):
            new_count = 0
            for company in companies:
                cid = company.get("id")
                if cid is not None and cid in seen_ids:
                    continue
                record = self._to_startup_record(company)
                if record is None:
                    continue
                if cid is not None:
                    seen_ids.add(cid)
                records.append(record)
                new_count += 1
            logger.info(f"Tag '{tag}': {len(companies)} companies, {new_count} new after dedup")

        logger.info(f"Total unique AI startups collected: {len(records)}")
        return records


async def run_startups_scraper(tags: Optional[List[str]] = None) -> List[StartupRecord]:
    """Entry point used by the pipeline runner."""
    async with aiohttp.ClientSession() as session:
        scraper = StartupsScraper(session)
        return await scraper.collect(tags)

