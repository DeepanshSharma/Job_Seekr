# Job_Seekr — Phase 1 Execution Plan

**Status:** ✅ COMPLETE
**Goal:** SQLite DB, Streamlit dashboard, and the triage pipeline using mock data.

---

## What Was Built

### `db.py`
- `resumes` table — stores DA/BA/AI base resumes as markdown
- `jobs` table — full job record including status, scores, legitimacy, source metadata
- `init_db()` — creates tables + runs ALTER TABLE migrations for new columns
- `seed_resumes_if_empty()` — auto-loads `resumes/*.md` on first run
- CRUD: `insert_job`, `get_all_jobs`, `get_resume`, `save_resume`, `clear_jobs`

### `app.py` — Triage Board (Page 1)
- "Run Pipeline" button → calls `run_pipeline_on_pending()`
- Displays jobs grouped by status: Passed (≥80%) · Low Match · Rejected · Stale · Error
- Shows Fit score + ATS score per job, legitimacy badge, Tailor Resume action

### Triage Pipeline (originally `gemini_orchestrator.py`, now `pipeline.py` + `llm.py`)
1. **Freshness** — drop if posted >3 days ago
2. **OPT Filter** — LLM: does JD explicitly ban visa sponsorship / require citizenship?
3. **Legitimacy** — LLM: annotates job trustworthiness (never blocks)
4. **Fit Score** — LLM: recruiter-lens conceptual match score (0-100)
5. **ATS Score** — LLM: keyword surface-match score (0-100)
6. **Decision** — combined score (70% fit + 30% ATS) → Passed / Low Match

### Mock Data
- `data/mock_jobs.json` — 8 jobs across Stripe, Deloitte, Cohere, Google DeepMind, etc.
- DRY_RUN=true in `.env` skips all API calls, uses preset scores for fast iteration

---

## Phase 1 Verification — Confirmed Working

- [x] `streamlit run app.py` starts without errors
- [x] Resume Manager loads DA/BA/AI resumes from `resumes/` folder
- [x] "Run Pipeline" on Triage Board processes mock jobs
- [x] Passed jobs (≥80%) shown with Fit + ATS breakdown
- [x] OPT-rejected jobs shown in Rejected expander
- [x] Stale jobs filtered correctly

---

## Key Decisions Made in Phase 1

| Decision | Choice | Reason |
|----------|--------|--------|
| LLM primary | Groq (`llama-3.3-70b-versatile`) | 14,400 req/day free, fast |
| LLM fallback | Gemini (`gemini-2.0-flash`) | When Groq hits rate limits |
| Score threshold | 80% | Practical balance of precision vs. volume |
| Dual scoring | Fit (recruiter) + ATS (keyword) | Covers both human and automated screening |
| Legitimacy | Annotates only, never blocks | Avoids false rejections on real postings |
