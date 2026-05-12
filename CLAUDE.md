# Job_Seekr — Claude Code Instructions

This is a Python-native job application automation platform.
Stack: Streamlit UI · SQLite · Groq (primary LLM) + Gemini (fallback) · LangGraph (multi-agent pipeline) · ChromaDB + sentence-transformers (RAG) · Pydantic (structured outputs) · Playwright (PDF render + Phase 4 auto-apply)

## Project Structure

```
Job_Seekr/
├── app.py                    # Streamlit dashboard (entry point)
├── db.py                     # SQLite schema + CRUD + llm_logs table
├── llm.py                    # LLM clients, call_llm(), Pydantic models, judgment functions
├── rag.py                    # ChromaDB: chunk resumes, embed, index, retrieve
├── pipeline.py               # LangGraph 7-agent triage graph
├── tailor.py                 # LLM tailoring engine + Playwright PDF renderer
├── eval.py                   # Custom evaluator: keyword coverage + hallucination check
├── sourcer.py                # Track A (ATS APIs) + Track B (Apify) sourcing engine
├── templates/
│   └── cv-template.html      # HTML resume template for Playwright
├── data/mock_jobs.json       # Mock job data for dev/testing
├── resumes/                  # Base markdown resumes (da, ba, ai)
├── output/                   # Generated PDFs go here
├── chroma_db/                # ChromaDB persistent vector store (gitignored)
├── requirements.txt
├── .env                      # API keys — never commit
└── venv/                     # Python virtual environment
```

## Running the App

```bash
source venv/bin/activate
streamlit run app.py
```

Always activate venv before running Python commands.

## Environment Variables (.env)

```
GEMINI_API_KEY=...
GROQ_API_KEY=...
DRY_RUN=false        # Set true during dev to skip API calls
```

## LLM Usage Rules

- **Primary:** Groq (`llama-3.3-70b-versatile`) — 14,400 req/day free
- **Fallback:** Gemini (`gemini-2.0-flash`) — only used when Groq fails
- **DRY_RUN=true** — skips all API calls, uses preset scores. Use during dev.
- All LLM calls go through `_call_llm()` in `gemini_orchestrator.py`
- Never call Groq/Gemini directly from `app.py`

## Database

SQLite at `jobseeker.db` (gitignored). Schema in `db.py`:
- `resumes` — role_type (DA/BA/AI), content (markdown)
- `jobs` — full job record including status, match_score, legitimacy_score, filter_reason

## Pipeline Stages (Phase 1)

Each job goes through in order:
1. **Freshness** — drop if posted >3 days ago
2. **OPT Filter** — Groq: does JD ban visa sponsorship / require citizenship?
3. **Legitimacy** — Groq: is this a real, specific, trustworthy job posting?
4. **Scoring** — Groq: ATS match score 0-100 against the assigned resume

Jobs below 80% match are shown as Low Match, not hidden.

---

## Skill: /pdf — ATS-Optimized Resume PDF Generation

**Trigger:** User says "tailor resume", "generate PDF", "create CV for [company]"

### ONE PAGE — HARD CONSTRAINT

**The output PDF must fit on exactly one page. This is non-negotiable.**

Fitting strategy — apply in order until it fits on one page:
1. **Compress margins** — start at 0.6in, reduce in 0.05in steps down to 0.4in minimum
2. **Reduce font size** — body from 11px to 10px; section headers from 13px to 11px
3. **Trim bullets** — keep each bullet to ≤ 3 line; remove lowest-priority bullets
4. **Reduce projects shown** — drop from top 3 to top 2 if still overflowing

Never go below 0.4in margin or 9.5px body font — illegible text defeats the point.

**Design baseline:** Deepansh's existing DOCX resume is clean, one-page, Word-style. If the designed output is not clearly an improvement, match that style exactly — no forced "design" upgrades.

### Pipeline

1. Load the assigned base resume from `resumes/{role}.md`
2. Accept JD as text or URL (WebFetch if URL)
3. Extract 15-20 keywords from the JD
4. Detect role archetype → adapt framing
5. Rewrite Professional Summary injecting top JD keywords (authentic only — never invent)
6. Select top 3 most relevant projects reordered by JD relevance
7. Reorder/reframe experience bullets using exact JD vocabulary (2-3 bullets per role)
8. Build Core Competencies grid (6-8 keyword phrases from JD requirements)
9. Apply ATS character normalization (see below)
10. Render HTML using `templates/cv-template.html` with tailored data injected
11. Write rendered HTML to `/tmp/cv-deepansh-{company}.html`
12. Use Playwright (chromium) to render PDF:
    - `page.pdf(format="Letter", print_background=True)`
    - Check page count — if > 1, apply fitting strategy above and re-render
13. Save to `output/cv-deepansh-{company}-{YYYY-MM-DD}.pdf`
14. Report: PDF path, page count confirmed, keyword coverage %

### ATS Rules (non-negotiable)

- Single-column layout — no sidebars, no parallel columns
- Standard section headers: "Professional Summary", "Work Experience", "Education", "Skills", "Projects"
- No text in images/SVGs
- UTF-8, selectable text (not rasterized)
- No nested tables
- Keywords distributed: Summary (top 5), first bullet of each role, Skills section

### ATS Character Normalization (apply before PDF render)

```python
text = text.replace('\u2014', '-')   # em-dash → hyphen
text = text.replace('\u2013', '-')   # en-dash → hyphen
text = text.replace('\u2018', "'")   # left single quote → apostrophe
text = text.replace('\u2019', "'")   # right single quote → apostrophe
text = text.replace('\u201c', '"')   # left double quote → standard
text = text.replace('\u201d', '"')   # right double quote → standard
text = text.replace('\u2026', '...')  # ellipsis → three dots
text = text.replace('\u200b', '')    # zero-width space → remove
text = text.replace('\u00a0', ' ')   # non-breaking space → regular space
```

### PDF Design Spec

- **Fonts:** Space Grotesk (headings, 600-700) + DM Sans (body, 400-500) — via Google Fonts @import
- **Header:** Name in Space Grotesk 24px bold + 2px gradient line `linear-gradient(to right, hsl(187,74%,32%), hsl(270,70%,45%))` + contact row (DM Sans 10px)
- **Section headers:** Space Grotesk 12px, uppercase, letter-spacing 0.08em, color `hsl(187,74%,32%)` (teal)
- **Body:** DM Sans 11px, line-height 1.45
- **Company names:** bold, color `hsl(270,70%,45%)` (purple)
- **Default margins:** 0.6in (all sides) — compress toward 0.4in minimum to fit one page
- **Background:** pure white `#ffffff`
- **Bullets:** `•` character, left indent 12px max

### Section Order (6-second recruiter scan optimized)

1. Header (name, 2px gradient line, contact row: email · phone · LinkedIn · GitHub/portfolio)
2. Professional Summary (3-4 lines, keyword-dense)
3. Core Competencies (6-8 phrase flex-grid, 2-3 columns)
4. Work Experience (reverse chronological, 2-3 bullets per role max)
5. Projects (top 2-3 most relevant, 1-2 bullets each)
6. Education & Certifications
7. Skills (single compact row or two-column grid)

### Keyword Injection — Ethical Rules

Reformulate real experience using JD vocabulary. NEVER add skills the candidate doesn't have.

Examples:
- JD says "RAG pipelines", CV says "LLM workflows with retrieval" → "RAG pipeline design and LLM orchestration"
- JD says "stakeholder management", CV says "collaborated with team" → "stakeholder management across engineering and business"
- JD says "MLOps", CV says "error handling and observability" → "MLOps: evals, error handling, cost monitoring"

---

## Skill: /interview-prep — Company-Specific Interview Intelligence

**Trigger:** User says "prep for interview at [company]", "interview prep [company]"

### Steps

1. Read the job's evaluation report from SQLite (match score, reasoning, role type)
2. Run WebSearch queries:
   - `"{company} {role} interview questions site:glassdoor.com"`
   - `"{company} interview process site:teamblind.com"`
   - `"{company} {role} interview site:leetcode.com/discuss"`
   - `"{company} engineering blog"`
3. Extract: actual questions asked, round structure, difficulty, timeline, comp details
4. Build report sections:
   - **Process Overview** — rounds, duration, difficulty rating, positive experience rate
   - **Round-by-Round Breakdown** — what each round tests, reported questions with sources
   - **Likely Questions** — Technical / Behavioral / Role-Specific / Background Red Flags
   - **Technical Prep Checklist** — max 10 items, prioritized by frequency in reviews
   - **Company Signals** — vocabulary to use, values they screen for, questions to ask them
5. Save report to `output/interview-prep-{company}-{YYYY-MM-DD}.md`

### Rules

- **NEVER fabricate questions.** Label inferred content `[inferred from JD]`
- **NEVER invent Glassdoor ratings.** If data is sparse, say so explicitly
- Cite every question and stat with its source
- Be direct — this is a working document, not a pep talk

---

## Skill: /patterns — Rejection Pattern Analysis

**Trigger:** User says "analyze patterns", "what's working", "show me my application stats"

**Minimum data required:** 5+ jobs with status beyond "Pending" in SQLite.

### Steps

1. Query SQLite for all jobs with outcomes (Passed, Rejected, Low Match, Stale, Error)
2. Compute:
   - **Conversion funnel** — count per status stage
   - **Score vs outcome** — avg/min/max score per outcome group
   - **OPT rejection rate** — what % were killed by visa filter
   - **Legitimacy rejection rate** — what % were killed by legitimacy filter
   - **Role type performance** — DA vs BA vs AI: which converts best
   - **Top blockers** — most frequent rejection reasons from `filter_reason`
   - **Stale rate** — what % of sourced jobs are too old
3. Output summary:
   - One-line stat (X jobs, Y passed, Z% pass rate)
   - Top 3 findings with actionable recommendations
   - Save full report to `output/pattern-analysis-{YYYY-MM-DD}.md`

### Outcome Classification

| Status | Outcome |
|--------|---------|
| Passed | Positive |
| Low Match | Borderline |
| Rejected | Negative (OPT/visa block) |
| Stale | Sourcing issue |
| Error | Pipeline issue |

### Recommendations format

```
1. [HIGH IMPACT] Action
   Reasoning: evidence from data
2. [MEDIUM IMPACT] Action
   Reasoning: evidence from data
```

---

## Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Done | Triage board — OPT filter + legitimacy + dual scoring (fit + ATS) |
| 2 | ✅ Done | Tailoring engine — `tailor.py` + `templates/cv-template.html` + Playwright PDF |
| 3 | ✅ Done | Live sourcing — Track A (ATS APIs) + Track B (Apify LinkedIn + Indeed) |
| AI Refactor | ✅ Done | LangGraph pipeline, RAG/ChromaDB, Pydantic structured outputs, eval layer |
| 4 | 🔜 Planned | Auto-apply — Playwright form filling + LinkedIn Easy Apply submission |

### Phase 2 Scope (confirmed)

**Files to build:**
- `tailor.py` — LLM tailoring engine (keyword extraction, summary rewrite, bullet reframing, competency grid)
- `templates/cv-template.html` — HTML template the tailor fills in; Playwright renders it to PDF
- Streamlit additions in `app.py` — "Tailor" button per Passed job, spinner, download link

**Constraints:**
- PDF renderer: Playwright (chromium) — already needed for Phase 4, no extra dependency
- One page: hard constraint — margin compression is the primary lever
- Cover letter: TBD — not yet confirmed for Phase 2 scope

**New DB columns for Phase 2** (add via ALTER in `db.py`):
- `tailored_resume_path TEXT` — path to generated PDF
- `cover_letter_path TEXT` — path to generated cover letter (if in scope)
- `tailor_status TEXT` — 'Pending' | 'Done' | 'Error'

## What NOT to do

- Don't call Gemini/Groq directly from `app.py` — use `gemini_orchestrator.py`
- Don't call Playwright directly from `app.py` — use `tailor.py`
- Don't commit `.env` or `jobseeker.db`
- Don't add features beyond the current phase without discussing first
- Don't mock the database — use real SQLite for all testing
- Don't change the LLM model names without checking current Groq/Gemini model availability
- Don't fabricate the detials while tailoring resumes.
- Ask wherever you have even a slight confusion or ambiguity.
