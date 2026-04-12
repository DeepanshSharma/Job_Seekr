# Job_Seekr V2 - Phase 2 Execution Plan

**Status:** Building
**Goal:** Tailoring Engine — take a Passed job from the Triage Board, LLM-tailor the matching resume against the JD, and render a one-page ATS PDF via Playwright.

---

## Decisions Locked In

| Decision | Choice | Reason |
|----------|--------|--------|
| PDF renderer | Playwright (chromium) | Already needed for Phase 4 auto-apply; no extra dep |
| One-page constraint | Hard — non-negotiable | Recruiter standard; must always be one page |
| Margin lever | Compress 0.6in → 0.4in min | Primary fit strategy before font/content cuts |
| Cover letter | TBD — not confirmed yet | Will confirm before build |
| Design baseline | Deepansh's existing DOCX | Match this if custom design doesn't clearly win |

---

## Files to Build

### 1. `tailor.py` — LLM Tailoring Engine

Responsibilities:
- `extract_keywords(jd: str) -> list[str]` — Groq extracts 15-20 JD keywords
- `rewrite_summary(base_resume: str, jd: str, keywords: list) -> str` — Groq rewrites Professional Summary
- `reframe_bullets(role_bullets: list, jd: str, keywords: list) -> list` — Groq reframes bullets using JD vocabulary
- `build_competencies(keywords: list) -> list` — selects 6-8 keyword phrases for competency grid
- `tailor_resume(job_id: int) -> str` — orchestrates all the above, fills template, calls Playwright
- Returns: path to PDF in `output/`

### 2. `templates/cv-template.html` — HTML Resume Template

Python f-string template (no Jinja2 dependency) with placeholder slots:
- `{name}`, `{email}`, `{phone}`, `{linkedin}`, `{github}`
- `{summary}` — tailored Professional Summary paragraph
- `{competencies}` — list of 6-8 keyword phrases for flex-grid
- `{experience}` — list of roles with company, title, dates, bullets
- `{projects}` — top 2-3 most relevant projects
- `{education}` — degrees + certifications
- `{skills}` — condensed skills row

Design: Space Grotesk + DM Sans (Google Fonts), teal section headers, purple company names, gradient header line.
One-page enforced: CSS `@page { size: Letter; margin: 0.6in; }` — Playwright checks page count after render; re-renders with tighter margins if > 1 page.

### 3. `app.py` additions (Triage Board)

- **"Tailor Resume"** button per Passed job row
- On click: spinner → `tailor_resume(job_id)` → `st.download_button` linking to PDF
- On error: show inline error, log to DB
- New columns used: `tailor_status`, `tailored_resume_path`

### 4. `db.py` additions

```python
# New columns (add via ALTER TABLE migration in init_db):
# tailored_resume_path TEXT
# tailor_status TEXT DEFAULT 'Pending'

def update_tailor_result(job_id: int, pdf_path: str): ...
def get_tailor_status(job_id: int) -> dict: ...
```

---

## One-Page Fitting Strategy (ordered)

Apply each step and re-render until it fits on exactly one page:

1. Compress margins: 0.6in → 0.55in → 0.5in → 0.45in → 0.4in (never below 0.4in)
2. Reduce font size: body 11px → 10px; headers 13px → 11px (never below 9.5px body)
3. Cut bullets to 1 line each; remove lowest-priority bullets
4. Show 2 projects instead of 3

---

## Build Order

1. `db.py` — add new columns + helper functions
2. `templates/cv-template.html` — build and visually verify in browser
3. `tailor.py` — LLM stage first (DRY_RUN), then Playwright render + page-count check
4. `app.py` — wire "Tailor Resume" button + download link

---

## Phase 2 Verification Checkpoint

1. Click "Tailor Resume" on a Passed job in the Triage Board
2. Spinner shows, then success with download link
3. PDF is exactly one page, correct name/contact, tailored bullets using JD vocabulary
4. Keyword coverage % reported (target ≥ 70%)
5. No smart quotes, em-dashes, or zero-width chars in the PDF (ATS normalization confirmed)
