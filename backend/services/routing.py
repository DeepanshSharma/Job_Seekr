"""
Routing + Tier Assignment — uses Gemini to compare a job against the 3 resume
variants and assign a priority tier (1=top tech, 2=mid, 3=standard/startup).
"""
import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from data.resumes import DA_RESUME, BA_RESUME, AI_RESUME

load_dotenv()

_model = None


def get_model():
    global _model
    if _model is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel("gemini-2.0-flash")
    return _model


def route_job(job_title: str, company_name: str, job_description: str) -> dict:
    """
    Returns:
        {
            "best_resume": "DA" | "BA" | "AI",
            "priority_tier": 1 | 2 | 3,
            "reasoning": str
        }
    """
    prompt = f"""You are a job application strategist helping an early-career Data Analyst / Data Scientist
(F1-OPT, targeting mid-level to entry roles) decide which resume to send and how to prioritize this job.

You have 3 resume variants:

--- RESUME DA (Data Analyst) ---
{DA_RESUME}

--- RESUME BA (Business Analyst) ---
{BA_RESUME}

--- RESUME AI (Data Scientist / AI Engineer) ---
{AI_RESUME}

---
Job Title: {job_title}
Company: {company_name}
Job Description:
{job_description}

Based on the job description, answer:
1. Which resume fits best? (DA, BA, or AI)
2. What priority tier is this company?
   - Tier 1: Top tech / FAANG / elite finance (Google, Meta, Amazon, Goldman, etc.)
   - Tier 2: Well-known mid-size companies, established banks, consulting firms
   - Tier 3: Startups, smaller companies, less-known firms

Respond ONLY with valid JSON in this exact format:
{{"best_resume": "DA", "priority_tier": 2, "reasoning": "one sentence"}}

Do not include any text outside the JSON."""

    model = get_model()
    response = model.generate_content(prompt)
    raw = response.text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
        # Validate fields
        if result.get("best_resume") not in ("DA", "BA", "AI"):
            result["best_resume"] = "DA"
        if result.get("priority_tier") not in (1, 2, 3):
            result["priority_tier"] = 3
        return result
    except json.JSONDecodeError:
        return {
            "best_resume": "DA",
            "priority_tier": 3,
            "reasoning": f"Parse error, defaulted. Raw: {raw[:100]}",
        }
