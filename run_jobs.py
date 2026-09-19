"""
Collects fresh (<=24h) AI-related jobs from 3 job board sources
(RemoteOK, WeWorkRemotely, Arbeitnow) and saves to data/jobs.jsonl.

Usage:
    python run_jobs.py
"""

import asyncio
import logging
import os

from src.scrapers.jobs import run_jobs_scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

OUTPUT_PATH = "data/jobs.jsonl"


async def main():
    os.makedirs("data", exist_ok=True)

    records = await run_jobs_scraper()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(r.model_dump_json() + "\n")

    print(f"\n{'='*50}")
    print(f"Collected {len(records)} fresh (<=24h) AI-related jobs")
    print(f"Written to {OUTPUT_PATH}")
    print(f"{'='*50}")

    from collections import Counter
    source_counts = Counter(r.source.name for r in records)
    print("\nJobs per source:")
    for name, count in source_counts.most_common():
        print(f"  {name}: {count}")

    print("\nSample jobs:")
    for r in records[:5]:
        print(f"  [{r.source.name}] {r.content.title} @ {r.content.company}")


if __name__ == "__main__":
    asyncio.run(main())