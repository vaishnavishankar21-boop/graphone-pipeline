"""
Scaled-up research papers collection run.

Targets 1000+ unique papers across 5 arXiv categories, with GitHub star
enrichment. Progress is checkpointed to data/papers_checkpoint.jsonl as it
goes -- if this crashes or you need to stop partway through, just run it
again and it will resume from where it left off instead of starting over.

Usage:
    python run_papers.py
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

from src.scrapers.papers import run_papers_scraper

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

CHECKPOINT_PATH = "data/papers_checkpoint.jsonl"


async def main():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("WARNING: No GITHUB_TOKEN found in .env -- this run will be slow "
              "and may hit rate limits. See README for setup.")

    os.makedirs("data", exist_ok=True)

    records = await run_papers_scraper(
        categories=["cs.AI", "cs.LG", "cs.CL", "cs.CV", "stat.ML"],
        target_per_category=250,  # 5 categories x 250 = 1250 target, comfortably over 1000 after dedup
        github_token=token,
        checkpoint_path=CHECKPOINT_PATH,
    )

    print(f"\n{'='*50}")
    print(f"Collected {len(records)} NEW papers this run")
    print(f"Full checkpoint file: {CHECKPOINT_PATH}")

    # Count total lines in checkpoint (cumulative across all runs, in case
    # this was resumed from a previous partial run)
    if os.path.exists(CHECKPOINT_PATH):
        with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            total = sum(1 for _ in f)
        print(f"Total papers in checkpoint file (all runs combined): {total}")
    print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())