# GraphOne Intelligence Graph Pipeline

Data ingestion pipeline for AI startups, products, research papers, jobs, and news.

## What's built so far

- `src/schemas/models.py` — the exact record formats (Startup, Product, ResearchPaper, Job, News)
- `src/utils/retry.py` — shared retry/backoff logic for handling rate limits (429s)
- `src/scrapers/papers.py` — pulls research papers from arXiv, cross-references
  Papers with Code for GitHub repos, and fetches live star counts

## What's NOT built yet (todo, in order)

1. Test `papers.py` actually runs against live APIs (see Setup below)
2. `src/scrapers/startups.py` + `src/scrapers/products.py` — startup/product directories
3. `src/llm/orchestrator.py` — LLM extraction with fallback chain (Gemini -> Groq -> DeepSeek)
4. `src/resolution/entity_resolver.py` — canonicalize messy names ("Open AI" -> "OpenAI")
5. `src/scrapers/news.py` + `src/scrapers/jobs.py` — with 24-hour freshness filtering
6. `src/main.py` — runs everything and writes to Google Sheets
7. `architecture.pdf` — the design doc

## Setup (do this first)

```bash
# 1. Create a virtual environment (keeps dependencies isolated)
python3 -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Get a GitHub personal access token (for higher API rate limits)
#    https://github.com/settings/tokens -> generate new token (classic), no scopes needed
#    Then create a .env file:
echo "GITHUB_TOKEN=your_token_here" > .env
```

## How to test the papers scraper right now

Ask Claude Code (or run manually) to create a small test script:

```python
# test_papers.py
import asyncio
import os
from dotenv import load_dotenv
from src.scrapers.papers import run_papers_scraper

load_dotenv()

async def main():
    records = await run_papers_scraper(
        categories=["cs.AI"],
        target_per_category=20,   # small number first, to test it works
        github_token=os.getenv("GITHUB_TOKEN"),
    )
    print(f"Collected {len(records)} papers")
    for r in records[:3]:
        print(r.content.title, "|", r.content.github_stars)

asyncio.run(main())
```

Run it:
```bash
python test_papers.py
```

If you're using Claude Code, just say:
> "Run test_papers.py, and if there are any errors, fix them and re-run until it works"

That's the whole workflow for every remaining piece: describe what you want built,
have it write the code, then have it actually run and debug it — don't just accept
code that's never been executed.
