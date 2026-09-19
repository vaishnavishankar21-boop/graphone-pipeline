"""
Converts all collected data (JSONL files) into clean CSV files, one per
required Google Sheet tab, ready for direct import.

Run this any time -- safe to re-run as more data comes in (e.g. after
run_products.py finishes more records). Reads the freshest available
file for each vertical (checkpoint files reflect the most up-to-date
progress, since they're written incrementally).

Usage:
    python export_to_csv.py

Output: data/csv_export/*.csv -- one file per tab:
    startups.csv, products.csv, research_papers.csv, jobs.csv, news.csv,
    entity_mapping_log.csv
"""

import csv
import json
import os

OUTPUT_DIR = "data/csv_export"


def load_jsonl(path):
    if not os.path.exists(path):
        print(f"  (not found, skipping: {path})")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_csv(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"  Wrote {len(rows)} rows -> {path}")


def export_startups():
    print("Exporting Startups...")
    # Prefer the entity-resolved file (canonical names applied); fall back
    # to the raw collected file if resolution hasn't been run.
    records = load_jsonl("data/startups_resolved.jsonl") or load_jsonl("data/startups.jsonl")
    rows = []
    for r in records:
        c = r.get("content", {})
        data = c.get("data", {})
        rows.append({
            "schemaVersion": r.get("schemaVersion"),
            "recordType": r.get("recordType"),
            "source.name": r.get("source", {}).get("name"),
            "source.url": r.get("source", {}).get("url"),
            "content.entityName": c.get("entityName"),
            "content.rawName": c.get("rawName"),
            "content.description": c.get("description"),
            "content.website": c.get("website"),
            "content.data.employeeCount": data.get("employeeCount"),
            "content.data.foundedYear": data.get("foundedYear"),
            "content.data.hq": data.get("hq"),
            "content.data.industry": data.get("industry"),
            "collectedAt": r.get("collectedAt"),
        })
    fieldnames = ["schemaVersion", "recordType", "source.name", "source.url",
                  "content.entityName", "content.rawName", "content.description",
                  "content.website", "content.data.employeeCount",
                  "content.data.foundedYear", "content.data.hq",
                  "content.data.industry", "collectedAt"]
    write_csv(f"{OUTPUT_DIR}/startups.csv", rows, fieldnames)


def export_products():
    print("Exporting Products...")
    # Checkpoint file has the most up-to-date progress (products.py writes
    # to it incrementally); resolved file may be stale if entity
    # resolution ran before products finished. Prefer checkpoint.
    records = load_jsonl("data/products_checkpoint.jsonl") or load_jsonl("data/products.jsonl")
    rows = []
    for r in records:
        c = r.get("content", {})
        rows.append({
            "schemaVersion": r.get("schemaVersion"),
            "recordType": r.get("recordType"),
            "source.name": r.get("source", {}).get("name"),
            "source.url": r.get("source", {}).get("url"),
            "content.startupName": c.get("startupName"),
            "content.rawStartupName": c.get("rawStartupName"),
            "content.productName": c.get("productName"),
            "content.pricingModel": c.get("pricingModel"),
            "content.description": c.get("description"),
            "content.website": c.get("website"),
            "collectedAt": r.get("collectedAt"),
        })
    fieldnames = ["schemaVersion", "recordType", "source.name", "source.url",
                  "content.startupName", "content.rawStartupName",
                  "content.productName", "content.pricingModel",
                  "content.description", "content.website", "collectedAt"]
    write_csv(f"{OUTPUT_DIR}/products.csv", rows, fieldnames)


def export_papers():
    print("Exporting Research Papers...")
    records = load_jsonl("data/papers_checkpoint.jsonl")
    rows = []
    for r in records:
        c = r.get("content", {})
        rows.append({
            "schemaVersion": r.get("schemaVersion"),
            "recordType": r.get("recordType"),
            "source.name": r.get("source", {}).get("name"),
            "source.url": r.get("source", {}).get("url"),
            "content.title": c.get("title"),
            "content.authors": "; ".join(c.get("authors", []) or []),
            "content.paper_url": c.get("paper_url"),
            "content.github_url": c.get("github_url"),
            "content.github_stars": c.get("github_stars"),
            "content.published_date": c.get("published_date"),
            "content.arxiv_id": c.get("arxiv_id"),
            "collectedAt": r.get("collectedAt"),
        })
    fieldnames = ["schemaVersion", "recordType", "source.name", "source.url",
                  "content.title", "content.authors", "content.paper_url",
                  "content.github_url", "content.github_stars",
                  "content.published_date", "content.arxiv_id", "collectedAt"]
    write_csv(f"{OUTPUT_DIR}/research_papers.csv", rows, fieldnames)


def export_jobs():
    print("Exporting Jobs...")
    records = load_jsonl("data/jobs.jsonl")
    rows = []
    for r in records:
        c = r.get("content", {})
        rows.append({
            "schemaVersion": r.get("schemaVersion"),
            "recordType": r.get("recordType"),
            "source.name": r.get("source", {}).get("name"),
            "source.url": r.get("source", {}).get("url"),
            "content.title": c.get("title"),
            "content.company": c.get("company"),
            "content.date": c.get("date"),
            "content.is_remote": c.get("is_remote"),
            "content.role_family": c.get("role_family"),
            "content.location": c.get("location"),
            "content.job_url": c.get("job_url"),
            "collectedAt": r.get("collectedAt"),
        })
    fieldnames = ["schemaVersion", "recordType", "source.name", "source.url",
                  "content.title", "content.company", "content.date",
                  "content.is_remote", "content.role_family",
                  "content.location", "content.job_url", "collectedAt"]
    write_csv(f"{OUTPUT_DIR}/jobs.csv", rows, fieldnames)


def export_news():
    print("Exporting News...")
    records = load_jsonl("data/news.jsonl")
    rows = []
    for r in records:
        c = r.get("content", {})
        rows.append({
            "schemaVersion": r.get("schemaVersion"),
            "recordType": r.get("recordType"),
            "source.name": r.get("source", {}).get("name"),
            "source.url": r.get("source", {}).get("url"),
            "content.title": c.get("title"),
            "content.summary": c.get("summary"),
            "content.published_date": c.get("published_date"),
            "content.article_url": c.get("article_url"),
            "collectedAt": r.get("collectedAt"),
        })
    fieldnames = ["schemaVersion", "recordType", "source.name", "source.url",
                  "content.title", "content.summary", "content.published_date",
                  "content.article_url", "collectedAt"]
    write_csv(f"{OUTPUT_DIR}/news.csv", rows, fieldnames)


def export_entity_mapping_log():
    print("Exporting Entity Mapping Log...")
    records = load_jsonl("data/entity_mapping_log.jsonl")
    fieldnames = ["entityType", "rawName", "canonicalName", "method", "confidence", "sourceUrl"]
    write_csv(f"{OUTPUT_DIR}/entity_mapping_log.csv", records, fieldnames)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    export_startups()
    export_products()
    export_papers()
    export_jobs()
    export_news()
    export_entity_mapping_log()
    print(f"\nAll CSVs written to {OUTPUT_DIR}/")
    print("Next: create a Google Sheet, add 6 tabs, and import each CSV.")


if __name__ == "__main__":
    main()