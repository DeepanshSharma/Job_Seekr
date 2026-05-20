# Job_Seekr — Phase 2 Execution Plan

**Status:** ✅ COMPLETE
**Goal:** Tailoring engine — LLM rewrites resume against JD, renders a one-page ATS PDF via Playwright.

---

## What Was Built

### `tailor.py` — Full Tailoring Pipeline

Entry point: `tailor_resume(job_id: int) -> tuple[str, int, float]`

Steps executed in order:
1. Load job from DB + base resume from SQLite
2. **RAG retrieval** — embed JD, retrieve top-6 relevant resume chunks from ChromaDB
3. `analyze_fit(jd, resume_context)` — single LLM call: competency map + gaps + ATS keywords
4. `rewrite_summary(base_summary, fit_map)` — LLM rewrites 3-sentence summary with JD vocabulary
5. `reframe_experience(experience, fit_map)` — LLM reframes bullets using fit map, preserving bullet count
6. `evaluate_resume(tailored_text, original_resume, fit_map)` — keyword coverage % + hallucination check
7. Assemble data dict → fill `cv-template.html`
8. One-page fitting loop (margin compression → font reduction → bullet trim)
9. Playwright renders HTML → Letter PDF
10. Post-tailor re-score (fit + ATS on final tailored text) → saved to DB

### `templates/cv-template.html`
- Fonts: Space Grotesk (headings) + DM Sans (body) via Google Fonts
- Teal section headers, purple company names, gradient header line
- `@@PLACEHOLDER@@` tokens filled by `tailor.py`
- CSS `@page { size: Letter; }` — Playwright enforces page count

### One-Page Fitting Strategy

Applied in order until PDF fits on exactly 1 page:

| Step | What changes |
|------|-------------|
| 1 | Margin 0.60in → 0.55 → 0.50 → 0.45 → 0.40in |
| 2 | Body font 11px → 10px; header font 13px → 11px |
| 3 | Max bullets per role: drop to 3 |
| 4 | Max projects: drop from 3 to 2 |

Never goes below 0.40in margin or 9.5px body font.

### `eval.py` — Custom Evaluator (added in AI Refactor phase)
- **Keyword coverage** — what % of JD's required keywords appear in the tailored resume
- **Hallucination detection** — flags tech terms added by the LLM that weren't in the original resume
- No LLM needed — pure text analysis, fast and fully explainable

### `db.py` additions
- `tailored_resume_path TEXT` — path to generated PDF
- `tailor_status TEXT` — 'Pending' | 'Done' | 'Error'
- `tailored_match_score REAL` — post-tailor combined score
- `update_tailor_result()`, `get_tailor_status()`, `get_job_by_id()`

### `app.py` additions
- "Tailor Resume" button per Passed/Low Match job (gated: only 65-90% match score)
- Spinner during render (~30s), success shows keyword coverage % + score improvement
- Download PDF button on completion
- "Already excellent — skip" shown for >90% matches

---

## ATS Rules (Non-Negotiable)
- Single-column layout — no sidebars
- Standard section headers
- UTF-8, selectable text
- ATS character normalization (em-dash → hyphen, smart quotes → straight, etc.)
- Keywords distributed: Summary (top 5), first bullet of each role, Skills section

---

## Phase 2 Verification — Confirmed Working
- [x] "Tailor Resume" button appears for eligible jobs in Triage Board
- [x] Spinner → PDF generated → download button shown
- [x] PDF is exactly one page (fitting loop working)
- [x] Keyword coverage % reported
- [x] ATS normalization applied before render
- [x] Post-tailor re-score saved to DB and shown in UI

---

## Key Decisions Made in Phase 2

| Decision | Choice | Reason |
|----------|--------|--------|
| PDF renderer | Playwright (Chromium) | Already needed for Phase 4; no extra dep |
| One-page constraint | Hard — non-negotiable | Recruiter standard |
| RAG in tailoring | Top-6 chunks via ChromaDB | More focused LLM context = better tailoring |
| Hallucination check | Tech-term list (no LLM) | Fast, transparent, explainable |
| Cover letter | Not in scope | Deferred — adds complexity without clear Phase 2 value |
