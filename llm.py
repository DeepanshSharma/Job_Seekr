"""
llm.py — LLM infrastructure for Job_Seekr.

Everything LLM-related lives here:
  - Groq (primary) + Gemini (fallback) clients
  - call_llm()  — single entry point for all LLM calls
  - Pydantic models — structured output validation (no more regex parsing)
  - Four judgment functions used by the pipeline and tailor
  - log_llm_call() — writes every call to llm_logs table (MLOps observability)
"""

import json
import os
import time

from dotenv import load_dotenv
from google import genai
from groq import Groq
from pydantic import BaseModel, ValidationError

load_dotenv()

# ── Clients ────────────────────────────────────────────────────────────────────
_groq_client   = Groq(api_key=os.getenv("GROQ_API_KEY"))
_gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# DRY_RUN=true in .env skips all API calls and returns preset scores.
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

SCORE_THRESHOLD = 80


# ── Pydantic models — structured outputs ──────────────────────────────────────
# Instead of regex-parsing raw LLM text, we use JSON mode + Pydantic validation.
# This guarantees the shape of every LLM response before we use it.

class OPTResult(BaseModel):
    denied: bool
    reason: str

class LegitimacyResult(BaseModel):
    label: str   # "High Confidence" | "Proceed with Caution" | "Suspicious"
    reason: str

class ScoringResult(BaseModel):
    score: int
    reason: str

class FitMapResult(BaseModel):
    competency_map: list[dict]
    gaps: list[str]
    ats_keywords: list[str]

class SummaryResult(BaseModel):
    summary: str

class BulletsResult(BaseModel):
    roles: list[dict]


# ── DRY_RUN presets ────────────────────────────────────────────────────────────

_DRY_OPT = {
    "Stripe":                (False, "No restrictions — explicitly welcomes OPT/CPT"),
    "Deloitte":              (False, "No restrictions — open to sponsoring work authorization"),
    "Cohere":                (False, "Explicitly welcomes OPT/STEM OPT candidates"),
    "Federal Reserve Board": (True,  "Requires U.S. Citizenship explicitly"),
    "DataBricks":            (False, "Will sponsor H-1B for exceptional candidates"),
    "Google DeepMind":       (False, "Supports visa sponsorship"),
    "Nike":                  (False, "Authorized to sponsor work visas"),
    "Palantir Technologies": (True,  "Requires U.S. Citizenship + security clearance; no sponsorship"),
}
_DRY_FIT = {
    "Stripe":                (82, "DA experience with ETL, SQL dashboards, and analytics engineering maps well"),
    "Deloitte":              (88, "Stakeholder management, KPI reporting, and Power BI all demonstrated"),
    "Cohere":                (74, "Python/ML/LLM background relevant; lacks production RAG pipeline depth"),
    "DataBricks":            (40, "Core Spark/PySpark/Delta Lake expertise genuinely absent"),
    "Google DeepMind":       (45, "ML background present but lacks JAX and large-scale distributed training"),
    "Nike":                  (62, "Partial BA match; consumer digital product tools missing"),
    "Palantir Technologies": (68, "ML and Python skills map; cleared government context is a real gap"),
}
_DRY_ATS = {
    "Stripe":                (86, "SQL, Python, Power BI, ETL pipeline present; Redshift/Snowflake absent"),
    "Deloitte":              (84, "SQL, Power BI, Jira, stakeholder management surface-match well"),
    "Cohere":                (78, "Python, scikit-learn, FastAPI match; LangChain, RAG, vector DB absent"),
    "DataBricks":            (52, "SQL, Python present; PySpark, Spark, Delta Lake all absent"),
    "Google DeepMind":       (60, "ML, Python, scikit-learn present; JAX, PyTorch, RLHF absent"),
    "Nike":                  (68, "SQL, Power BI present; Google Analytics, Mixpanel, SAFe absent"),
    "Palantir Technologies": (72, "Python, SQL, scikit-learn present; clearance terminology absent"),
}
_DRY_LEGITIMACY = {
    "Stripe":                ("High Confidence",       "Specific team, clear responsibilities, active company"),
    "Deloitte":              ("High Confidence",       "Well-known employer, detailed JD with concrete requirements"),
    "Cohere":                ("High Confidence",       "Specific technical stack, active AI company"),
    "Federal Reserve Board": ("High Confidence",       "Government institution, clear role scope"),
    "DataBricks":            ("Proceed with Caution",  "Highly specific stack may indicate narrow internal fit"),
    "Google DeepMind":       ("High Confidence",       "Reputable employer, detailed research-focused JD"),
    "Nike":                  ("High Confidence",       "Large employer, specific product team context"),
    "Palantir Technologies": ("Proceed with Caution",  "Clearance requirement limits pool; may be evergreen"),
}


# ── Core LLM call infrastructure ──────────────────────────────────────────────

def _call_groq(prompt: str, model: str = "llama-3.3-70b-versatile") -> dict:
    """
    Call Groq with JSON mode enabled.
    response_format=json_object forces the model to return valid JSON — no regex needed.
    """
    response = _groq_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def _call_gemini(prompt: str, retries: int = 3) -> dict:
    """Call Gemini (fallback) with exponential backoff on rate limits."""
    last_exc = None
    for attempt in range(retries):
        try:
            response = _gemini_client.models.generate_content(
                model="gemini-2.0-flash", contents=prompt
            )
            # Gemini doesn't have a native JSON mode — strip markdown fences manually
            text = response.text.strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(text)
        except Exception as e:
            last_exc = e
            err = str(e)
            if "429" in err or "quota" in err.lower() or "resource_exhausted" in err.lower():
                import re
                m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", err)
                wait = float(m.group(1)) if m else 30.0
                time.sleep(wait * (2 ** attempt))
            else:
                raise
    raise last_exc


def call_llm(prompt: str, fast: bool = False) -> tuple[dict, str]:
    """
    Main LLM entry point. Tries Groq first, falls back to Gemini.

    fast=True  → llama-3.1-8b-instant (500K TPD) — for quick binary checks
    fast=False → llama-3.3-70b-versatile (100K TPD) — for scoring and analysis
    Returns (result_dict, provider_used).
    """
    start = time.time()
    primary = "llama-3.1-8b-instant" if fast else "llama-3.3-70b-versatile"

    try:
        result = _call_groq(prompt, model=primary)
        time.sleep(2)
        provider = f"groq-{primary}"
        _log_llm_call(primary, prompt[:200], int((time.time() - start) * 1000), provider)
        return result, provider
    except Exception as groq_err:
        err = str(groq_err)
        # 70b hit daily cap → try 8b before Gemini
        if not fast and ("token" in err.lower() or "rate_limit" in err.lower()) and "429" in err:
            try:
                result = _call_groq(prompt, model="llama-3.1-8b-instant")
                time.sleep(2)
                provider = "groq-8b-fallback"
                _log_llm_call("llama-3.1-8b-instant", prompt[:200], int((time.time() - start) * 1000), provider)
                return result, provider
            except Exception:
                pass

        result = _call_gemini(prompt)
        time.sleep(5)
        _log_llm_call("gemini-2.0-flash", prompt[:200], int((time.time() - start) * 1000), "gemini")
        return result, "gemini"


# ── LLM judgment functions ─────────────────────────────────────────────────────
# These are the four decisions the pipeline makes for every job.
# Each validates its response with a Pydantic model for guaranteed structure.

def opt_filter(company: str, jd: str) -> tuple[bool, str]:
    """Does this JD explicitly ban OPT / require citizenship / require clearance?"""
    if DRY_RUN:
        return _DRY_OPT.get(company, (False, "dry-run: no restriction assumed"))

    prompt = f"""Analyze this job description.
Does it explicitly deny visa sponsorship, require US Citizenship, or require a security clearance only available to US Citizens?

Return ONLY valid JSON:
{{"denied": true, "reason": "brief reason"}}

Job Description:
{jd}"""
    raw, _ = call_llm(prompt, fast=True)
    try:
        result = OPTResult(**raw)
    except ValidationError:
        result = OPTResult(denied=False, reason="parse error — assumed no restriction")
    return result.denied, result.reason


def legitimacy_check(company: str, jd: str) -> tuple[str, str]:
    """
    How trustworthy is this posting? Annotates only — never blocks a job.
    Returns (label, reason) where label is one of:
      'High Confidence' | 'Proceed with Caution' | 'Suspicious'
    """
    if DRY_RUN:
        return _DRY_LEGITIMACY.get(company, ("High Confidence", "dry-run"))

    prompt = f"""Assess the legitimacy of this job posting.

Classify as exactly one of:
- "High Confidence": specific role, clear responsibilities, credible employer
- "Proceed with Caution": vague JD, generic requirements, signs of evergreen reposting
- "Suspicious": likely ghost job, fake listing, or spam

Return ONLY valid JSON:
{{"label": "High Confidence", "reason": "one-line reason"}}

Job Description:
{jd}"""
    raw, _ = call_llm(prompt, fast=True)
    try:
        result = LegitimacyResult(**raw)
    except ValidationError:
        result = LegitimacyResult(label="Proceed with Caution", reason="parse error")
    return result.label, result.reason


def fit_check(company: str, jd: str, resume_context: str) -> tuple[int, str]:
    """
    Recruiter-lens score: does the candidate's actual experience demonstrate
    what this role needs, even with different vocabulary?
    resume_context is the RAG-retrieved relevant chunks (not the full resume).
    """
    if DRY_RUN:
        return _DRY_FIT.get(company, (65, "dry-run: default fit score"))

    prompt = f"""You are a senior technical recruiter evaluating conceptual fit.

For each core requirement in the JD, assess whether the candidate's experience
genuinely demonstrates that competency — even when different terminology is used.

Score 0-100 on conceptual alignment. Be realistic — strong presentation of wrong skills still scores low.

Return ONLY valid JSON:
{{"score": 82, "reason": "1-2 sentences: key strengths and any real gaps"}}

Job Description:
{jd}

Relevant Resume Sections:
{resume_context}"""
    raw, _ = call_llm(prompt)
    try:
        result = ScoringResult(**raw)
    except ValidationError:
        result = ScoringResult(score=0, reason="parse error")
    return result.score, result.reason


def ats_check(company: str, jd: str, resume_context: str) -> tuple[int, str]:
    """
    ATS-lens score: surface-level keyword and qualification overlap only.
    resume_context is the RAG-retrieved relevant chunks.
    """
    if DRY_RUN:
        return _DRY_ATS.get(company, (65, "dry-run: default ATS score"))

    prompt = f"""You are an ATS scanner evaluating keyword and qualification surface match.

Check for exact or near-exact skill matches, experience requirements met,
and specific technologies named in the JD present in the resume.

Score 0-100 on surface-level overlap only. If a term is absent, it is absent.

Return ONLY valid JSON:
{{"score": 71, "reason": "brief list of key matches and missing terms"}}

Job Description:
{jd}

Relevant Resume Sections:
{resume_context}"""
    raw, _ = call_llm(prompt)
    try:
        result = ScoringResult(**raw)
    except ValidationError:
        result = ScoringResult(score=0, reason="parse error")
    return result.score, result.reason


# ── LLM call logging (MLOps observability) ────────────────────────────────────

def _log_llm_call(model: str, prompt_preview: str, latency_ms: int, provider: str):
    """
    Write a record to llm_logs for every LLM call.
    Non-fatal — if the DB write fails, the pipeline continues.
    This gives us observability: which model, how fast, what was asked.
    """
    try:
        from db import log_llm_call
        log_llm_call(model, prompt_preview, latency_ms, provider)
    except Exception:
        pass  # logging failure never blocks the pipeline
