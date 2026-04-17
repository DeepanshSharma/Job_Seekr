import json
import os
import re
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from google import genai
from groq import Groq

from db import clear_jobs, get_resume, get_pending_jobs, insert_job, update_job_pipeline_result

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
_DRY_RUN_FIT = {
    "Stripe":                (82, "DA experience with ETL, SQL dashboards, and analytics engineering maps well conceptually; cloud data warehouse depth (Redshift/Snowflake) is a genuine gap"),
    "Deloitte":              (88, "Stakeholder management, requirements gathering, KPI reporting, and Power BI all demonstrated; formal BRD authorship and UAT leadership less evident"),
    "Cohere":                (74, "Python/ML/LLM integration background conceptually relevant; lacks production RAG pipeline depth and LangChain/vector-DB hands-on experience"),
    "DataBricks":            (40, "Core Spark/PySpark/Delta Lake expertise genuinely absent; SQL and Python present but at wrong scale and toolchain for this role"),
    "Google DeepMind":       (45, "ML background present but lacks JAX, large-scale distributed training, and research publication record; significant seniority gap"),
    "Nike":                  (62, "Partial BA match; consumer digital product, Scrum/SAFe, and product analytics tools (Mixpanel, GA) genuinely missing"),
    "Palantir Technologies": (68, "ML and Python skills map to the DS role conceptually; cleared government customer context is a genuine experience gap"),
}
_DRY_RUN_ATS = {
    "Stripe":                (86, "SQL, Python, Power BI, ETL pipeline, REST API, data quality keywords present; Redshift/Snowflake/pandas not mentioned"),
    "Deloitte":              (84, "SQL, Power BI, Jira, stakeholder management surface-match well; BRD, UAT, use case documentation terminology absent"),
    "Cohere":                (78, "Python, scikit-learn, TensorFlow, FastAPI, REST API match; LangChain, RAG, vector database terms absent"),
    "DataBricks":            (52, "SQL, Python present; PySpark, Spark, Delta Lake, Kafka, dbt, Scala all absent"),
    "Google DeepMind":       (60, "ML, Python, scikit-learn, TensorFlow present; JAX, PyTorch, RLHF, transformer, XLA all absent"),
    "Nike":                  (68, "SQL, Power BI, Jira, stakeholder management present; Google Analytics, Mixpanel, Scrum, SAFe, user stories absent"),
    "Palantir Technologies": (72, "Python, SQL, scikit-learn, TensorFlow present; clearance, defense sector, Palantir platform terminology absent"),
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


def _fit_check(company: str, jd: str, resume: str) -> tuple[int, str]:
    """
    Recruiter-lens evaluation: does the candidate's actual experience
    conceptually demonstrate what this role needs, even with different vocab?
    """
    if DRY_RUN:
        return _DRY_RUN_FIT.get(company, (65, "dry-run: default fit score"))

    prompt = f"""You are a senior technical recruiter evaluating conceptual fit — not keyword matching.

For each core requirement in this job description, assess whether the candidate's actual experience genuinely demonstrates that competency, even when different terminology is used.

Ask yourself:
- Does the candidate's work history show they can actually do this job?
- Are their seniority and depth appropriate for this role?
- What genuine skill or experience gaps exist that vocabulary changes cannot fix?

Score 0-100 on conceptual alignment. Be realistic and strict — strong presentation of the wrong skills still scores low.

Return ONLY a JSON object:
{{"score": 82, "reason": "1-2 sentences covering key conceptual strengths and any real gaps"}}

Job Description:
{jd}

Resume:
{resume}"""
    result, _ = _call_llm(prompt)
    return int(result.get("score", 0)), result.get("reason", "")


def _ats_check(company: str, jd: str, resume: str) -> tuple[int, str]:
    """
    ATS-lens evaluation: surface-level keyword and qualification overlap.
    """
    if DRY_RUN:
        return _DRY_RUN_ATS.get(company, (65, "dry-run: default ATS score"))

    prompt = f"""You are an ATS scanner evaluating keyword and qualification surface match.

Check for:
- Exact or near-exact skill and tool name matches
- Years of experience requirements met
- Required qualifications present (degree, certifications)
- Specific technologies and methodologies named in the JD present in the resume

Score 0-100 on surface-level overlap only. Do not infer intent — if a term is absent, it is absent.

Return ONLY a JSON object:
{{"score": 71, "reason": "brief list of key matches and missing terms"}}

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

        # Stage 4 — Dual scoring: fit check (recruiter lens) + ATS check (keyword lens)
        resume_content = get_resume(role)
        if not resume_content:
            insert_job({**job, "status": "Error", "filter_reason": f"No resume for role: {role}"})
            counts["errored"] += 1
            continue

        try:
            fit_score, fit_reason = _fit_check(company, jd, resume_content)
            ats_score, ats_reason = _ats_check(company, jd, resume_content)
        except Exception as e:
            insert_job({**job, "status": "Error", "filter_reason": f"Scoring failed: {e}",
                        "legitimacy_label": leg_label, "legitimacy_reason": leg_reason})
            counts["errored"] += 1
            continue

        # Combined score: fit weighted higher (60/40) — conceptual match matters more
        match_score  = round(0.7 * fit_score + 0.3 * ats_score)
        score_reason = f"Fit: {fit_score}% — {fit_reason} | ATS: {ats_score}% — {ats_reason}"

        base = {
            **job,
            "match_score": match_score,
            "fit_score":   fit_score,
            "ats_score":   ats_score,
            "filter_reason": score_reason,
            "legitimacy_label":  leg_label,
            "legitimacy_reason": leg_reason,
        }
        if match_score >= SCORE_THRESHOLD:
            insert_job({**base, "status": "Passed"})
            counts["passed"] += 1
        else:
            insert_job({**base, "status": "Low Match"})
            counts["low_match"] += 1

    return counts


# ── Phase 3 entry point — process Pending jobs already in DB ──────────────────

def run_pipeline_on_pending() -> dict:
    """
    Run the triage pipeline on all jobs currently in the DB with status='Pending'.
    Unlike run_pipeline(), this never clears or re-inserts — it updates in place.
    Called automatically by sourcer.run_sourcing() after ingestion.
    """
    jobs = get_pending_jobs()
    counts = {"total": len(jobs), "stale": 0, "rejected": 0,
              "low_match": 0, "passed": 0, "errored": 0}

    for job in jobs:
        job_id  = job["id"]
        jd      = job.get("job_description", "")
        company = job.get("company_name", "")
        role    = job.get("assigned_resume_type", "DA")

        # Stage 1 — Freshness
        if _is_stale(job.get("posted_at", "")):
            update_job_pipeline_result(job_id, "Stale",
                                       filter_reason="Posted more than 3 days ago")
            counts["stale"] += 1
            continue

        # Stage 2 — OPT filter
        try:
            denied, reason = _opt_filter(company, jd)
        except Exception as e:
            update_job_pipeline_result(job_id, "Error",
                                       filter_reason=f"OPT filter failed: {e}")
            counts["errored"] += 1
            continue

        if denied:
            update_job_pipeline_result(job_id, "Rejected", filter_reason=reason)
            counts["rejected"] += 1
            continue

        # Stage 3 — Legitimacy (annotates, never blocks)
        try:
            leg_label, leg_reason = _legitimacy_check(company, jd)
        except Exception as e:
            leg_label, leg_reason = "Unknown", f"Legitimacy check failed: {e}"

        # Stage 4 — Dual scoring
        resume_content = get_resume(role)
        if not resume_content:
            update_job_pipeline_result(job_id, "Error",
                                       filter_reason=f"No resume for role: {role}",
                                       legitimacy_label=leg_label,
                                       legitimacy_reason=leg_reason)
            counts["errored"] += 1
            continue

        try:
            fit_score, fit_reason = _fit_check(company, jd, resume_content)
            ats_score, ats_reason = _ats_check(company, jd, resume_content)
        except Exception as e:
            update_job_pipeline_result(job_id, "Error",
                                       filter_reason=f"Scoring failed: {e}",
                                       legitimacy_label=leg_label,
                                       legitimacy_reason=leg_reason)
            counts["errored"] += 1
            continue

        match_score  = round(0.7 * fit_score + 0.3 * ats_score)
        score_reason = f"Fit: {fit_score}% — {fit_reason} | ATS: {ats_score}% — {ats_reason}"

        if match_score >= SCORE_THRESHOLD:
            update_job_pipeline_result(
                job_id, "Passed",
                match_score=match_score, fit_score=fit_score, ats_score=ats_score,
                filter_reason=score_reason,
                legitimacy_label=leg_label, legitimacy_reason=leg_reason,
            )
            counts["passed"] += 1
        else:
            update_job_pipeline_result(
                job_id, "Low Match",
                match_score=match_score, fit_score=fit_score, ats_score=ats_score,
                filter_reason=score_reason,
                legitimacy_label=leg_label, legitimacy_reason=leg_reason,
            )
            counts["low_match"] += 1

    return counts
