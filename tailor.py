"""
tailor.py — Phase 2 LLM tailoring engine + Playwright PDF renderer.

Pipeline per job:
  1. extract_keywords()   — Groq: 15-20 JD keywords
  2. rewrite_summary()    — Groq: inject keywords into Summary (3 sentences, hard cap)
  3. reframe_experience() — Groq: reframe bullets with JD vocab, preserving bullet count
  4. _build_html()        — fill cv-template.html with tailored data
  5. _render_pdf_raw()    — Playwright: Letter PDF bytes
  6. one-page fit loop    — margin → font → trim 4→3 bullets (last resort only)
  7. update_tailor_result() — write PDF path + re-score to DB

Section order matches resume format: Summary → Skills → Education → Experience → Projects
No extra sections (no Core Competencies, no Professional Summary header).
"""

import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from db import get_job_by_id, get_resume, update_tailor_result
from gemini_orchestrator import DRY_RUN, _call_llm, _score_resume

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = _DIR / "templates" / "cv-template.html"
OUTPUT_DIR = _DIR / "output"

# ── Candidate contact info ────────────────────────────────────────────────────
# Update phone / LinkedIn / GitHub here as needed.
CANDIDATE = {
    "name":     "Deepansh Sharma",
    "email":    "deepansh2424@gmail.com",
    "phone":    "+1 (202) 345-5407",
    "linkedin": "linkedin.com/in/deepansh-sharma-03071997",
    "github":   "github.com/DeepanshSharma",
}

# ── DRY_RUN presets (mirrors what real LLM returns) ───────────────────────────
_DRY_KEYWORDS = [
    "data analysis", "SQL", "Python", "Power BI", "ETL pipelines",
    "stakeholder management", "KPI tracking", "data visualization",
    "dashboard development", "business intelligence",
    "data quality", "cross-functional collaboration",
    "requirements gathering", "process optimization", "reporting automation",
]

_DRY_SUMMARY = (
    "Data professional with hands-on experience building ETL pipelines, SQL-driven dashboards, "
    "and self-service analytics using Python and Power BI. Strong focus on KPI tracking, "
    "data quality, and stakeholder management - translating business requirements into "
    "reliable, data-driven insights that support operational decision-making."
)


# ── ATS normalization ─────────────────────────────────────────────────────────

def normalize_ats(text: str) -> str:
    """Replace non-ATS-safe Unicode characters with ASCII equivalents."""
    replacements = [
        ("\u2014", "-"),   # em-dash
        ("\u2013", "-"),   # en-dash
        ("\u2018", "'"),   # left single quote
        ("\u2019", "'"),   # right single quote
        ("\u201c", '"'),   # left double quote
        ("\u201d", '"'),   # right double quote
        ("\u2026", "..."), # ellipsis
        ("\u200b", ""),    # zero-width space
        ("\u00a0", " "),   # non-breaking space
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


# ── Resume parser ─────────────────────────────────────────────────────────────

def _parse_experience_section(content: str) -> list[dict]:
    """Parse the Experience section text into a list of role dicts."""
    entries = []
    # Split on lines that start with '**' (role headers)
    blocks = re.split(r"\n(?=\*\*)", content.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # Match: **Title | Company | Location** *(dates)*
        m = re.match(r"\*\*(.+?)\*\*\s*\*\((.+?)\)\*", block)
        if not m:
            continue
        parts = [p.strip() for p in m.group(1).split(" | ")]
        title    = parts[0] if parts else ""
        company  = parts[1] if len(parts) > 1 else ""
        location = parts[2] if len(parts) > 2 else ""
        dates    = m.group(2).strip()
        bullets  = re.findall(r"^- (.+)$", block, re.MULTILINE)
        entries.append({
            "title": title,
            "company": company,
            "location": location,
            "dates": dates,
            "bullets": bullets,
        })
    return entries


def _parse_projects_section(content: str) -> list[dict]:
    """Parse the Projects section text into a list of project dicts."""
    projects = []
    blocks = re.split(r"\n(?=\*\*)", content.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        m = re.match(r"\*\*([^*]+)\*\*", block)
        if not m:
            continue
        name    = m.group(1).strip()
        bullets = re.findall(r"^- (.+)$", block, re.MULTILINE)
        projects.append({"name": name, "bullets": bullets})
    return projects


def parse_resume(resume_md: str) -> dict:
    """Parse a markdown resume into a structured dict."""
    # Name + email from header block
    name_m  = re.search(r"^# (.+)$", resume_md, re.MULTILINE)
    email_m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", resume_md)
    name  = name_m.group(1).strip()  if name_m  else CANDIDATE["name"]
    email = email_m.group(0).strip() if email_m else CANDIDATE["email"]

    # Split into ## sections
    parts = re.split(r"^## (.+)$", resume_md, flags=re.MULTILINE)
    secs: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        secs[parts[i].strip()] = parts[i + 1].strip() if i + 1 < len(parts) else ""

    return {
        "name":       name,
        "email":      email,
        "summary":    secs.get("Summary", ""),
        "skills":     secs.get("Skills", ""),
        "education":  secs.get("Education", ""),
        "experience": _parse_experience_section(secs.get("Experience", "")),
        "projects":   _parse_projects_section(secs.get("Projects", "")),
    }


# ── LLM tailoring functions ───────────────────────────────────────────────────

def extract_keywords(jd: str) -> list[str]:
    """Extract 15-20 high-value ATS keywords from the JD."""
    if DRY_RUN:
        return list(_DRY_KEYWORDS)

    prompt = f"""Extract 15-20 high-value ATS keywords from this job description.
Focus on: technical skills, tools, methodologies, domain terms, and role-specific soft skills.
Prefer multi-word phrases over single words where possible.

Return ONLY a JSON object:
{{"keywords": ["keyword1", "keyword2", ...]}}

Job Description:
{jd}"""
    result, _ = _call_llm(prompt)
    return result.get("keywords", list(_DRY_KEYWORDS[:15]))


def rewrite_summary(base_summary: str, jd: str, keywords: list[str]) -> str:
    """Rewrite the Summary injecting top JD keywords. Hard cap: exactly 3 sentences."""
    if DRY_RUN:
        return _DRY_SUMMARY

    kw_str = ", ".join(keywords[:10])
    prompt = f"""Rewrite this professional summary to target the job description below.
Inject 5-7 of the listed keywords naturally.

HARD RULES — violating any of these makes the output unusable:
- Exactly 3 sentences. No more, no less.
- Sentence 1: [Role] with hands-on experience [specific work done] using [tools].
- Sentence 2: Strong focus on [domain strengths relevant to JD].
- Sentence 3: Proven ability to [business value / outcome delivered].
- No "I" pronoun. No education mentions. No fabricated skills.
- NEVER add skills the candidate doesn't actually have.

Keywords to inject (most relevant only): {kw_str}

Original Summary:
{base_summary}

Job Description (target):
{jd[:1500]}

Return ONLY a JSON object:
{{"summary": "sentence 1. sentence 2. sentence 3."}}"""
    result, _ = _call_llm(prompt)
    return result.get("summary", base_summary)


def reframe_experience(experience: list[dict], jd: str, keywords: list[str]) -> list[dict]:
    """Reframe experience bullets using JD vocabulary. 2-3 bullets per role."""
    if DRY_RUN:
        return experience

    kw_str = ", ".join(keywords[:12])
    exp_text = ""
    for i, role in enumerate(experience):
        exp_text += f"\nRole {i}: {role['title']} at {role['company']}\n"
        for b in role["bullets"]:
            exp_text += f"  - {b}\n"

    prompt = f"""Reframe these work experience bullets to better match the job description.
Use JD vocabulary where authentic. NEVER fabricate skills or experience — only reformulate.

RULES:
- Preserve the exact bullet count for each role. If a role has 3 bullets, return 3 bullets.
- Each bullet: past-tense action verb → what was built/done → tools used → quantified impact.
- Do NOT merge bullets or drop any. Do NOT add new bullets that weren't in the original.
- Keep bullets to 1-2 lines max (no run-on sentences).

JD Keywords: {kw_str}

Current Experience:
{exp_text}

Job Description excerpt:
{jd[:1500]}

Return ONLY a JSON object:
{{
  "roles": [
    {{"index": 0, "bullets": ["reframed bullet 1", "reframed bullet 2", "reframed bullet 3"]}},
    {{"index": 1, "bullets": ["reframed bullet 1", "reframed bullet 2"]}}
  ]
}}"""
    result, _ = _call_llm(prompt)

    reframed = [dict(r) for r in experience]
    for role_update in result.get("roles", []):
        idx = role_update.get("index", -1)
        new_bullets = role_update.get("bullets", [])
        if 0 <= idx < len(reframed) and new_bullets:
            reframed[idx] = {**reframed[idx], "bullets": new_bullets[:3]}
    return reframed


def compute_projected_score(jd: str, resume_md: str, current_score: float) -> int:
    """
    Realistic post-tailor score ceiling — no LLM required.

    Tailoring can only reformulate *existing* experience using JD vocabulary.
    It cannot fabricate skills. The honest maximum gain is therefore bounded by
    a structural cap:

        max_honest_boost = (100 - current_score) * 0.30

    This says: at most 30% of the remaining distance to 100 is fixable via
    presentation. The other 70% is genuine skills/experience gap that no
    amount of wordsmithing can close.

    That ceiling is then scaled by how many top JD keywords are actually
    missing from the resume (the presentation gap fraction).

    Examples at 30% cap:
        60% score, 80% keyword gap → boost = 0.8 * (40 * 0.30) = 9.6  → ~70%
        86% score, 60% keyword gap → boost = 0.6 * (14 * 0.30) = 2.5  → ~89%
        92% score, 40% keyword gap → boost = 0.4 *  (8 * 0.30) = 0.96 → ~93%

    A 60% resume will never project to 95% — that would require skills the
    candidate doesn't have.
    """
    from collections import Counter

    STOP = {
        "the", "a", "an", "and", "or", "for", "in", "on", "at", "to", "of",
        "with", "is", "are", "was", "were", "be", "been", "have", "has", "do",
        "does", "did", "will", "would", "could", "should", "may", "might",
        "must", "can", "this", "that", "these", "those", "we", "you", "our",
        "your", "their", "its", "as", "by", "from", "not", "but", "if", "so",
        "than", "also", "work", "team", "ability", "strong", "years", "year",
        "role", "position", "experience", "including", "required", "preferred",
        "working", "using", "across", "within", "new", "all", "any", "more",
        "most", "some", "good", "great", "high", "key", "make", "use", "need",
        "based", "related", "other", "each", "into", "about", "well", "both",
        "such", "help", "what", "how", "who", "where", "when", "which",
    }

    def _tokens(text: str) -> list[str]:
        return [
            w for w in re.findall(r"\b[a-z][a-z0-9+#]{2,}\b", text.lower())
            if w not in STOP
        ]

    jd_freq    = Counter(_tokens(jd))
    resume_set = set(_tokens(resume_md))

    top_jd = jd_freq.most_common(25)
    if not top_jd:
        return int(current_score)

    total_w   = sum(v for _, v in top_jd)
    missing_w = sum(v for w, v in top_jd if w not in resume_set)
    gap = missing_w / total_w  # 0.0 = fully covered, 1.0 = fully missing

    # Structural cap: even perfect tailoring can only close 30% of the remaining gap
    max_honest_boost = max(100 - current_score, 0) * 0.30
    boost = gap * max_honest_boost

    return max(int(current_score + boost), int(current_score))


# ── HTML builder helpers ──────────────────────────────────────────────────────

def _md_to_inline_html(text: str) -> str:
    """Convert markdown bold/italic to HTML inline elements."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
    return text


def _build_experience_html(experience: list[dict], max_bullets: int) -> str:
    html = ""
    for role in experience:
        loc_html = (
            f' &nbsp;<span class="role-location">| {role["location"]}</span>'
            if role["location"] else ""
        )
        bullets_html = "".join(
            f"<li>{normalize_ats(b)}</li>" for b in role["bullets"][:max_bullets]
        )
        html += f"""<div class="role">
  <div class="role-header">
    <div class="role-left">
      <span class="role-title">{role["title"]}</span>
      &nbsp;&middot;&nbsp;
      <span class="role-company">{role["company"]}</span>{loc_html}
    </div>
    <div class="role-dates">{role["dates"]}</div>
  </div>
  <ul>{bullets_html}</ul>
</div>"""
    return html


def _build_projects_html(projects: list[dict], max_projects: int) -> str:
    html = ""
    for proj in projects[:max_projects]:
        bullets_html = "".join(
            f"<li>{normalize_ats(b)}</li>" for b in proj["bullets"]
        )
        html += f"""<div class="project">
  <div class="project-name">{proj["name"]}</div>
  <ul>{bullets_html}</ul>
</div>"""
    return html


def _build_education_html(education: str) -> str:
    edu = _md_to_inline_html(education)
    edu = edu.replace("\n", "<br>")
    return f'<div class="education-entry">{edu}</div>'


def _build_skills_html(skills: str) -> str:
    sk = _md_to_inline_html(skills)
    sk = sk.replace("\n", "<br>")
    return sk


def _tailored_text(data: dict) -> str:
    """Plain-text resume from tailored data — passed to LLM for post-tailor re-scoring."""
    lines = [
        f"# {data['name']}",
        "",
        "## Summary",
        data["summary"],
        "",
        "## Experience",
    ]
    for role in data["experience"]:
        loc = f" | {role['location']}" if role["location"] else ""
        lines.append(f"**{role['title']} | {role['company']}{loc}** ({role['dates']})")
        for b in role["bullets"]:
            lines.append(f"- {b}")
    lines += ["", "## Skills", data["skills"]]
    return "\n".join(lines)


def _build_html(
    data: dict,
    margin: float,
    body_font: int,
    header_font: int,
    max_bullets: int,
    max_projects: int,
) -> str:
    """Render the cv-template.html with all data and fitting parameters."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    replacements = {
        "NAME":       data["name"],
        "EMAIL":      data["email"],
        "PHONE":      data["phone"],
        "LINKEDIN":   data["linkedin"],
        "GITHUB":     data["github"],
        "SUMMARY":    normalize_ats(data["summary"]),
        "EXPERIENCE": _build_experience_html(data["experience"], max_bullets),
        "PROJECTS":   _build_projects_html(data["projects"], max_projects),
        "EDUCATION":  _build_education_html(data["education"]),
        "SKILLS":     _build_skills_html(data["skills"]),
        "MARGIN":     str(margin),
        "BODY_FONT":  str(body_font),
        "HEADER_FONT": str(header_font),
        "SMALL_FONT": str(body_font - 1),
    }

    for key, value in replacements.items():
        template = template.replace(f"@@{key}@@", value)

    return template


# ── PDF rendering ─────────────────────────────────────────────────────────────

def _render_pdf_raw(html_path: str) -> bytes:
    """Render an HTML file to PDF bytes using Playwright chromium."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"file://{html_path}", wait_until="networkidle")
        pdf_bytes = page.pdf(format="Letter", print_background=True)
        browser.close()
    return pdf_bytes


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Count pages in a PDF by reading /Count from the Pages dictionary."""
    matches = re.findall(rb"/Count\s+(\d+)", pdf_bytes)
    if matches:
        return max(int(m) for m in matches)
    # Fallback: count individual /Type /Page entries (not /Pages container)
    pages = re.findall(rb"/Type\s*/Page(?!s)", pdf_bytes)
    return max(len(pages), 1)


# ── One-page fitting strategy ─────────────────────────────────────────────────
# Applied in order until the rendered PDF fits on exactly 1 page.
# Priority: compress margins first → reduce font → only touch content as last resort.
# Content trimming is capped at 4→3 bullets (never below 3) and 3→2 projects.
_FITTING_CONFIGS = [
    # (margin_in, body_font_px, header_font_px, max_bullets_per_role, max_projects)
    (0.60, 11, 13, 99, 3),  # start: full bullets, full margin
    (0.55, 11, 13, 99, 3),
    (0.50, 11, 13, 99, 3),
    (0.45, 11, 13, 99, 3),
    (0.40, 11, 13, 99, 3),  # minimum margin
    (0.40, 10, 11, 99, 3),  # reduce font
    (0.40, 10, 11,  3, 3),  # last resort: trim 4→3 bullets per role
    (0.40, 10, 11,  3, 2),  # last resort: drop to 2 projects
]


# ── Main entry point ──────────────────────────────────────────────────────────

def tailor_resume(job_id: int) -> tuple[str, int]:
    """
    Tailor the resume for the given job_id and render a one-page ATS PDF.

    Returns:
        (pdf_path, keyword_coverage_pct)
    """
    # 1. Load job + resume
    job = get_job_by_id(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found in database")

    role       = job.get("assigned_resume_type", "DA")
    resume_md  = get_resume(role)
    if not resume_md:
        raise ValueError(f"No resume found for role type: {role}")

    jd      = job.get("job_description", "")
    company = job.get("company_name", "unknown")

    # 2. LLM tailoring
    keywords   = extract_keywords(jd)
    parsed     = parse_resume(resume_md)
    summary    = rewrite_summary(parsed["summary"], jd, keywords)
    experience = reframe_experience(parsed["experience"], jd, keywords)

    # 3. Compute keyword coverage (summary + reframed bullets)
    bullet_text = " ".join(
        b for role in experience for b in role["bullets"]
    )
    searchable = (summary + " " + bullet_text).lower()
    kw_hits    = sum(1 for kw in keywords if kw.lower() in searchable)
    kw_pct     = round(100 * kw_hits / len(keywords)) if keywords else 0

    # 4. Assemble data dict
    data = {
        "name":       CANDIDATE["name"],
        "email":      CANDIDATE["email"],
        "phone":      CANDIDATE["phone"],
        "linkedin":   CANDIDATE["linkedin"],
        "github":     CANDIDATE["github"],
        "summary":    summary,
        "experience": experience,
        "projects":   parsed["projects"],
        "education":  parsed["education"],
        "skills":     parsed["skills"],
    }

    # 5. Set up output paths
    OUTPUT_DIR.mkdir(exist_ok=True)
    date_str     = datetime.now().strftime("%Y-%m-%d")
    company_slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    pdf_path     = str(OUTPUT_DIR / f"cv-deepansh-{company_slug}-{date_str}.pdf")
    html_tmp     = f"/tmp/cv-deepansh-{company_slug}.html"

    # 6. One-page fitting loop
    final_pdf_bytes = None
    for margin, body_f, header_f, max_b, max_p in _FITTING_CONFIGS:
        html = _build_html(data, margin, body_f, header_f, max_b, max_p)
        with open(html_tmp, "w", encoding="utf-8") as f:
            f.write(html)

        pdf_bytes = _render_pdf_raw(html_tmp)
        final_pdf_bytes = pdf_bytes

        if _count_pdf_pages(pdf_bytes) <= 1:
            break  # fits — stop here

    # 7. Write PDF
    with open(pdf_path, "wb") as f:
        f.write(final_pdf_bytes)

    # 8. Post-tailor ATS re-score (LLM — skipped in DRY_RUN)
    tailored_score: float | None = None
    try:
        tailored_score, _ = _score_resume(company, jd, _tailored_text(data))
    except Exception:
        pass  # non-fatal — score stays None, shown as missing in UI

    # 9. Update DB
    update_tailor_result(job_id, pdf_path, "Done", tailored_score)

    return pdf_path, kw_pct, tailored_score
