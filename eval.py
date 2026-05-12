"""
eval.py — Custom LLM output evaluator for Job_Seekr.

Two checks run after every resume is tailored:

  1. Keyword Coverage
     What % of the JD's required keywords actually appear in the tailored resume?
     Higher = better ATS pass rate. Target: >70%.

  2. Hallucination Detection
     Did the LLM invent tech skills that aren't in the candidate's original resume?
     We check for a list of specific technical terms — if a term appears in the
     tailored version but NOT in the original, it's flagged as a potential hallucination.

Why no LLM for evaluation?
  Using an LLM to evaluate LLM output adds cost and latency.
  For these two checks, pure text analysis is reliable, fast, and fully explainable —
  which is exactly what an interviewer wants to hear.

Interview talking point:
  "I implemented a two-part evaluation layer: keyword coverage for ATS quality,
   and a hallucination detector that catches invented skills before they reach recruiters."
"""


# ── Hallucination detection vocabulary ────────────────────────────────────────
# These are specific technical terms that should only appear in the tailored resume
# if they were already in the original. Any term that shows up as "new" is flagged.
_TECH_TERMS = [
    # Cloud / Infra
    "kubernetes", "docker", "terraform", "helm", "aws", "gcp", "azure",
    "ec2", "s3", "lambda", "bigquery", "redshift", "snowflake", "databricks",
    # Data Engineering
    "spark", "pyspark", "kafka", "airflow", "dbt", "flink", "hadoop",
    "delta lake", "iceberg", "hive",
    # ML / AI
    "pytorch", "tensorflow", "jax", "xgboost", "lightgbm", "huggingface",
    "langchain", "langgraph", "openai", "llm fine-tuning", "rlhf",
    "vector database", "pinecone", "weaviate", "faiss", "qdrant",
    # BI / Analytics
    "tableau", "looker", "qlik", "mixpanel", "amplitude", "google analytics",
    # Dev
    "scala", "java", "go", "rust", "typescript",
    # Methodology
    "scrum", "safe", "kanban",
]


def evaluate_resume(
    tailored_text: str,
    original_resume_md: str,
    fit_map: dict,
) -> dict:
    """
    Evaluate the quality of a tailored resume.

    Args:
        tailored_text:       Plain-text version of the tailored resume.
        original_resume_md:  The original base resume (markdown) before tailoring.
        fit_map:             The fit analysis dict from analyze_fit() in tailor.py.
                             Must contain 'ats_keywords' key.

    Returns a dict with:
        keyword_coverage_pct  — % of JD keywords found in tailored resume (0-100)
        keywords_found        — list of keywords that ARE present
        keywords_missing      — list of keywords that are NOT present
        hallucination_flags   — list of tech terms added by the LLM but not in original
        passed                — True if coverage ≥ 70% and zero hallucinations
    """
    tailored_lower  = tailored_text.lower()
    original_lower  = original_resume_md.lower()
    ats_keywords    = fit_map.get("ats_keywords", [])

    # ── 1. Keyword coverage ────────────────────────────────────────────────────
    keywords_found   = [kw for kw in ats_keywords if kw.lower() in tailored_lower]
    keywords_missing = [kw for kw in ats_keywords if kw.lower() not in tailored_lower]
    coverage_pct     = (
        round(100 * len(keywords_found) / len(ats_keywords))
        if ats_keywords else 0
    )

    # ── 2. Hallucination detection ─────────────────────────────────────────────
    # Flag any tech term that appears in the tailored resume but NOT in the original.
    # These would be skills the LLM invented — a problem for honest job applications.
    hallucination_flags = [
        term for term in _TECH_TERMS
        if term in tailored_lower and term not in original_lower
    ]

    passed = coverage_pct >= 70 and len(hallucination_flags) == 0

    return {
        "keyword_coverage_pct": coverage_pct,
        "keywords_found":       keywords_found,
        "keywords_missing":     keywords_missing,
        "hallucination_flags":  hallucination_flags,
        "passed":               passed,
    }
