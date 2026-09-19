"""
Applies entity resolution to the collected startups and products, and
produces the Entity Mapping Log (Raw vs Canonical names) required as one
of the 6 Google Sheet tabs in the final deliverable.

For each startup/product record:
  - content.rawName / content.rawStartupName (already captured at
    scrape time) is resolved via EntityResolver.
  - content.entityName / content.startupName is updated to the
    resolved canonical form.
  - Every resolution decision is logged to
    data/entity_mapping_log.jsonl regardless of whether it matched the
    seed database or not -- this is what makes the log a complete audit
    trail, not just a list of the "interesting" cases.

Usage:
    python run_entity_resolution.py
"""

import json
import os

from src.resolution.entity_resolver import EntityResolver

STARTUPS_IN = "data/startups.jsonl"
STARTUPS_OUT = "data/startups_resolved.jsonl"
PRODUCTS_IN = "data/products.jsonl"
PRODUCTS_OUT = "data/products_resolved.jsonl"
MAPPING_LOG_OUT = "data/entity_mapping_log.jsonl"


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def main():
    resolver = EntityResolver()
    mapping_log = []

    # ---- Startups ----
    startups = load_jsonl(STARTUPS_IN)
    for rec in startups:
        content = rec["content"]
        raw_name = content.get("rawName") or content.get("entityName")
        result = resolver.resolve(raw_name)
        content["entityName"] = result.canonical_name
        mapping_log.append({
            "entityType": "STARTUP",
            "rawName": result.raw_name,
            "canonicalName": result.canonical_name,
            "method": result.method,
            "confidence": result.confidence,
            "sourceUrl": rec.get("source", {}).get("url"),
        })
    if startups:
        write_jsonl(STARTUPS_OUT, startups)
        print(f"Resolved {len(startups)} startup records -> {STARTUPS_OUT}")

    # ---- Products ----
    products = load_jsonl(PRODUCTS_IN)
    for rec in products:
        content = rec["content"]
        raw_name = content.get("rawStartupName") or content.get("startupName")
        result = resolver.resolve(raw_name)
        content["startupName"] = result.canonical_name
        mapping_log.append({
            "entityType": "PRODUCT",
            "rawName": result.raw_name,
            "canonicalName": result.canonical_name,
            "method": result.method,
            "confidence": result.confidence,
            "sourceUrl": rec.get("source", {}).get("url"),
        })
    if products:
        write_jsonl(PRODUCTS_OUT, products)
        print(f"Resolved {len(products)} product records -> {PRODUCTS_OUT}")

    write_jsonl(MAPPING_LOG_OUT, mapping_log)
    print(f"\nEntity mapping log written: {MAPPING_LOG_OUT} ({len(mapping_log)} entries)")

    # Summary stats
    from collections import Counter
    method_counts = Counter(m["method"] for m in mapping_log)
    print("\nResolution method breakdown:")
    for method, count in method_counts.most_common():
        print(f"  {method}: {count}")

    seed_matches = [m for m in mapping_log if m["method"] != "no_seed_match"]
    print(f"\n{len(seed_matches)} entities matched the 50-company seed database:")
    for m in seed_matches[:15]:
        print(f"  {m['rawName']!r} -> {m['canonicalName']!r} ({m['method']}, {m['confidence']:.0f}%)")


if __name__ == "__main__":
    main()