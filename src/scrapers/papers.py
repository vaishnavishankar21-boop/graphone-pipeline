"""
Research Papers vertical.

Pipeline:
  1. Pull paper metadata from the arXiv API (official, free, no auth, no
     anti-bot issues) -- this is our primary source of truth for title,
     authors, abstract, published date, and paper_url. Every field here
     traces back to a real arXiv record, so there is zero hallucination
     risk at this stage.
  2. Cross-reference each paper against the GitHub Search API to find an
     associated code implementation (searching for the arXiv ID in repo
     READMEs/descriptions). NOTE: this project originally targeted the
     Papers with Code API for this step, but PWC was sunset by Meta in
     July 2025 and paperswithcode.com now redirects to Hugging Face's
     "Trending Papers" page instead of serving its old API -- confirmed
     via live testing (paperswithcode.com/api/v1/search/ returns an HTML
     redirect, not JSON). GitHub Search is used as the replacement source
     of truth for paper->code linkage.
  3. Enrich with live GitHub star counts via the GitHub REST API.

All APIs used here are free, documented, and don't require scraping/
rendering, which is why this vertical is the fastest to get to real scale.

Concurrency: bounded by an asyncio.Semaphore so we can safely fan out
thousands of requests without tripping rate limits or overwhelming the
event loop -- this is the same pattern used in the startup/product
scrapers (Playwright-based) later in src/scrapers/.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional

import aiohttp

from src.schemas.models import ResearchPaperContent, ResearchPaperRecord, Source
from src.utils.retry import PermanentError, RetryableError, parse_retry_after, with_retries

logger = logging.getLogger("graphone.scrapers.papers")

ARXIV_API = "http://export.arxiv.org/api/query"
GITHUB_API = "https://api.github.com/repos"
GITHUB_SEARCH_API = "https://api.github.com/search/repositories"

ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class PapersScraper:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        max_concurrency: int = 8,
        github_token: Optional[str] = None,
    ):
        self.session = session
        self.sem = asyncio.Semaphore(max_concurrency)
        # Unauthenticated GitHub API is limited to 60 req/hr; a token bumps
        # this to 5000/hr. Strongly recommended for any real run.
        self.github_headers = {"Authorization": f"token {github_token}"} if github_token else {}
        # GitHub SEARCH API has its own, much stricter limit: 10 req/min
        # unauthenticated, 30 req/min with a token. A single semaphore slot
        # plus an explicit sleep after every search call keeps us under it
        # regardless of how many papers are being enriched concurrently.
        self.search_sem = asyncio.Semaphore(1)
        self._search_delay = 2.5 if github_token else 6.5

    # ---------------------------------------------------------------- arXiv

    async def fetch_arxiv_batch(
        self, category: str = "cs.AI", start: int = 0, max_results: int = 100
    ) -> List[ResearchPaperContent]:
        """Fetch one page of arXiv results for a category, newest first."""
        params = {
            "search_query": f"cat:{category}",
            "start": start,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        async def _do_fetch():
            async with self.session.get(ARXIV_API, params=params, timeout=30) as resp:
                if resp.status == 429:
                    raise RetryableError("arXiv rate limited", retry_after=parse_retry_after(resp) or 10)
                if resp.status >= 500:
                    raise RetryableError(f"arXiv server error {resp.status}")
                if resp.status != 200:
                    raise PermanentError(f"arXiv returned {resp.status}")
                return await resp.text()

        xml_text = await with_retries(_do_fetch, op_name=f"arxiv:{category}:{start}")
        return self._parse_arxiv_feed(xml_text)

    @staticmethod
    def _parse_arxiv_feed(xml_text: str) -> List[ResearchPaperContent]:
        root = ET.fromstring(xml_text)
        papers = []
        for entry in root.findall("atom:entry", ARXIV_NS):
            arxiv_id_full = entry.findtext("atom:id", default="", namespaces=ARXIV_NS)
            arxiv_id = arxiv_id_full.rsplit("/", 1)[-1] if arxiv_id_full else None
            title_raw = entry.findtext("atom:title", default="", namespaces=ARXIV_NS) or ""
            title = re.sub(r"\s+", " ", title_raw).strip()
            summary_raw = entry.findtext("atom:summary", default="", namespaces=ARXIV_NS) or ""
            summary = re.sub(r"\s+", " ", summary_raw).strip()
            published_raw = entry.findtext("atom:published", default="", namespaces=ARXIV_NS)
            published_date = None
            if published_raw:
                try:
                    published_date = datetime.strptime(published_raw, "%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    logger.warning(f"Could not parse arXiv date: {published_raw}")

            authors = [
                a.findtext("atom:name", default="", namespaces=ARXIV_NS)
                for a in entry.findall("atom:author", ARXIV_NS)
            ]
            categories = [
                c.attrib.get("term", "")
                for c in entry.findall("atom:category", ARXIV_NS)
            ]

            paper_url = arxiv_id_full or ""
            if not arxiv_id or not title or not paper_url:
                # Skip malformed entries rather than emit partial/fabricated data
                continue

            papers.append(
                ResearchPaperContent(
                    title=title,
                    authors=[a for a in authors if a],
                    abstract=summary or None,
                    paper_url=paper_url,
                    published_date=published_date,
                    arxiv_id=arxiv_id,
                    categories=[c for c in categories if c],
                )
            )
        return papers

    async def fetch_arxiv_many(
        self, category: str = "cs.AI", total: int = 1000, page_size: int = 100
    ) -> List[ResearchPaperContent]:
        """Paginate through arXiv until `total` papers collected."""
        results: List[ResearchPaperContent] = []
        start = 0
        while len(results) < total:
            async with self.sem:
                batch = await self.fetch_arxiv_batch(category, start=start, max_results=page_size)
            if not batch:
                logger.info(f"arXiv exhausted for category={category} at start={start}")
                break
            results.extend(batch)
            start += page_size
            # arXiv asks for >=3s between requests as courtesy rate limiting
            await asyncio.sleep(3)
        return results[:total]

    # -------------------------------------------------------------- GitHub search

    async def find_github_repo(self, arxiv_id: str) -> Optional[str]:
        """
        Search GitHub for a repository that references this arXiv ID
        (most paper implementations mention the arXiv ID in their README
        or description). Returns the best-match repo URL, or None.

        Strips the version suffix (e.g. "2401.12345v1" -> "2401.12345")
        since repos usually cite the bare ID, and picks the highest-starred
        match to avoid grabbing an unrelated fork or mention.
        """
        bare_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
        params = {
            "q": f'"{bare_id}" in:readme,description',
            "sort": "stars",
            "order": "desc",
            "per_page": 8,  # fetch a few candidates so we can skip aggregator repos
        }

        async def _do_fetch():
            async with self.session.get(
                GITHUB_SEARCH_API, params=params, headers=self.github_headers, timeout=20
            ) as resp:
                if resp.status == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                    reset = resp.headers.get("X-RateLimit-Reset")
                    delay = 30
                    if reset:
                        try:
                            delay = max(1, int(reset) - int(datetime.utcnow().timestamp()))
                        except ValueError:
                            pass
                    raise RetryableError("GitHub search rate limited", retry_after=min(delay, 60))
                if resp.status == 422:
                    # malformed query (e.g. odd characters in id) -- not retryable
                    return None
                if resp.status >= 500:
                    raise RetryableError(f"GitHub search server error {resp.status}")
                if resp.status != 200:
                    raise PermanentError(f"GitHub search returned {resp.status}")
                return await resp.json()

        async with self.search_sem:
            try:
                data = await with_retries(_do_fetch, op_name=f"ghsearch:{arxiv_id}", max_attempts=3)
            except (PermanentError, RetryableError):
                return None
            finally:
                # paced regardless of success/failure so we never burst past
                # GitHub's search rate limit even under errors/retries
                await asyncio.sleep(self._search_delay)

        if not data:
            return None

        items = data.get("items", [])
        for item in items:
            repo_url = item.get("html_url", "")
            if self._is_aggregator_repo(item):
                logger.debug(f"Skipping likely aggregator repo for {arxiv_id}: {repo_url}")
                continue
            return repo_url
        return None

    # Repos matching these patterns are near-certainly "daily arxiv digest"
    # or "awesome list" repos that reference thousands of unrelated arXiv
    # IDs in their README, rather than being an actual paper implementation.
    # Confirmed empirically: unfiltered matching produced repos like
    # "awesome-daily-AI-arxiv" matched to 148 different papers in one run.
    _AGGREGATOR_KEYWORDS = (
        "arxiv-daily", "daily-arxiv", "arxiv_daily", "daily_arxiv",
        "awesome-daily", "arxiv-radar", "arxiv-sub", "arxivsub", "hfpaper",
        "paper-daily", "papers-daily", "arxiv-digest", "daily-paper",
        "-daily", "_daily", "awesome-", "awesome_", "-papers", "_papers",
        "paper-list", "papers-list", "reading-list", "-resources",
        "_resources", "curated-list", "paper-collection",
    )

    @classmethod
    def _is_aggregator_repo(cls, item: dict) -> bool:
        name = (item.get("full_name") or "").lower()
        description = (item.get("description") or "").lower()
        haystack = f"{name} {description}"
        return any(kw in haystack for kw in cls._AGGREGATOR_KEYWORDS)

    # ------------------------------------------------------------------ GitHub

    async def get_github_stars(self, repo_url: str) -> Optional[int]:
        """Given a github.com/{owner}/{repo} URL, fetch live star count."""
        try:
            parts = repo_url.rstrip("/").split("github.com/")[-1].split("/")
            owner, repo = parts[0], parts[1]
        except (IndexError, ValueError):
            return None

        api_url = f"{GITHUB_API}/{owner}/{repo}"

        async def _do_fetch():
            async with self.session.get(api_url, headers=self.github_headers, timeout=15) as resp:
                if resp.status == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                    reset = resp.headers.get("X-RateLimit-Reset")
                    delay = 30
                    if reset:
                        try:
                            delay = max(1, int(reset) - int(datetime.utcnow().timestamp()))
                        except ValueError:
                            pass
                    raise RetryableError("GitHub rate limited", retry_after=min(delay, 60))
                if resp.status == 404:
                    return None
                if resp.status >= 500:
                    raise RetryableError(f"GitHub server error {resp.status}")
                if resp.status != 200:
                    raise PermanentError(f"GitHub returned {resp.status}")
                return await resp.json()

        try:
            data = await with_retries(_do_fetch, op_name=f"github:{owner}/{repo}", max_attempts=4)
        except (PermanentError, RetryableError):
            return None

        if not data:
            return None
        return data.get("stargazers_count")

    # -------------------------------------------------------------- pipeline

    async def enrich_paper(self, paper: ResearchPaperContent) -> ResearchPaperContent:
        """Attach GitHub repo + star count to a paper, if one exists."""
        async with self.sem:
            repo_url = await self.find_github_repo(paper.arxiv_id) if paper.arxiv_id else None
        if repo_url:
            paper.github_url = repo_url
            async with self.sem:
                paper.github_stars = await self.get_github_stars(repo_url)
        return paper

    async def collect(
        self,
        categories: List[str],
        target_per_category: int = 350,
        checkpoint_path: Optional[str] = None,
    ) -> List[ResearchPaperRecord]:
        """
        Full collection run: fetch papers across categories, dedupe (a paper
        can legitimately appear under multiple arXiv categories), enrich
        with GitHub metrics, and wrap in the canonical ResearchPaperRecord
        schema.

        If `checkpoint_path` is given, records are appended to that file
        (one JSON object per line -- JSONL) as each category finishes, and
        any arxiv_ids already present in that file on startup are skipped.
        This means a crash or interruption partway through a long run never
        loses progress: just re-run with the same checkpoint_path.
        """
        import json
        import os

        seen_ids: set = set()
        if checkpoint_path and os.path.exists(checkpoint_path):
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        aid = rec.get("content", {}).get("arxiv_id")
                        if aid:
                            seen_ids.add(aid)
                    except json.JSONDecodeError:
                        continue
            logger.info(f"Resuming from checkpoint: {len(seen_ids)} papers already collected")

        all_records: List[ResearchPaperRecord] = []

        for cat in categories:
            logger.info(f"Fetching arXiv category={cat}, target={target_per_category}")
            papers = await self.fetch_arxiv_many(cat, total=target_per_category)

            # dedupe against both this run's already-seen ids AND checkpoint
            fresh = [p for p in papers if p.arxiv_id not in seen_ids]
            skipped = len(papers) - len(fresh)
            if skipped:
                logger.info(f"Skipping {skipped} already-collected duplicates in {cat}")

            if not fresh:
                continue

            logger.info(f"Enriching {len(fresh)} new papers from {cat} with GitHub metrics...")
            enriched = await asyncio.gather(*(self.enrich_paper(p) for p in fresh))

            batch_records = [
                ResearchPaperRecord(source=Source(name="arXiv", url=p.paper_url), content=p)
                for p in enriched
            ]

            for p in fresh:
                seen_ids.add(p.arxiv_id)
            all_records.extend(batch_records)

            if checkpoint_path:
                with open(checkpoint_path, "a", encoding="utf-8") as f:
                    for r in batch_records:
                        f.write(r.model_dump_json() + "\n")
                logger.info(f"Checkpoint saved: {len(batch_records)} records from {cat} written to {checkpoint_path}")

        return all_records


async def run_papers_scraper(
    categories: Optional[List[str]] = None,
    target_per_category: int = 350,
    github_token: Optional[str] = None,
    checkpoint_path: Optional[str] = None,
) -> List[ResearchPaperRecord]:
    """Entry point used by the pipeline runner (src/main.py)."""
    categories = categories or ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "stat.ML"]
    async with aiohttp.ClientSession() as session:
        scraper = PapersScraper(session, github_token=github_token)
        return await scraper.collect(
            categories, target_per_category=target_per_category, checkpoint_path=checkpoint_path
        )