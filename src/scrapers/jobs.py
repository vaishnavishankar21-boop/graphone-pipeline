"""
Jobs vertical.

Sources: 3 real, verified-active, free, no-auth job board sources:
  1. RemoteOK       - remoteok.com/api (JSON, native epoch timestamps)
  2. WeWorkRemotely - weworkremotely.com/categories/remote-programming-jobs.rss (RSS)
  3. Arbeitnow      - arbeitnow.com/api/job-board-api (JSON, EU/remote focus)

All three provide genuine posting dates natively (no scraping of raw HTML
job pages, no anti-bot fighting for this vertical), which is what makes
this the right approach for the "24-hour freshness" requirement: dates
come from the source's own structured data, not guessed at.

AI filtering: none of these APIs let you filter by "AI" server-side, so
each job's title/description/tags are checked client-side against a
keyword list. This is a simple, explainable filter -- not a hallucinated
classification -- and every kept job still traces to its real posting.

Architecture note: this is 3 of the assignment's target 5 job boards.
Two more (e.g. Remotive, Jobicy) were identified during research but
their exact API shape wasn't independently verified against a live
response in this project, so they were left out rather than risk
shipping an untested/guessed integration. Adding a 4th or 5th source
follows the exact same pattern as the three below (see architecture.pdf,
Section 1) -- it is an infrastructure/config addition, not a code
rewrite.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Optional

import aiohttp

from src.schemas.models import JobContent, JobRecord, Source
from src.utils.dates import is_within_last_24h, parse_flexible_date
from src.utils.retry import PermanentError, RetryableError, parse_retry_after, with_retries

logger = logging.getLogger("graphone.scrapers.jobs")

AI_KEYWORDS = (
    "artificial intelligence", "machine learning", " ai ", " ai,", " ai/",
    "ai engineer", "ai researcher", "ml engineer", "deep learning",
    "nlp", "llm", "generative ai", "computer vision", "data scientist",
)

NS = {"atom": "http://www.w3.org/2005/Atom"}


def _matches_ai_keywords(*texts: Optional[str]) -> bool:
    """
    Matches against title and tags ONLY -- deliberately excludes freeform
    description text. Description-based matching was tested and found to
    produce false positives (e.g. a "Channel Partner Manager" role
    matched because its description happened to mention "AI-powered
    tools" in passing). Title and tags are curated/structured signals of
    what the role actually IS; a long description is noisy free text
    where an incidental "AI" mention doesn't mean the role is AI-focused.
    """
    haystack = " ".join(t.lower() for t in texts if t)
    haystack = f" {haystack} "  # padding so " ai " boundary-matches work at string edges
    return any(kw in haystack for kw in AI_KEYWORDS)


class JobsScraper:
    def __init__(self, session: aiohttp.ClientSession, max_concurrency: int = 3):
        self.session = session
        self.sem = asyncio.Semaphore(max_concurrency)

    # ---------------------------------------------------------------- RemoteOK

    async def fetch_remoteok(self) -> List[JobRecord]:
        url = "https://remoteok.com/api"

        async def _do_fetch():
            async with self.sem:
                headers = {"User-Agent": "Mozilla/5.0 (compatible; GraphOneBot/1.0)"}
                async with self.session.get(url, headers=headers, timeout=20) as resp:
                    if resp.status == 429:
                        raise RetryableError("RemoteOK rate limited", retry_after=parse_retry_after(resp) or 10)
                    if resp.status >= 500:
                        raise RetryableError(f"RemoteOK server error {resp.status}")
                    if resp.status != 200:
                        raise PermanentError(f"RemoteOK returned {resp.status}")
                    return await resp.json(content_type=None)

        try:
            data = await with_retries(_do_fetch, op_name="jobs:RemoteOK", max_attempts=4)
        except (PermanentError, RetryableError) as e:
            logger.error(f"Giving up on RemoteOK: {e}")
            return []

        if not isinstance(data, list):
            return []

        records = []
        for item in data:
            if not isinstance(item, dict) or "id" not in item:
                continue  # first element is often a legal/metadata notice, not a job
            title = item.get("position") or item.get("title")
            company = item.get("company")
            url_ = item.get("url")
            if not title or not company or not url_:
                continue

            description = item.get("description", "")
            tags = " ".join(item.get("tags", []) or [])
            if not _matches_ai_keywords(title, tags):
                continue

            published = parse_flexible_date(item.get("date") or item.get("epoch"))
            if not is_within_last_24h(published):
                continue

            records.append(JobRecord(
                source=Source(name="RemoteOK", url=url_),
                content=JobContent(
                    title=title,
                    company=company,
                    date=published,
                    is_remote=True,  # RemoteOK is remote-only by definition
                    role_family="Engineering",
                    location=item.get("location") or "Remote",
                    job_url=url_,
                    description=(description or "")[:2000] or None,
                ),
            ))
        logger.info(f"RemoteOK: {len(data)} total listings, {len(records)} AI-related within 24h")
        return records

    # ----------------------------------------------------------- WeWorkRemotely

    async def fetch_wwr(self) -> List[JobRecord]:
        url = "https://weworkremotely.com/categories/remote-programming-jobs.rss"

        async def _do_fetch():
            async with self.sem:
                async with self.session.get(url, timeout=20) as resp:
                    if resp.status == 429:
                        raise RetryableError("WeWorkRemotely rate limited", retry_after=parse_retry_after(resp) or 10)
                    if resp.status >= 500:
                        raise RetryableError(f"WeWorkRemotely server error {resp.status}")
                    if resp.status != 200:
                        raise PermanentError(f"WeWorkRemotely returned {resp.status}")
                    return await resp.text()

        try:
            xml_text = await with_retries(_do_fetch, op_name="jobs:WeWorkRemotely", max_attempts=4)
        except (PermanentError, RetryableError) as e:
            logger.error(f"Giving up on WeWorkRemotely: {e}")
            return []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"Could not parse WeWorkRemotely RSS: {e}")
            return []

        items = root.findall(".//item")
        records = []
        for item in items:
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            date_el = item.find("pubDate")

            raw_title = title_el.text if title_el is not None else None
            link = link_el.text if link_el is not None else None
            description = "".join(desc_el.itertext()) if desc_el is not None else ""
            date_raw = date_el.text if date_el is not None else None

            if not raw_title or not link:
                continue

            # WWR titles are formatted "Company: Job Title"
            if ":" in raw_title:
                company, title = raw_title.split(":", 1)
                company, title = company.strip(), title.strip()
            else:
                company, title = "Unknown", raw_title.strip()

            if not _matches_ai_keywords(title):
                continue

            published = parse_flexible_date(date_raw)
            if not is_within_last_24h(published):
                continue

            records.append(JobRecord(
                source=Source(name="WeWorkRemotely", url=link),
                content=JobContent(
                    title=title,
                    company=company,
                    date=published,
                    is_remote=True,
                    role_family="Engineering",
                    location="Remote",
                    job_url=link,
                    description=re.sub(r"<[^>]+>", "", description)[:2000] or None,
                ),
            ))
        logger.info(f"WeWorkRemotely: {len(items)} total listings, {len(records)} AI-related within 24h")
        return records

    # ---------------------------------------------------------------- Arbeitnow

    async def fetch_arbeitnow(self) -> List[JobRecord]:
        url = "https://www.arbeitnow.com/api/job-board-api"

        async def _do_fetch():
            async with self.sem:
                async with self.session.get(url, timeout=20) as resp:
                    if resp.status == 429:
                        raise RetryableError("Arbeitnow rate limited", retry_after=parse_retry_after(resp) or 10)
                    if resp.status >= 500:
                        raise RetryableError(f"Arbeitnow server error {resp.status}")
                    if resp.status != 200:
                        raise PermanentError(f"Arbeitnow returned {resp.status}")
                    return await resp.json()

        try:
            data = await with_retries(_do_fetch, op_name="jobs:Arbeitnow", max_attempts=4)
        except (PermanentError, RetryableError) as e:
            logger.error(f"Giving up on Arbeitnow: {e}")
            return []

        jobs = data.get("data", []) if isinstance(data, dict) else []
        records = []
        for item in jobs:
            title = item.get("title")
            company = item.get("company_name")
            url_ = item.get("url")
            if not title or not company or not url_:
                continue

            description = item.get("description", "")
            tags = " ".join(item.get("tags", []) or [])
            if not _matches_ai_keywords(title, tags):
                continue

            published = parse_flexible_date(item.get("created_at"))
            if not is_within_last_24h(published):
                continue

            records.append(JobRecord(
                source=Source(name="Arbeitnow", url=url_),
                content=JobContent(
                    title=title,
                    company=company,
                    date=published,
                    is_remote=bool(item.get("remote")),
                    role_family="Engineering",
                    location=item.get("location") or "Not specified",
                    job_url=url_,
                    description=(description or "")[:2000] or None,
                ),
            ))
        logger.info(f"Arbeitnow: {len(jobs)} total listings, {len(records)} AI-related within 24h")
        return records

    async def collect(self) -> List[JobRecord]:
        results = await asyncio.gather(
            self.fetch_remoteok(), self.fetch_wwr(), self.fetch_arbeitnow()
        )
        all_records = [r for batch in results for r in batch]
        logger.info(f"Total fresh (<=24h) AI jobs across 3 sources: {len(all_records)}")
        return all_records


async def run_jobs_scraper() -> List[JobRecord]:
    """Entry point used by the pipeline runner."""
    async with aiohttp.ClientSession() as session:
        scraper = JobsScraper(session)
        return await scraper.collect()