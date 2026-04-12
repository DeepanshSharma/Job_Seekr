# Job_Seekr V2 - Phase 1 Execution Plan

**Status:** Ready for Execution.
**Goal:** Build the UI Dashboard to display jobs, build a basic local database, and construct the Gemini AI scoring logic using a mock payload (No Apify, no Auto-Applying yet). Focus strictly on Python/Streamlit logic.

---

## 1. Local Database (SQLite)
Create `db.py` to initialize `jobseeker.db` using Python's built-in `sqlite3`.
**Schema:**
- `resumes`: `id`, `role_type` (DA, BA, AI), `content` (Markdown).
- `jobs`: `id`, `apify_url`, `company_name`, `job_title`, `job_description`, `posted_at`, `status` (Pending, Passed, Rejected), `match_score`, `assigned_resume_type`.

## 2. Streamlit Dashboard (The UI)
Create `app.py`.
- **View 1 (Resumes):** A simple text area to paste and save the base markdown content for DA, BA, or AI.
- **View 2 (Triage Board):** A clean data table (`st.dataframe` or custom columns) displaying active jobs. Must clearly show the Job Title, Company, Match Score (0-100%), and a status badge.
- **Action Buttons:** A "Run Pipeline (Mock)" button that triggers the backend logic on a dummy JSON file.

## 3. Semantic Engine (`gemini_orchestrator.py`)
This is the "Brain" for Phase 1, operating directly on a `mock_jobs.json`.
1. **Fetch & Freshness Filter:** Load mock jobs. Drop anything `> 3 days` old.
2. **OPT Filter Pipeline:** Send the JD to Gemini. Ask: *"Does this explicitly deny visa sponsorship or require US Citizenship?"*. If yes, set status to `Rejected` in SQLite.
3. **Semantic Match Pipeline:** For the surviving jobs, send the JD + the assigned Base Resume content to Gemini. Ask: *"Acting as an ATS, score this resume against this JD from 0 to 100 based on core hard skills. Return only the JSON score."*
4. Select only the jobs where `match_score >= 80`. Update the SQLite DB.

## Phase 1 Verification Checkpoint
To successfully close Phase 1, we must:
1. Run `streamlit run app.py` successfully.
2. Paste the DA resume markdown into the form.
3. Hit "Run Pipeline" and confirm the pipeline parses the mock data, drops the non-sponsoring jobs, and properly renders the `>80%` matched jobs in the Streamlit UI with their calculated Gemini scores.
