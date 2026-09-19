"""
Final precision pass on papers_checkpoint.jsonl.

Rationale: keyword-based blocklisting (papers.py's _is_aggregator_repo)
catches most digest/awesome-list repos, but not all -- some slip through
because they don't happen to contain a blocked keyword (e.g. "awesome-
agentic", "sg-tamil-tts-resources"). A more robust, naming-independent
signal: a genuine paper-specific implementation repo should only ever be
matched to ONE paper. Any repo matched to more than 2 different papers in
our dataset is almost certainly a list/digest repo, regardless of what
it's named.

This script nulls out github_url/github_stars for any repo that appears
more than `MAX_PAPERS_PER_REPO` times across the dataset. This is a
pure post-processing pass on the existing file -- no new network calls,
runs instantly.

Run after fix_checkpoint.py:
    python final_cleanup.py
"""

import json
import shutil
from collections import Counter

CHECKPOINT_PATH = "data/papers_checkpoint.jsonl"
BACKUP_PATH = "data/papers_checkpoint.backup2.jsonl"
MAX_PAPERS_PER_REPO = 2


def main():
    shutil.copy(CHECKPOINT_PATH, BACKUP_PATH)
    print(f"Backed up to {BACKUP_PATH}")

    records = []
    with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    url_counts = Counter(
        r["content"]["github_url"] for r in records if r["content"].get("github_url")
    )
    bad_urls = {url for url, count in url_counts.items() if count > MAX_PAPERS_PER_REPO}

    print(f"Found {len(bad_urls)} repos matched to more than {MAX_PAPERS_PER_REPO} papers:")
    for url in sorted(bad_urls, key=lambda u: -url_counts[u]):
        print(f"  {url_counts[url]}x  {url}")

    cleared = 0
    for r in records:
        if r["content"].get("github_url") in bad_urls:
            r["content"]["github_url"] = None
            r["content"]["github_stars"] = None
            cleared += 1

    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    print(f"\nCleared {cleared} records with over-matched repos.")
    print(f"File rewritten: {CHECKPOINT_PATH}")


if __name__ == "__main__":
    main()

