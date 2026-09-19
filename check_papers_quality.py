"""
Quick data quality check on the collected papers checkpoint file.

Run this any time to sanity-check what you've collected so far:
    python check_papers_quality.py
"""

import json

CHECKPOINT_PATH = "data/papers_checkpoint.jsonl"


def main():
    total = 0
    with_github = 0
    with_stars = 0
    missing_title = 0
    missing_authors = 0
    missing_date = 0
    star_counts = []
    categories_seen = set()
    sample_with_stars = []
    github_url_counts = {}

    with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            content = rec.get("content", {})
            total += 1

            if content.get("github_url"):
                with_github += 1
                url = content["github_url"]
                github_url_counts[url] = github_url_counts.get(url, 0) + 1
            stars = content.get("github_stars")
            if stars is not None:
                with_stars += 1
                star_counts.append(stars)
                if len(sample_with_stars) < 5:
                    sample_with_stars.append((content.get("title", "")[:60], stars))

            if not content.get("title"):
                missing_title += 1
            if not content.get("authors"):
                missing_authors += 1
            if not content.get("published_date"):
                missing_date += 1

            for c in content.get("categories", []):
                categories_seen.add(c)

    print("=" * 55)
    print(f"TOTAL RECORDS:              {total}")
    print(f"With a GitHub repo linked:  {with_github}  ({100*with_github/total:.1f}%)")
    print(f"With a star count:          {with_stars}  ({100*with_stars/total:.1f}%)")
    print(f"Missing title:              {missing_title}")
    print(f"Missing authors:            {missing_authors}")
    print(f"Missing published_date:     {missing_date}")
    print(f"Distinct arXiv categories:  {len(categories_seen)}")
    if star_counts:
        print(f"Star count range:           {min(star_counts)} - {max(star_counts)}")
        print(f"Average stars (when found): {sum(star_counts)/len(star_counts):.1f}")
    print("=" * 55)
    print("\nSample papers WITH GitHub stars found:")
    for title, stars in sample_with_stars:
        print(f"  [{stars} stars] {title}")

    print("\nRepos matched to MULTIPLE different papers (likely false positives -- "
          "'awesome-list' style repos rather than actual paper implementations):")
    suspicious = {url: c for url, c in github_url_counts.items() if c > 1}
    if not suspicious:
        print("  None found -- looks clean.")
    else:
        for url, count in sorted(suspicious.items(), key=lambda x: -x[1]):
            print(f"  {count}x  {url}")


if __name__ == "__main__":
    main()

