"""
Collects AI startups from Y Combinator's public directory (via the
yc-oss.github.io mirror) and saves them to data/startups.jsonl.

This is fast -- it's just a handful of static JSON file fetches, no
pagination, no rate-limit pacing needed. Should complete in seconds.

Usage:
    python run_startups.py
"""

import asyncio
import json
import os

from src.scrapers.startups import run_startups_scraper

OUTPUT_PATH = "data/startups.jsonl"


async def main():
    os.makedirs("data", exist_ok=True)

    records = await run_startups_scraper()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(r.model_dump_json() + "\n")

    print(f"\n{'='*50}")
    print(f"Collected {len(records)} unique AI startups")
    print(f"Written to {OUTPUT_PATH}")
    print(f"{'='*50}")

    # quick sample
    print("\nSample records:")
    for r in records[:5]:
        print(f"  {r.content.entityName} | employees={r.content.data.employeeCount} "
              f"| founded={r.content.data.foundedYear} | {r.source.url}")


if __name__ == "__main__":
    asyncio.run(main())

