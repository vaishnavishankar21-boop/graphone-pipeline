"""
Runs the Products extraction pipeline: reads data/startups.jsonl, uses
the LLM fallback chain to infer each startup's pricing model, and writes
data/products.jsonl.

Requires at least ONE of these API keys in your .env file (more = more
resilient fallback):
    GEMINI_API_KEY       -- https://aistudio.google.com/apikey (free tier)
    GROQ_API_KEY          -- https://console.groq.com/keys (free tier)
    OPENROUTER_API_KEY    -- https://openrouter.ai/keys (some free models)

Usage:
    python run_products.py            # process all startups
    python run_products.py --limit 20 # quick test on first 20 only
"""

import argparse
import asyncio
import logging
import os

from dotenv import load_dotenv

from src.scrapers.products import run_products_extraction

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

OUTPUT_PATH = "data/products.jsonl"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Process only first N startups (for testing)")
    args = parser.parse_args()

    keys_configured = [
        k for k in ["GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"] if os.getenv(k)
    ]
    if not keys_configured:
        print("ERROR: No LLM API keys found in .env. Set at least one of "
              "GEMINI_API_KEY, GROQ_API_KEY, or OPENROUTER_API_KEY.")
        return
    print(f"LLM tiers configured: {keys_configured}")

    os.makedirs("data", exist_ok=True)

    checkpoint_path = "data/products_checkpoint.jsonl"
    new_records = await run_products_extraction(limit=args.limit, checkpoint_path=checkpoint_path)
    print(f"\nProcessed {len(new_records)} NEW records this run")

    # The checkpoint file is the source of truth across all runs (including
    # resumed ones), so read the full file back for the final summary/output
    # rather than just this run's newly-added records.
    import json
    all_records_raw = []
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                all_records_raw.append(json.loads(line))

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for rec in all_records_raw:
            f.write(json.dumps(rec) + "\n")

    print(f"\n{'='*50}")
    print(f"Total product records (all runs combined): {len(all_records_raw)}")
    print(f"Written to {OUTPUT_PATH}")
    print(f"{'='*50}")

    from collections import Counter
    pricing_counts = Counter(rec["content"]["pricingModel"] for rec in all_records_raw)
    print("\nPricing model distribution:")
    for model, count in pricing_counts.most_common():
        print(f"  {model}: {count}")

    print("\nSample records:")
    for rec in all_records_raw[:5]:
        print(f"  {rec['content']['productName']} | {rec['content']['pricingModel']}")


if __name__ == "__main__":
    asyncio.run(main())


