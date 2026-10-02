# GraphOne / FrontierAtlas Intelligence Graph — Data Ingestion Pipeline

A data ingestion pipeline collecting structured AI-ecosystem intelligence
across five verticals: startups, products, research papers, jobs, and
news. Built for the GraphOne / FrontierAtlas AI Engineer trial assignment.

## Results Summary

| Vertical | Records | Source(s) |
|---|---|---|
| Research Papers | 1,004 | arXiv API + GitHub API (stars/repo linkage) |
| Startups | 2,044 | Y Combinator company directory (via yc-oss.github.io) |
| Products | 2,044 | Derived from Startups + LLM-inferred pricing model |
| News | 311 (fresh, ≤24h) | 5 RSS feeds: TechCrunch AI, VentureBeat AI, arXiv cs.AI, DeepMind Blog, Hugging Face Blog |
| Jobs | 20 (fresh, ≤24h) | 3 job board APIs: RemoteOK, WeWorkRemotely, Arbeitnow |
| Entity Mapping Log | 2,064 | Resolution against 50-company seed database (exact + fuzzy match) |

**Products pricing model distribution:** ENTERPRISE: 1,191 · UNKNOWN: 720
· PAID: 69 · FREE: 56 · FREEMIUM: 8. (UNKNOWN reflects genuinely
uninformative source descriptions plus cases where every configured LLM
tier was unavailable for that record — the pipeline defaults to UNKNOWN
rather than guessing, per the no-hallucination requirement.)

Full data: see the linked Google Sheet (6 tabs matching the table above).
Architecture rationale, scale strategy, and design tradeoffs: see
`architecture.pdf`.

## Project Structure

```
src/
  schemas/models.py          # Canonical Pydantic schemas for all 5 record types
  scrapers/
    papers.py                # arXiv + GitHub star/repo enrichment
    startups.py               # Y Combinator directory (yc-oss.github.io)
    products.py               # Derives products from startups + LLM pricing inference
    news.py                    # RSS feeds, 24h freshness filtering, flexible date parsing
    jobs.py                    # Job board APIs, AI keyword filtering, 24h freshness
  llm/
    orchestrator.py            # Multi-tier LLM fallback chain (429 handling, backoff)
    chunking.py                 # Pre-emptive text truncation (413 prevention)
  resolution/
    entity_resolver.py         # Exact + fuzzy matching against seed database
    seed_entities.py            # 50 known AI startups with name variants
  utils/
    retry.py                    # Shared exponential backoff + jitter + fast-fallthrough
    dates.py                    # Shared flexible date normalization (RFC822/ISO8601/epoch/relative)

run_papers.py                 # Entry point: collect research papers
run_startups.py                # Entry point: collect startups
run_products.py                 # Entry point: LLM-extract product pricing models
run_news.py                      # Entry point: collect fresh AI news
run_jobs.py                       # Entry point: collect fresh AI jobs
run_entity_resolution.py           # Entry point: resolve names to canonical form
export_to_csv.py                    # Converts all collected data to CSV for Google Sheets import

check_papers_quality.py        # Data quality diagnostics for the papers dataset
fix_checkpoint.py               # One-time repair script (removed bad GitHub matches)
final_cleanup.py                 # One-time repair script (removed over-matched repos)

architecture.pdf                # Full architecture document (scale, 413/429, freshness, storage)
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows; use `source venv/bin/activate` on Mac/Linux
pip install -r requirements.txt
```

Create a `.env` file in the project root:
```
GITHUB_TOKEN=your_github_personal_access_token
GROQ_API_KEY=your_groq_api_key
```
- GitHub token (free): https://github.com/settings/tokens — no scopes needed, used for higher API rate limits on the papers/GitHub-star enrichment step.
- Groq API key (free tier): https://console.groq.com/keys — powers the LLM extraction chain (Products vertical).

Optional third fallback tier:
```
OPENROUTER_API_KEY=your_openrouter_api_key
```
(DeepSeek via OpenRouter — see Known Limitations below.)

## Running the Pipeline

Each vertical runs independently and writes to `data/*.jsonl`:

```bash
python run_papers.py              # ~15-20 min, checkpointed/resumable
python run_startups.py            # ~seconds, static JSON API
python run_products.py            # Several hours (LLM-rate-limited), checkpointed/resumable
python run_news.py                # ~10-20 seconds
python run_jobs.py                # ~10-20 seconds
python run_entity_resolution.py   # Instant, local logic only
python export_to_csv.py           # Converts everything to CSV for Sheets import
```

All long-running scripts (`run_papers.py`, `run_products.py`) checkpoint
progress incrementally to `data/*_checkpoint.jsonl` and are safe to
interrupt (Ctrl+C) and resume — re-running the same command picks up
exactly where it left off without re-processing or losing data.

## Key Design Decisions

**Source selection over scraping.** Every vertical is built against a
structured API or feed (arXiv, GitHub, yc-oss, RSS feeds, job board
JSON APIs) rather than raw HTML scraping. This eliminates most anti-bot
friction for the trial's scope and guarantees every record traces back
to a real, verifiable source URL — no hallucinated data.

**Multi-tier LLM fallback with real-world testing and tuning.** The
orchestrator was built for a 3-tier chain (Gemini → Groq → DeepSeek) but
was adjusted twice after live testing:
1. Gemini's free tier was non-functional for this account (100% failure
   rate regardless of pacing) — removed from the active chain rather than
   burning retry time on a dead tier.
2. Groq's free tier enforces a real **daily** request cap in addition to
   its per-minute limit, reporting 429s with Retry-After values of
   100-450+ seconds when exhausted. The retry logic initially slept
   through up to 5 such waits on the same tier before ever falling
   through — meaning the chain could lose 20+ minutes stuck on one dead
   tier. Fixed with a `giveup_if_delay_exceeds` threshold: any wait
   longer than 30 seconds now gives up on that tier immediately, falling
   through to the next tier within seconds instead of minutes.

Both fixes are documented inline in `orchestrator.py` and `retry.py` —
this kind of empirical adjustment based on what actually happens against
live free-tier APIs, rather than documentation alone, is the core of
what Phase III's "resilient LLM integration" requirement is testing for.

**Data quality verification, not just collection.** The papers pipeline
initially matched ~45% of papers to a GitHub repo, but manual
verification caught that many matches were "daily arxiv digest"
aggregator repos, not actual paper implementations (one repo was matched
to 148 different papers). Fixed via a keyword blocklist plus a per-repo
match-count cap. See `fix_checkpoint.py` and `final_cleanup.py` for the
repair scripts, and `check_papers_quality.py` for the diagnostic tooling
used to catch this.

**Freshness as an ingestion invariant.** News and Jobs filter to the
last 24 hours at collection time (not as a later query filter), using a
shared date-normalization utility (`src/utils/dates.py`) that handles
RFC 822, ISO 8601, Unix epoch, and relative ("2 hours ago") formats — and
treats an unparseable date as NOT fresh (conservative) rather than
guessing.

## Known Limitations

- **OpenRouter/DeepSeek third tier** is wired into the fallback chain but
  returned `403 auth failed` in this project's testing despite a
  configured API key — likely requires additional account verification
  on OpenRouter's side. Groq alone was sufficient to complete all 2,044
  product extractions; OpenRouter remains available as a genuine third
  option once that's resolved.
- **Jobs/News coverage** is intentionally 3-5 real sources rather than
  scraping every possible board — sources were chosen for having genuine
  structured APIs/feeds (no anti-bot fighting, real dates) over raw
  quantity.
- **Entity resolution seed database** covers 50 well-known AI companies;
  the majority of collected startups (being smaller/earlier stage)
  correctly fall through to using their own name as canonical, which is
  expected given the seed list's intentionally small size.

See `architecture.pdf` for the full scale-to-500k design and storage
strategy discussion.