import json
import os
import re
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from google import genai
from groq import Groq

from db import clear_jobs, get_resume, insert_job

load_dotenv()

# ── Clients ───────────────────────────────────────────────────────────────────
_groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
_gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MOCK_JOBS_PATH = os.path.join(os.path.dirname(__file__), "data", "mock_jobs.json")
FRESHNESS_DAYS = 3
SCORE_THRESHOLD = 80

# DRY_RUN=true in .env skips all API calls — uses preset scores for dev/testing
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# ── Dry-run presets (mirrors what real Gemini/Groq should return) ─────────────
_DRY_RUN_OPT = {
    "Stripe":                (False, "No restrictions — explicitly welcomes OPT/CPT"),
    "Deloitte":              (False, "No restrictions — open to sponsoring work authorization"),
    "Cohere":                (False, "Explicitly welcomes OPT/STEM OPT candidates"),
    "Federal Reserve Board": (True,  "Requires U.S. Citizenship explicitly"),
    "DataBricks":            (False, "Will sponsor H-1B for exceptional candidates"),
    "Google DeepMind":       (False, "Supports visa sponsorship"),
    "Nike":                  (False, "Authorized to sponsor work visas"),
    "Palantir Technologies": (True,  "Requires U.S. Citizenship + security clearance; no sponsorship"),
}
_DRY_RUN_SCORES = {
    "Stripe":                (84, "Strong SQL/Python/Power BI match; ETL pipeline experience aligns well"),
    "Deloitte":              (86, "Solid BA match: stakeholder management, KPI reporting, SQL, Jira"),
    "Cohere":                (76, "Good Python/ML overlap; lacks deep RAG production experience"),
    "DataBricks":            (48, "Missing core Spark/PySpark/Scala and Databricks platform depth"),
    "Google DeepMind":       (55, "ML background present but lacks JAX/PyTorch at scale and PhD-level research"),
    "Nike":                  (65, "Partial BA match; lacks Scrum/SAFe and product analytics tool experience"),
    "Palantir Technologies": (70, "ML skills match but clearance/citizenship requirement is a hard block"),
}

# Legitimacy: High Confidence / Proceed with Caution / Suspicious
_DRY_RUN_LEGITIMACY = {
    "Stripe":                ("High Confidence",       "Specific team, clear responsibilities, active company"),
    "Deloitte":              ("High Confidence",       "Well-known employer, detailed JD with concrete requirements"),
    "Cohere":                ("High Confidence",       "Specific technical stack, active AI company, credible posting"),
    "Federal Reserve Board": ("High Confidence",       "Government institution, clear role scope and requirements"),
    "DataBricks":            ("Proceed with Caution",  "Highly specific stack requirements may indicate narrow internal fit"),
    "Google DeepMind":       ("High Confidence",       "Reputable employer, detailed research-focused JD"),
    "Nike":                  ("High Confidence",       "Large employer, specific product team context"),
    "Palantir Technologies": ("Proceed with Caution",  "Clearance requirement limits applicant pool; posting may be evergreen"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in: {text!r}")
    return json.loads(match.group())


def _parse_retry_delay(error_str: str, default: float = 30.0) -> float:
    match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", error_str)
    return float(match.group(1)) if match else default


def _call_groq(prompt: str) -> dict:
    """Call Groq (primary). Returns parsed dict. Raises on failure."""
    response = _groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    return _extract_json(response.choices[0].message.content)


def _call_gemini(prompt: str, retries: int = 3) -> dict:
    """Call Gemini (fallback) with backoff on 429."""
    last_exc = None
    for attempt in range(retries):
        try:
            response = _gemini_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            return _extract_json(response.text)
        except Exception as e:
            last_exc = e
            err = str(e)
            if "429" in err or "quota" in err.lower() or "resource_exhausted" in err.lower():
                wait = _parse_retry_delay(err) * (2 ** attempt)
                time.sleep(wait)
            else:
                raise
    raise last_exc


def _call_llm(prompt: str) -> tuple[dict, str]:
    """
    Try Groq first. On any failure, fall back to Gemini.
    Returns (result_dict, provider_used).
    """
    try:
        result = _call_groq(prompt)
        time.sleep(2)  # Groq: stay well under 30 RPM
        return result, "groq"
    except Exception as groq_err:
        try:
            result = _call_gemini(prompt)
            time.sleep(5)  # Gemini: stay under 15 RPM
            return result, "gemini"
        except Exception as gemini_err:
            raise RuntimeError(
                f"Both providers failed. Groq: {groq_err} | Gemini: {gemini_err}"
            )


# ── Pipeline stages ───────────────────────────────────────────────────────────

def _is_stale(posted_at: str) -> bool:
    try:
        posted = datetime.strptime(posted_at, "%Y-%m-%d")
    except ValueError:
        return True
    return datetime.today() - posted > timedelta(days=FRESHNESS_DAYS)


def _legitimacy_check(company: str, jd: str) -> tuple[str, str]:
    """
    Return (label, reason).
    label is one of: 'High Confidence' | 'Proceed with Caution' | 'Suspicious'
    Never blocks a job — only annotates it.
    """
    if DRY_RUN:
        return _DRY_RUN_LEGITIMACY.get(company, ("High Confidence", "dry-run: assumed legitimate"))

    prompt = f"""Assess the legitimacy and trustworthiness of this job posting.

Classify it as exactly one of:
- "High Confidence": Specific role, clear responsibilities, credible employer, not a ghost job
- "Proceed with Caution": Vague JD, very generic requirements, unusual patterns, or signs of evergreen reposting
- "Suspicious": Likely ghost job, fake listing, or spam (no specific details, unrealistic requirements, suspicious apply link)

Return ONLY a JSON object:
{{"label": "High Confidence", "reason": "brief one-line reason"}}

Job Description:
{jd}"""
    result, _ = _call_llm(prompt)
    return result.get("label", "Proceed with Caution"), result.get("reason", "")


def _opt_filter(company: str, jd: str) -> tuple[bool, str]:
    if DRY_RUN:
        return _DRY_RUN_OPT.get(company, (False, "dry-run: no restriction assumed"))

    prompt = f"""Analyze this job description carefully.
Does it explicitly deny visa sponsorship, require US Citizenship, or require a security clearance only available to US Citizens?

Answer with ONLY a JSON object:
{{"denied": true, "reason": "brief reason"}}
or
{{"denied": false, "reason": "no restriction found"}}

Job Description:
{jd}"""
    result, _ = _call_llm(prompt)
    return bool(result.get("denied")), result.get("reason", "")


def _score_resume(company: str, jd: str, resume: str) -> tuple[int, str]:
    if DRY_RUN:
        return _DRY_RUN_SCORES.get(company, (60, "dry-run: default score"))

    prompt = f"""You are an ATS. Score this resume against the job description from 0 to 100 based solely on alignment of core hard skills, relevant experience, and qualifications. Be strict and realistic.

Return ONLY a JSON object:
{{"score": 75, "reason": "brief reason"}}

Job Description:
{jd}

Resume:
{resume}"""
    result, _ = _call_llm(prompt)
    return int(result.get("score", 0)), result.get("reason", "")


# ── Main entry point ──────────────────────────────────────────────────────────

def run_pipeline() -> dict:
    with open(MOCK_JOBS_PATH, "r") as f:
        jobs = json.load(f)

    clear_jobs()
    counts = {"total": len(jobs), "stale": 0, "rejected": 0, "low_match": 0, "passed": 0, "errored": 0}

    for job in jobs:
        jd      = job.get("job_description", "")
        company = job.get("company_name", "")
        role    = job.get("assigned_resume_type", "DA")

        # Stage 1 — Freshness (no API)
        if _is_stale(job.get("posted_at", "")):
            insert_job({**job, "status": "Stale", "filter_reason": "Posted more than 3 days ago"})
            counts["stale"] += 1
            continue

        # Stage 2 — OPT filter
        try:
            denied, reason = _opt_filter(company, jd)
        except Exception as e:
            insert_job({**job, "status": "Error", "filter_reason": f"OPT filter failed: {e}"})
            counts["errored"] += 1
            continue

        if denied:
            insert_job({**job, "status": "Rejected", "filter_reason": reason})
            counts["rejected"] += 1
            continue

        # Stage 3 — Legitimacy check (annotates, never blocks)
        try:
            leg_label, leg_reason = _legitimacy_check(company, jd)
        except Exception as e:
            leg_label, leg_reason = "Unknown", f"Legitimacy check failed: {e}"

        # Stage 4 — Semantic scoring
        resume_content = get_resume(role)
        if not resume_content:
            insert_job({**job, "status": "Error", "filter_reason": f"No resume for role: {role}"})
            counts["errored"] += 1
            continue

        try:
            score, score_reason = _score_resume(company, jd, resume_content)
        except Exception as e:
            insert_job({**job, "status": "Error", "filter_reason": f"Scoring failed: {e}",
                        "legitimacy_label": leg_label, "legitimacy_reason": leg_reason})
            counts["errored"] += 1
            continue

        if score >= SCORE_THRESHOLD:
            insert_job({**job, "status": "Passed", "match_score": score, "filter_reason": score_reason,
                        "legitimacy_label": leg_label, "legitimacy_reason": leg_reason})
            counts["passed"] += 1
        else:
            insert_job({**job, "status": "Low Match", "match_score": score, "filter_reason": score_reason,
                        "legitimacy_label": leg_label, "legitimacy_reason": leg_reason})
            counts["low_match"] += 1

    return counts
