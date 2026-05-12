"""
Phase 3 — Live job sourcing engine.

Track A: Direct ATS public APIs (no auth required)
  - Greenhouse: boards-api.greenhouse.io
  - Lever:      api.lever.co
  - Ashby:      api.ashbyhq.com

Track B: Apify scrapers (requires APIFY_API_KEY)
  - LinkedIn:   curious_coder/linkedin-jobs-scraper
  - Indeed:     curious_coder/indeed-scraper
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
from datetime import datetime, timedelta

import requests
import yaml
from dotenv import load_dotenv

from db import (
    get_sourcing_stats,
    insert_job,
    job_composite_exists,
    job_url_exists,
)

load_dotenv()

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

PORTALS_PATH = os.path.join(os.path.dirname(__file__), "portals.yml")
FRESHNESS_DAYS = int(os.getenv("FRESHNESS_DAYS", "2"))
TRACK_A_CAP = 50        # max jobs per ATS company
TRACK_A_SLEEP = 0.3     # seconds between company requests

APIFY_API_KEY    = os.getenv("APIFY_API_KEY", "")
APIFY_DRY_RUN    = os.getenv("APIFY_DRY_RUN", "false").lower() == "true"
TRACK_B_CAP      = int(os.getenv("TRACK_B_CAP", "50"))
TRACK_B_DEV_MODE = os.getenv("TRACK_B_DEV_MODE", "false").lower() == "true"  # use 1 URL, small cap

_all_linkedin_urls = [
    u for u in [
        os.getenv("LINKEDIN_URL_DA"),
        os.getenv("LINKEDIN_URL_BA"),
        os.getenv("LINKEDIN_URL_DS"),   # DS maps to AI role — same resume
        os.getenv("LINKEDIN_URL_AI"),
    ] if u
]
# Dev mode: only use first URL to avoid burning Apify credits
LINKEDIN_URLS = _all_linkedin_urls[:1] if TRACK_B_DEV_MODE else _all_linkedin_urls
INDEED_MAX_RESULTS = int(os.getenv("INDEED_MAX_RESULTS", "50"))
INDEED_LOCATION    = os.getenv("INDEED_LOCATION", "United States")

INDEED_QUERIES = [
    {"role": "DA", "query": "Data Analyst"},
    {"role": "BA", "query": "Business Analyst"},
    {"role": "AI", "query": "Data Scientist"},
    {"role": "AI", "query": "Machine Learning Engineer"},
]

# ── Role classification ───────────────────────────────────────────────────────

DA_KEYWORDS = [
    "data analyst", "analytics analyst", "analytics engineer",
    "sql analyst", "reporting analyst", "data analytics",
]
BA_KEYWORDS = [
    "business analyst", "business intelligence analyst", "bi analyst",
    "product analyst", "strategy analyst", "operations analyst",
    "functional analyst", "systems analyst",
]
AI_KEYWORDS = [
    "ai engineer", "ml engineer", "machine learning engineer", "machine learning",
    "data scientist", "nlp engineer", "llm engineer", "ai/ml",
    "applied scientist", "research engineer", "deep learning",
    "gen ai", "generative ai", "llm", "large language model", "mlops",
]


def classify_role(title: str) -> str | None:
    """
    Map job title to DA / BA / AI.
    Check AI first (most specific) to avoid false DA/BA matches.
    Returns None for titles that don't map to any target role.
    """
    t = title.lower()
    for kw in AI_KEYWORDS:
        if kw in t:
            return "AI"
    for kw in DA_KEYWORDS:
        if kw in t:
            return "DA"
    for kw in BA_KEYWORDS:
        if kw in t:
            return "BA"
    return None


# ── ATS Detection ─────────────────────────────────────────────────────────────

from urllib.parse import urlparse

_ATS_PATTERNS = [
    ("greenhouse.io",        "greenhouse"),
    ("lever.co",             "lever"),
    ("ashbyhq.com",          "ashby"),
    ("myworkdayjobs.com",    "workday"),
    ("icims.com",            "icims"),
    ("taleo.net",            "taleo"),
    ("csod.com",             "cornerstone"),
    ("bamboohr.com",         "bamboohr"),
    ("smartrecruiters.com",  "smartrecruiters"),
    ("jobvite.com",          "jobvite"),
    ("successfactors.com",   "successfactors"),
    ("workable.com",         "workable"),
    ("recruiterbox.com",     "recruiterbox"),
]


def detect_ats(apply_url: str) -> str:
    """
    Detect ATS from the URL domain only — ignores query params like ?source=LinkedIn
    which are just tracking attribution, not an indicator of the ATS type.
    """
    if not apply_url:
        return "unknown"
    try:
        domain = urlparse(apply_url).netloc.lower()
    except Exception:
        return "unknown"
    if "linkedin.com" in domain:
        return "linkedin_easy"
    for pattern, ats in _ATS_PATTERNS:
        if pattern in domain:
            return ats
    return "company_custom"


# ── Shared utilities ──────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities. Returns plain text."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date(raw: str | int | None) -> str:
    """
    Normalize heterogeneous date formats to YYYY-MM-DD.
    Falls back to today if unparseable.
    """
    today = datetime.today()
    if raw is None:
        return today.strftime("%Y-%m-%d")

    # Lever gives millisecond timestamps
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000).strftime("%Y-%m-%d")
        except Exception:
            return today.strftime("%Y-%m-%d")

    raw = str(raw).strip()

    # Relative: "today", "1 day ago", "3 days ago"
    if raw.lower() == "today" or raw.lower() == "just posted":
        return today.strftime("%Y-%m-%d")
    m = re.match(r"(\d+)\s+day", raw.lower())
    if m:
        return (today - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")

    # ISO 8601 with/without time
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:26], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # "April 10, 2026" style
    try:
        return datetime.strptime(raw, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        pass

    return today.strftime("%Y-%m-%d")


def _is_stale(posted_at: str) -> bool:
    try:
        posted = datetime.strptime(posted_at, "%Y-%m-%d")
    except ValueError:
        return False
    return datetime.today() - posted > timedelta(days=FRESHNESS_DAYS)


def normalize_job(raw: dict, source: str, role: str | None = None) -> dict:
    """
    Map raw actor/API output to the jobs table schema.
    `source` is one of: track_a_greenhouse | track_a_lever | track_a_ashby
                         | track_b_linkedin | track_b_indeed
    `role` is pre-computed when the query already encodes role (Indeed queries).
    """
    # ── Field extraction with fallbacks ──────────────────────────────────────
    title = (
        raw.get("title") or raw.get("positionName") or raw.get("name") or ""
    ).strip()
    # Some Indeed/LinkedIn rows append salary to the title (e.g. "Data Analyst - 57.69 - 67.31 per hour").
    # Strip trailing salary patterns: hourly ranges, annual ranges, and "$X-Y" suffixes.
    title = re.sub(
        r"\s*[-–—]\s*\$?[\d,.]+\s*[-–—]\s*\$?[\d,.]+\s*(per\s*(hour|hr|year|yr|annum)|/(hour|hr|year|yr)|hourly|annually|/yr)\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()

    company = (
        raw.get("company_name") or raw.get("companyName") or raw.get("company")
        or raw.get("organization") or ""
    ).strip()

    description_raw = (
        raw.get("description") or raw.get("descriptionText")
        or raw.get("descriptionHtml") or raw.get("content")
        or raw.get("descriptionBody") or ""
    )
    description = _strip_html(description_raw)

    url = (
        raw.get("link") or raw.get("jobUrl") or raw.get("absolute_url") or raw.get("url")
        or raw.get("applyUrl") or raw.get("hostedUrl") or ""
    ).strip()

    external_id = str(
        raw.get("id") or raw.get("jobId") or raw.get("postingId") or ""
    ).strip()

    posted_raw = (
        raw.get("postingDateParsed") or raw.get("postedAt") or raw.get("publishedAt")
        or raw.get("updated_at") or raw.get("createdAt") or raw.get("date")
        or raw.get("datePosted") or None
    )
    posted_at = _parse_date(posted_raw)

    location = (
        raw.get("location") or raw.get("locationName")
        or (raw.get("location") or {}).get("name") if isinstance(raw.get("location"), dict)
        else raw.get("location") or ""
    )
    if isinstance(location, dict):
        location = location.get("name", "")
    location = str(location).strip()

    # ── Role classification ───────────────────────────────────────────────────
    assigned_role = role or classify_role(title)

    # ── Apply URL + ATS detection ─────────────────────────────────────────────
    apply_url = (
        raw.get("externalApplyLink") or raw.get("applyUrl") or raw.get("apply_url")
        or raw.get("absolute_url") or raw.get("hostedUrl") or url
    ).strip()
    is_easy_apply = bool(raw.get("isEasyApply") or raw.get("is_easy_apply", False))
    ats_type = "linkedin_easy" if is_easy_apply else detect_ats(apply_url)

    return {
        "apify_url":            url,
        "company_name":         company,
        "job_title":            title,
        "job_description":      description,
        "posted_at":            posted_at,
        "status":               "Pending",
        "assigned_resume_type": assigned_role,
        "source":               source,
        "external_id":          external_id,
        "sourced_at":           datetime.now().isoformat(timespec="seconds"),
        "apply_url":            apply_url,
        "ats_type":             ats_type,
        "is_easy_apply":        is_easy_apply,
    }


def ingest(raw_jobs: list[dict], source: str, role_hint: str | None = None) -> dict:
    """
    Dedup, classify, and INSERT normalized jobs.
    Returns {inserted, skipped_dup, skipped_stale, skipped_no_role, errors}.
    """
    counts = dict(inserted=0, skipped_dup=0, skipped_stale=0,
                  skipped_no_role=0, errors=0)

    for raw in raw_jobs:
        try:
            job = normalize_job(raw, source, role=role_hint)

            # Must have a role
            if not job["assigned_resume_type"]:
                counts["skipped_no_role"] += 1
                continue

            # Freshness gate
            if _is_stale(job["posted_at"]):
                counts["skipped_stale"] += 1
                continue

            # Primary dedup: URL
            if job["apify_url"] and job_url_exists(job["apify_url"]):
                counts["skipped_dup"] += 1
                continue

            # Secondary dedup: company + title
            if job_composite_exists(job["company_name"], job["job_title"]):
                counts["skipped_dup"] += 1
                continue

            insert_job(job)
            counts["inserted"] += 1

        except Exception as exc:
            logger.warning("ingest error for %s: %s", raw.get("title", "?"), exc)
            counts["errors"] += 1

    return counts


# ── Track A — ATS public APIs ─────────────────────────────────────────────────

def _load_portals() -> dict:
    with open(PORTALS_PATH, "r") as f:
        return yaml.safe_load(f)


def fetch_greenhouse(slug: str) -> list[dict]:
    """Fetch jobs from Greenhouse public board API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    resp = requests.get(url, timeout=(3, 5))
    resp.raise_for_status()
    return resp.json().get("jobs", [])[:TRACK_A_CAP]


def fetch_lever(slug: str) -> list[dict]:
    """Fetch postings from Lever public API."""
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    resp = requests.get(url, timeout=(3, 5))
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        company_name = slug.replace("-", " ").title()
        for p in data:
            p.setdefault("company_name", company_name)
        return data[:TRACK_A_CAP]
    return []


def fetch_ashby(slug: str) -> list[dict]:
    """Fetch job postings from Ashby public API."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    resp = requests.get(url, timeout=(3, 5))
    resp.raise_for_status()
    data = resp.json()
    # Ashby returns {"jobs": [...]} — "jobPostings" was old API shape
    postings = data.get("jobs") or data.get("jobPostings") or []
    # Ashby doesn't include company_name per-job — inject from slug
    company_name = slug.replace("-", " ").title()
    for p in postings:
        p.setdefault("company_name", company_name)
    return postings[:TRACK_A_CAP]


def run_track_a() -> dict:
    """
    Fetch from all Greenhouse, Lever, and Ashby portals in portals.yml.
    Returns combined ingest counts + per-source breakdown.
    """
    portals = _load_portals()
    totals = dict(inserted=0, skipped_dup=0, skipped_stale=0,
                  skipped_no_role=0, errors=0)
    breakdown: dict[str, int] = {}

    ats_map = [
        ("greenhouse", portals.get("greenhouse") or [], fetch_greenhouse, "track_a_greenhouse"),
        ("lever",      portals.get("lever")      or [], fetch_lever,      "track_a_lever"),
        ("ashby",      portals.get("ashby")      or [], fetch_ashby,      "track_a_ashby"),
    ]

    for ats_name, slugs, fetcher, source_tag in ats_map:
        for slug in slugs:
            try:
                raw_jobs = fetcher(slug)
                result = ingest(raw_jobs, source=source_tag)
                for k, v in result.items():
                    totals[k] = totals.get(k, 0) + v
                breakdown[source_tag] = breakdown.get(source_tag, 0) + result["inserted"]
                logger.info("[Track A] %s/%s — %d inserted, %d dup",
                            ats_name, slug, result["inserted"], result["skipped_dup"])
            except requests.exceptions.Timeout:
                logger.warning("[Track A] %s/%s — timeout, skipping", ats_name, slug)
                totals["errors"] += 1
            except requests.HTTPError as e:
                status_code = e.response.status_code if e.response else "?"
                logger.warning("[Track A] %s/%s — HTTP %s, skipping", ats_name, slug, status_code)
                totals["errors"] += 1
            except Exception as e:
                logger.warning("[Track A] %s/%s — error: %s", ats_name, slug, e)
                totals["errors"] += 1
            time.sleep(TRACK_A_SLEEP)

    totals["breakdown"] = breakdown
    return totals


# ── Track B — Apify scrapers ──────────────────────────────────────────────────

def _apify_run(actor_id: str, run_input: dict) -> list[dict]:
    """
    Run an Apify actor synchronously and return all dataset items.
    Returns empty list immediately when APIFY_DRY_RUN=true (dev mode — no credits spent).
    """
    if APIFY_DRY_RUN:
        logger.info("[Apify DRY RUN] Skipping actor %s — returning 0 items", actor_id)
        return []
    from apify_client import ApifyClient
    client = ApifyClient(APIFY_API_KEY)
    run = client.actor(actor_id).call(run_input=run_input)
    return list(client.dataset(run["defaultDatasetId"]).iterate_items())


def run_linkedin_scraper() -> dict:
    """
    Scrape LinkedIn using pre-filtered search URLs from env vars.
    Skipped gracefully if no URLs configured or no API key.
    """
    if not APIFY_API_KEY:
        logger.warning("[Track B] APIFY_API_KEY not set — skipping LinkedIn")
        return dict(inserted=0, skipped_dup=0, skipped_stale=0,
                    skipped_no_role=0, errors=0, skipped_config=1)

    if not LINKEDIN_URLS:
        logger.warning("[Track B] No LINKEDIN_URL_* env vars set — skipping LinkedIn")
        return dict(inserted=0, skipped_dup=0, skipped_stale=0,
                    skipped_no_role=0, errors=0, skipped_config=1)

    dev_cap = 10 if TRACK_B_DEV_MODE else TRACK_B_CAP
    run_input = {
        "urls": LINKEDIN_URLS,
        "count": dev_cap,           # jobs per URL
        "scrapeCompany": False,     # skip company page — halves run time and cost
        "splitByLocation": False,
    }
    try:
        items = _apify_run("curious_coder/linkedin-jobs-scraper", run_input)
        return ingest(items, source="track_b_linkedin")
    except Exception as e:
        logger.error("[Track B] LinkedIn scraper failed: %s", e)
        return dict(inserted=0, skipped_dup=0, skipped_stale=0,
                    skipped_no_role=0, errors=1)


def run_indeed_scraper() -> dict:
    """
    Scrape Indeed using misceres/indeed-scraper (free, 20k+ users).
    One Apify run per role query. Returns combined ingest counts.
    """
    if not APIFY_API_KEY:
        logger.warning("[Track B] APIFY_API_KEY not set — skipping Indeed")
        return dict(inserted=0, skipped_dup=0, skipped_stale=0,
                    skipped_no_role=0, errors=0, skipped_config=1)

    dev_cap = 25 if TRACK_B_DEV_MODE else INDEED_MAX_RESULTS
    totals = dict(inserted=0, skipped_dup=0, skipped_stale=0,
                  skipped_no_role=0, errors=0)

    for q in INDEED_QUERIES:
        run_input = {
            "position":            q["query"],
            "location":            INDEED_LOCATION,
            "country":             "US",
            "maxItemsPerSearch":   dev_cap,
            "saveOnlyUniqueItems": True,
            "parseCompanyDetails": False,
            "followApplyRedirects": False,
        }
        try:
            items = _apify_run("misceres/indeed-scraper", run_input)
            result = ingest(items, source="track_b_indeed", role_hint=q["role"])
            for k, v in result.items():
                if k in totals:
                    totals[k] += v
            logger.info("[Track B] Indeed '%s' — %d inserted", q["query"], result["inserted"])
        except Exception as e:
            logger.error("[Track B] Indeed '%s' failed: %s", q["query"], e)
            totals["errors"] += 1

    return totals


def run_track_b() -> dict:
    """Run both LinkedIn and Indeed scrapers and combine results."""
    linkedin = run_linkedin_scraper()
    indeed   = run_indeed_scraper()

    combined: dict = {}
    for k in set(list(linkedin.keys()) + list(indeed.keys())):
        if k == "breakdown":
            continue
        combined[k] = (linkedin.get(k) or 0) + (indeed.get(k) or 0)

    combined["breakdown"] = {
        "track_b_linkedin": linkedin.get("inserted", 0),
        "track_b_indeed":   indeed.get("inserted", 0),
    }
    return combined


# ── Top-level entry point ─────────────────────────────────────────────────────

def run_sourcing(tracks: list[str] = ("a", "b")) -> dict:
    """
    Run requested sourcing tracks and return combined ingest stats.

    tracks: list containing "a", "b", or both.
    Returns dict with ingest counts + stats snapshot.
    """
    tracks = [t.lower() for t in tracks]
    totals = dict(inserted=0, skipped_dup=0, skipped_stale=0,
                  skipped_no_role=0, errors=0, breakdown={})

    if "a" in tracks:
        result_a = run_track_a()
        for k, v in result_a.items():
            if k == "breakdown":
                totals["breakdown"].update(v)
            elif k in totals:
                totals[k] += v

    if "b" in tracks:
        result_b = run_track_b()
        for k, v in result_b.items():
            if k == "breakdown":
                totals["breakdown"].update(v)
            elif k in totals:
                totals[k] += v

    # Auto-trigger scoring pipeline on newly inserted Pending jobs
    if totals.get("inserted", 0) > 0:
        logger.info("Auto-triggering pipeline on %d new Pending jobs...", totals["inserted"])
        try:
            from pipeline import run_pipeline_on_pending
            totals["pipeline"] = run_pipeline_on_pending()
        except Exception as e:
            logger.error("Pipeline auto-trigger failed: %s", e)
            totals["pipeline"] = {"error": str(e)}
    else:
        logger.info("No new jobs inserted — pipeline not triggered")
        totals["pipeline"] = None

    totals["stats"] = get_sourcing_stats()

    return totals
