# Job_Seekr - Phase 1 Plan

**Status:** Ready for Execution
**Core Philosophy for Phase 1 UI:** *Function over Form.* We will build a very simple, clean Next.js UI. Beautification, UX design, animations, and complex styling will be deferred until the core functionalities of the app are proven.

---

## Phase 1 Scope: Foundation, Data Ingestion, & Routing Logic

The goal of Phase 1 is to build the pipeline that takes a raw job from Apify, filters it for OPT/Sponsorship, maps it to the correct resume, assigns it a priority tier, and saves it to a database visible on a barebones UI dashboard.

**Phase 1 DOES NOT include:** Browser automation, auto-applying scripts, or email verification handling. 

### 1. Database Layout & Schema (Supabase)
We will establish the foundational tables:
- **Resumes Table:** `id`, `user_id`, `role_type` (DA, AI, BA), `content/s3_url`.
- **Jobs Table:** `id`, `apify_source_url`, `company_name`, `job_description`, `location`, `sponsor_risk_flag`, `posted_at`.
- **Applications/Board Table:** `id`, `job_id`, `assigned_resume_id`, `priority_tier` (1,2,3), `edge_score`, `status` (e.g., Pending, Auto-Apply_Ready, Manual_Review).

### 2. Next.js Dashboard (Functional UI)
A simple React application to visualize our data flow. 
- **Upload Hub:** Extremely simple form to upload Resumes and tag them (e.g., "Data Analyst").
- **Triage Board:** A tabular or basic grid view showing Jobs ingested from Apify. Must clearly indicate: Job Title, Company, Priority Tier (1-3), pass/fail for F1-OPT sponsorship, and which Resume the system thinks we should use.

### 3. The Backend "Brain" (Filtering + Priority Tiering)
This is the core logic module of Phase 1.
- **Cost-Free Data Ingestion:** Create an API route that accepts a **MOCK Apify JSON payload** (a static file of 5-10 fake jobs). We will build the logic against this free mock data before hooking up the real Apify key.
- **Freshness Filter:** Immediately discard any job posting that is older than 3 days. Ghost jobs are a waste of resources.
- **OPT-LLM Filter:** Pass the job description to an LLM instruction: *Does this explicitly ban international applicants or refuse sponsorship?* If yes, drop from the list or flag as rejected.
- **Routing-LLM Filter:** Pass the safe jobs to a second prompt: *Compare this job to these 3 Resumes. Which fits best? Is this a Tier 1 (top tech), Tier 2 (mid), or Tier 3 (standard) company?*
- **Save State:** Write the finalized objects to Supabase.

## Phase 1 Validation Checkpoint
To successfully complete Phase 1, we must:
1. Boot the Next.js app locally.
2. Upload 2 dummy resumes (DA and AI) via the UI to Supabase.
3. Feed a static mock JSON array of 5 jobs (including jobs older than 3 days, and non-sponsoring jobs) into the API route.
4. Verify the dashboard correctly filtered out old jobs, dumped non-sponsoring jobs, assigned the correct tiers, and mapped the DA/AI resumes properly without UI errors.

*Do not proceed to Phase 2 (Auto-Applying) until this validation is 100% complete and approved.*
