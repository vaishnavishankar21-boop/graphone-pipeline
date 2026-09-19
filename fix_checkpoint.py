"""
Repairs the existing papers_checkpoint.jsonl in place.

Background: the original GitHub-matching logic sometimes matched a paper
to a "daily arxiv digest" / "awesome list" repo (one that references
hundreds of unrelated papers in its README) instead of an actual paper
implementation. This script:

  1. Scans the checkpoint file for records whose github_url matches known
     aggregator patterns.
  2. Clears the bad github_url/github_stars on those records.
  3. Re-runs the (now-fixed, filtered) GitHub search for every record that
     has no github_url at all -- both the newly-cleared ones and any that
     legitimately never had a match -- to give them a fair second chance
     with the corrected matching logic.
  4. Writes the fully repaired file back out.

Run this once after replacing src/scrapers/papers.py with the fixed
version:
    python fix_checkpoint.py
"""

import asyncio
import json
import os
import shutil

import aiohttp
from dotenv import load_dotenv

from src.scrapers.papers import PapersScraper
from src.schemas.models import ResearchPaperContent

load_dotenv()

CHECKPOINT_PATH = "data/papers_checkpoint.jsonl"
BACKUP_PATH = "data/papers_checkpoint.backup.jsonl"


async def main():
    if not os.path.exists(CHECKPOINT_PATH):
        print(f"No checkpoint file found at {CHECKPOINT_PATH}")
        return

    shutil.copy(CHECKPOINT_PATH, BACKUP_PATH)
    print(f"Backed up original to {BACKUP_PATH}")

    records = []
    with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"Loaded {len(records)} records")

    token = os.getenv("GITHUB_TOKEN")
    async with aiohttp.ClientSession() as session:
        scraper = PapersScraper(session, github_token=token)

        cleared = 0
        to_recheck = []
        for rec in records:
            content = rec["content"]
            url = content.get("github_url")
            if url and scraper._is_aggregator_repo({"full_name": url, "description": ""}):
                content["github_url"] = None
                content["github_stars"] = None
                cleared += 1
            if not content.get("github_url"):
                to_recheck.append(rec)

        print(f"Cleared {cleared} bad aggregator matches")
        print(f"Re-checking {len(to_recheck)} papers with corrected matching logic...")
        print("(this will take a while -- paced to respect GitHub's rate limits)")

        for i, rec in enumerate(to_recheck):
            content = rec["content"]
            arxiv_id = content.get("arxiv_id")
            if not arxiv_id:
                continue
            repo_url = await scraper.find_github_repo(arxiv_id)
            if repo_url:
                content["github_url"] = repo_url
                content["github_stars"] = await scraper.get_github_stars(repo_url)
            if (i + 1) % 25 == 0:
                print(f"  ...{i + 1}/{len(to_recheck)} re-checked")

    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    print(f"\nDone. Repaired file written to {CHECKPOINT_PATH}")
    print(f"Original backup kept at {BACKUP_PATH}")


if __name__ == "__main__":
    asyncio.run(main())

