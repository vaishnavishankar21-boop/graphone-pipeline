"""
Products vertical.

Approach: each YC startup's primary offering IS its product (this is
standard for early-stage companies -- one company, one flagship
product). Rather than a separate scrape, we derive Product records from
the already-collected startups.jsonl, and use the LLM fallback chain
(src/llm/orchestrator.py) to infer the one genuinely-missing field the
source data doesn't provide: pricingModel (FREE / FREEMIUM / PAID /
ENTERPRISE).

This is a real LLM extraction task, not decoration: the raw YC data has
no pricing field at all, so classifying it from the company's own
description text is exactly the kind of unstructured-to-structured
extraction Phase III calls for, and it exercises the full fallback
chain, retry/backoff, and chunking logic on genuine data.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

import aiohttp

from src.llm.orchestrator import AllProvidersExhaustedError, LLMOrchestrator
from src.schemas.models import PricingModel, ProductContent, ProductRecord, Source

logger = logging.getLogger("graphone.scrapers.products")

SYSTEM_PROMPT = """You are a data extraction assistant. Given a startup's \
name and description, classify its pricing model by reasoning about its \
business model -- not just by looking for literal pricing words. Respond \
with ONLY a JSON object, no other text, in exactly this format:
{"pricingModel": "FREE" | "FREEMIUM" | "PAID" | "ENTERPRISE" | "UNKNOWN"}

Guidance (infer from business model context, not just exact keyword matches):
- ENTERPRISE: sells to businesses/organizations as customers (B2B), even if
  the word "enterprise" never appears -- e.g. "used by law firms", "customers
  include $10B retailers", "REST API for businesses to integrate", "adopted
  across the legal market" all indicate ENTERPRISE.
- FREEMIUM: explicitly mentions both a free tier AND a paid upgrade/premium tier
- FREE: explicitly described as free with no paid tier mentioned anywhere
- PAID: sells directly to individual consumers for a fee, with no free tier
  mentioned (e.g. a paid consumer app or subscription)
- UNKNOWN: use this ONLY if the description gives no indication at all of who
  the customer is or how the company makes money (e.g. a one-line description
  with no business model context whatsoever)

Most B2B-sounding companies (mentions of "businesses", "clients", "law firms",
"retailers", "enterprises", "API for developers/companies", or a professional/
technical customer base) should be classified ENTERPRISE even without the word
"enterprise" appearing literally. Reserve UNKNOWN for genuinely uninformative
descriptions, not just ones lacking an explicit pricing keyword.
"""


def _build_user_prompt(name: str, description: Optional[str]) -> str:
    desc = description or "(no description available)"
    return f"Startup name: {name}\nDescription: {desc}"


async def extract_pricing_model(
    orchestrator: LLMOrchestrator, name: str, description: Optional[str]
) -> PricingModel:
    """Classify one startup's pricing model via the LLM fallback chain."""
    user_prompt = _build_user_prompt(name, description)
    try:
        result = await orchestrator.extract_json(SYSTEM_PROMPT, user_prompt)
        raw_value = str(result.get("pricingModel", "UNKNOWN")).upper()
        if raw_value in PricingModel.__members__:
            return PricingModel[raw_value]
        return PricingModel.UNKNOWN
    except AllProvidersExhaustedError as e:
        logger.warning(f"LLM extraction failed for '{name}', defaulting to UNKNOWN: {e}")
        return PricingModel.UNKNOWN


async def build_product_record(orchestrator: LLMOrchestrator, startup_record: dict) -> ProductRecord:
    """Convert one startup record into a Product record with LLM-inferred pricing."""
    content = startup_record["content"]
    name = content["entityName"]
    description = content.get("description")

    pricing = await extract_pricing_model(orchestrator, name, description)

    product_content = ProductContent(
        startupName=name,
        rawStartupName=content.get("rawName"),
        productName=name,  # one product per startup at this stage of company life
        pricingModel=pricing,
        description=description,
        website=content.get("website"),
    )

    return ProductRecord(
        source=Source(
            name=startup_record["source"]["name"],
            url=startup_record["source"]["url"],
        ),
        content=product_content,
    )


async def run_products_extraction(
    startups_path: str = "data/startups.jsonl",
    limit: Optional[int] = None,
    checkpoint_path: Optional[str] = None,
) -> List[ProductRecord]:
    """
    Entry point: reads startups.jsonl, produces Product records.

    If `checkpoint_path` is given, each record is appended to that file
    (JSONL) as soon as it's produced, and any startup already present in
    the checkpoint (matched by source URL) is skipped on startup. This
    makes a long run (LLM calls are rate-paced, so processing thousands
    of startups can take hours) safe to interrupt and resume without
    losing progress or re-spending API calls on already-done records.
    """
    with open(startups_path, "r", encoding="utf-8") as f:
        startups = [json.loads(line) for line in f if line.strip()]

    if limit:
        startups = startups[:limit]

    seen_urls: set = set()
    if checkpoint_path and os.path.exists(checkpoint_path):
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    url = rec.get("source", {}).get("url")
                    if url:
                        seen_urls.add(url)
                except json.JSONDecodeError:
                    continue
        logger.info(f"Resuming from checkpoint: {len(seen_urls)} products already done")

    todo = [s for s in startups if s.get("source", {}).get("url") not in seen_urls]
    logger.info(f"{len(todo)} startups remaining to process")

    results: List[ProductRecord] = []
    async with aiohttp.ClientSession() as session:
        orchestrator = LLMOrchestrator(session)
        for i, s in enumerate(todo):
            record = await build_product_record(orchestrator, s)
            results.append(record)

            if checkpoint_path:
                with open(checkpoint_path, "a", encoding="utf-8") as f:
                    f.write(record.model_dump_json() + "\n")

            if (i + 1) % 25 == 0:
                logger.info(f"Progress: {i + 1}/{len(todo)} products processed")

    return results

