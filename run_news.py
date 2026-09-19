"""
Collects fresh (<=24h) AI news from 5 RSS sources and saves to
data/news.jsonl.

Usage:
    python run_news.py
"""

import asyncio
import os

from src.scrapers.news import run_news_scraper

OUTPUT_PATH = "data/news.jsonl"


async def main():
    os.makedirs("data", exist_ok=True)

    records = await run_news_scraper()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(r.model_dump_json() + "\n")

    print(f"\n{'='*50}")
    print(f"Collected {len(records)} fresh (<=24h) news articles")
    print(f"Written to {OUTPUT_PATH}")
    print(f"{'='*50}")

    from collections import Counter
    source_counts = Counter(r.source.name for r in records)
    print("\nArticles per source:")
    for name, count in source_counts.most_common():
        print(f"  {name}: {count}")

    print("\nSample articles:")
    for r in records[:5]:
        print(f"  [{r.source.name}] {r.content.title}")


if __name__ == "__main__":
    asyncio.run(main())

