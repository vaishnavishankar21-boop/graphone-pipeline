import asyncio
from src.scrapers.papers import run_papers_scraper

async def main():
    records = await run_papers_scraper(
        categories=["cs.AI"],
        target_per_category=20,
        github_token=None,
    )
    print(f"Collected {len(records)} papers")
    for r in records[:3]:
        print(r.content.title, "|", r.content.github_stars)

asyncio.run(main())