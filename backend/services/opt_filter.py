"""
OPT Filter — uses Groq (fast inference) to classify whether a job description
explicitly bans international applicants or refuses visa sponsorship.
"""
import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client: Groq | None = None


def get_groq_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set")
        _client = Groq(api_key=api_key)
    return _client


def check_opt_eligibility(job_title: str, company_name: str, job_description: str) -> dict:
    """
    Returns:
        {
            "blocks_opt": bool,
            "reason": str
        }
    """
    prompt = f"""You are screening job descriptions for F1-OPT international students from India.

Read the following job description and determine:
Does this job EXPLICITLY ban international applicants, require US Citizenship only,
require security clearance, or clearly state they do NOT offer visa sponsorship?

Job Title: {job_title}
Company: {company_name}
Description:
{job_description}

Respond ONLY with valid JSON in this exact format:
{{"blocks_opt": true or false, "reason": "one sentence explanation"}}

Do not include any text outside the JSON."""

    client = get_groq_client()
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=150,
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: don't block if parsing fails
        return {"blocks_opt": False, "reason": f"Parse error, defaulting to pass. Raw: {raw[:100]}"}
