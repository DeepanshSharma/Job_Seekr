# Job_Seekr — Phase 3 Execution Plan

**Status:** ✅ COMPLETE
**Goal:** Replace mock data with live jobs from Track A (ATS APIs) and Track B (Apify scraping).

---

## What Was Built

### `sourcer.py` — Full Sourcing Engine

**Track A — Direct ATS APIs (free, no auth):**
- `fetch_greenhouse(slug)` — `boards-api.greenhouse.io`
- `fetch_lever(slug)` — `api.lever.co`
- `fetch_ashby(slug)` — `api.ashbyhq.com`
- `run_track_a()` — reads `portals.yml`, runs all fetchers, ingests results

**Track B — Apify Scrapers:**
- `run_linkedin_scraper()` — `curious_coder/linkedin-jobs-scraper` with pre-filtered URLs
- `run_indeed_scraper()` — `misceres/indeed-scraper` with keyword + location params
- `run_track_b()` — orchestrates both actors

**Shared:**
- `classify_role(title)` — keyword match → DA / BA / AI / None
- `normalize_job(raw, source)` — maps raw API output → jobs table schema
- `detect_ats(apply_url)` — detects Greenhouse/Lever/Workday/etc. from URL
- `ingest(raw_jobs, source)` — dedup + classify + INSERT, returns counts
- `run_sourcing(tracks)` — top-level entry point, auto-triggers pipeline after ingest

**Deduplication (two layers):**
1. Primary: `apify_url` match
2. Secondary: `(company_name, job_title)` composite

### `db.py` additions
- `source TEXT` — 'track_a_greenhouse' | 'track_a_lever' | 'track_b_linkedin' | etc.
- `external_id TEXT` — ATS-native job ID
- `sourced_at TEXT` — ISO timestamp
- `apply_url TEXT` — direct application link
- `ats_type TEXT` — detected ATS platform
- `is_easy_apply INTEGER` — 1 if LinkedIn Easy Apply
- `job_url_exists()`, `job_composite_exists()`, `get_pending_jobs()`, `get_sourcing_stats()`

### `app.py` — Sourcing Page (Page 2)
- "Run Track A — ATS APIs" button (~30s, free)
- "Run Track B — LinkedIn + Indeed" button (requires `APIFY_API_KEY`)
- "Run Full Sourcing" button (both tracks)
- Track B auto-disabled with tooltip if `APIFY_API_KEY` not set
- DB Stats panel: Total Jobs · New Today · Pending Pipeline · By Source breakdown
- Track B Configuration expander (shows which LinkedIn URLs are configured)

### Auto-Pipeline Trigger
After any sourcing run that inserts new jobs, `run_pipeline_on_pending()` is called
automatically — new jobs go straight from Pending to scored without manual action.

---

## Environment Variables Required

```
APIFY_API_KEY=...              # Track B only
LINKEDIN_URL_DA=...            # Pre-filtered LinkedIn search URL (Easy Apply + Past week + Full-time)
LINKEDIN_URL_BA=...
LINKEDIN_URL_AI=...
```

---

## Phase 3 Verification — Confirmed Working
- [x] Track A fetches from Greenhouse/Lever/Ashby and inserts to DB
- [x] Dedup prevents re-insertion on re-runs
- [x] Track B (LinkedIn) fetches via Apify and inserts with `source=track_b_linkedin`
- [x] Auto-pipeline scores new Pending jobs immediately after ingest
- [x] Sourcing page shows correct DB stats and by-source breakdown
- [x] 552 live jobs currently in DB from LinkedIn track

---

## Key Decisions Made in Phase 3

| Decision | Choice | Reason |
|----------|--------|--------|
| LinkedIn actor | `curious_coder/linkedin-jobs-scraper` | 4.9★, 40K users, most reliable |
| Indeed actor | `misceres/indeed-scraper` | Free actor, 20K+ users |
| Track A freshness | `FRESHNESS_DAYS` env (default 2) | Balance freshness vs. volume |
| Track A cap | 50 jobs per company | Prevents flooding from large portals |
| Track B cap | 50 per search query | 4 queries × 50 = 200 max per run |
| Scheduling | Manual UI trigger only | No cron in Phase 3 — Phase 4+ |
| Auto-pipeline | Yes — triggers on any new insert | Single flow, no manual step |

---

## Environment Variables (add to `.env`)

```
# Apify
APIFY_API_KEY=<APIFY_API_KEY_REDACTED>

# LinkedIn pre-filtered search URLs (set in LinkedIn UI: Easy Apply ON, Past 7 days, Remote)
LINKEDIN_URL_DA=<paste after finalizing in LinkedIn>
LINKEDIN_URL_BA=<paste after finalizing in LinkedIn>
LINKEDIN_URL_AI=<paste after finalizing in LinkedIn>

# Indeed search config (actor handles URL construction internally)
INDEED_COUNTRY=United States
INDEED_LOCATION=United States
INDEED_POSTED_WITHIN=7
INDEED_MAX_RESULTS=100
```

### LinkedIn URL filter checklist (before pasting):
- [ ] Easy Apply: ON (`f_LF=f_AL` in URL)
- [ ] Date posted: Past week (`f_TPR=r604800`)
- [ ] Job type: Full-time (`f_JT=F`)
- [ ] Experience: Entry/Associate level (`f_E=1,2`)
- [ ] Remote: checked if desired (`f_WT=2`)

---

## Files to Build

### 1. `sourcer.py` — Main Sourcing Engine

**Track A functions (ATS public APIs — no auth needed):**

| Function | What it does |
|----------|-------------|
| `fetch_greenhouse(company: str)` | `GET boards-api.greenhouse.io/v1/boards/{co}/jobs?content=true` |
| `fetch_lever(company: str)` | `GET api.lever.co/v0/postings/{co}?mode=json` |
| `fetch_ashby(company: str)` | `GET api.ashbyhq.com/posting-api/job-board/{co}` |
| `run_track_a(portals_path: str)` | Reads `portals.yml`, calls all three fetchers, returns normalized list |

**Track B functions (Apify):**

| Function | What it does |
|----------|-------------|
| `run_linkedin_scraper(urls: list[str])` | Calls `curious_coder/linkedin-jobs-scraper` with pre-filtered URLs |
| `run_indeed_scraper(queries: list[dict])` | Calls `curious_coder/indeed-scraper` with keyword+location params |
| `run_track_b()` | Orchestrates both actors, returns normalized list |

**Shared functions:**

| Function | What it does |
|----------|-------------|
| `classify_role(title: str) -> str \| None` | Keyword match → `"DA"` / `"BA"` / `"AI"` / `None` (skip if None) |
| `normalize_job(raw: dict, source: str) -> dict` | Maps raw actor output → `jobs` table schema |
| `ingest(raw_jobs: list[dict]) -> dict` | Dedup + classify + normalize + INSERT, returns `{inserted, skipped, errors}` |
| `run_sourcing(tracks: list[str]) -> dict` | Top-level: runs requested tracks, ingests, triggers pipeline |

**Apify call pattern (both actors):**
```python
from apify_client import ApifyClient

client = ApifyClient(os.getenv("APIFY_API_KEY"))
run = client.actor("curious_coder/linkedin-jobs-scraper").call(run_input={
    "startUrls": [{"url": url} for url in linkedin_urls],
    "maxResults": 100
})
items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
```

**Indeed actor input:**
```python
run_input = {
    "country": os.getenv("INDEED_COUNTRY", "United States"),
    "query": query,           # e.g. "Data Analyst"
    "location": os.getenv("INDEED_LOCATION", "United States"),
    "postedWithin": int(os.getenv("INDEED_POSTED_WITHIN", 7)),
    "maxResults": int(os.getenv("INDEED_MAX_RESULTS", 100))
}
```

---

### 2. `db.py` additions

New columns (ALTER TABLE migration, same pattern as Phase 1/2):
```
source       TEXT   -- 'track_a_greenhouse' | 'track_a_lever' | 'track_a_ashby'
                    --  | 'track_b_linkedin' | 'track_b_indeed'
external_id  TEXT   -- ATS-native job ID (Greenhouse ID, Lever posting ID, etc.)
```

New helpers:
```python
def job_url_exists(url: str) -> bool
    # SELECT 1 FROM jobs WHERE apify_url = ? LIMIT 1

def get_sourcing_stats() -> dict
    # Returns: {total, by_source, new_today, last_run_at}
```

---

### 3. `app.py` additions — "Sourcing" tab

New tab alongside Triage Board:

```
[ Triage Board ]  [ Sourcing ]

┌─ Sourcing Controls ──────────────────────────────────┐
│  [Run Track A — ATS APIs]   (free, ~30s)              │
│  [Run Track B — LinkedIn + Indeed]   (~2-3 min)       │
│  [Run Full Sourcing]   (both tracks + auto-pipeline)  │
└───────────────────────────────────────────────────────┘

┌─ Last Run ────────────────────────────────────────────┐
│  2026-04-14 10:32 AM                                  │
│  ✓ 12 new jobs inserted                               │
│  ↷ 38 skipped (duplicates)                            │
│  ✗ 2 errors                                           │
│                                                       │
│  By source:                                           │
│  track_a_greenhouse: 5  track_a_lever: 3              │
│  track_b_linkedin: 3    track_b_indeed: 1             │
└───────────────────────────────────────────────────────┘
```

- Track B button shows disabled tooltip if `APIFY_API_KEY` not set
- "Run Full Sourcing" auto-calls `run_pipeline()` from `gemini_orchestrator.py` after ingest
- Spinner with live status updates per stage

---

## Role Classification Keywords

Applied at ingestion — jobs with `None` role are skipped entirely:

```python
DA_KEYWORDS = [
    "data analyst", "analytics analyst", "bi analyst", "sql analyst",
    "business intelligence analyst", "reporting analyst", "data analytics"
]
BA_KEYWORDS = [
    "business analyst", "product analyst", "strategy analyst",
    "operations analyst", "functional analyst", "systems analyst"
]
AI_KEYWORDS = [
    "ai engineer", "ml engineer", "machine learning engineer",
    "data scientist", "nlp engineer", "llm engineer", "ai/ml",
    "applied scientist", "research engineer", "deep learning"
]
```

---

## Deduplication Strategy

1. **Primary:** `apify_url` — if URL already exists in SQLite, skip
2. **Secondary:** `(company_name, job_title)` composite — catches reposts with different URLs
3. Both checks run in `ingest()` before any INSERT

---

## Track A Rate Limiting

- `0.3s` sleep between company requests (polite client)
- 50 most recent jobs per company (ATS APIs return newest first — just take `[:50]`)
- ~75 companies → ~30s total runtime
- On HTTP error (404/500): log warning, skip company, continue

---

## Build Order

1. `db.py` — add `source`, `external_id` columns + `job_url_exists()` + `get_sourcing_stats()`
2. `sourcer.py` — Track A fetchers + `ingest()` (testable without Apify key)
3. Test Track A end-to-end: run against `portals.yml`, confirm jobs appear in Triage Board
4. `sourcer.py` — Track B (LinkedIn + Indeed Apify actors)
5. `app.py` — Sourcing tab + buttons + stats panel
6. Full end-to-end test: Run Full Sourcing → jobs appear → pipeline scores them

---

## Phase 3 Verification Checkpoint

1. **Track A only run** → Greenhouse/Lever/Ashby jobs appear in Triage Board as `Pending`
2. **Pipeline auto-triggers** → jobs get OPT-filtered, legitimacy-scored, and match-scored
3. **Re-run Track A** → zero new insertions (dedup working)
4. **Track B run** → LinkedIn + Indeed jobs appear with correct `source` column values
5. **Full run** → all sources combined, pipeline runs once, Triage Board shows live jobs
6. **Sourcing tab stats** → shows accurate counts by source, last run time

---

## What's NOT in Phase 3

- No LinkedIn login / session cookies — `curious_coder/linkedin-jobs-scraper` uses public data only
- No scheduling / cron — manual button trigger only (cron is Phase 4+)
- No cover letter generation — that's Phase 2 scope
- No auto-apply — Phase 4
