# Job_Seekr V2 - Overall Architecture & Execution Plan

This document serves as the global blueprint for the Job_Seekr platform using the "Simplest & Most Robust" Python architecture. Specific execution details for the current phase are kept in `phase_1_plan.md`.

## Core Vision
Build a highly viable, private, cost-free alternative to AIApply.com. It acts as an orchestrator that pulls fresh jobs, strictly filters out non-sponsoring roles (F1-OPT constraint), semantically scores the matches, customizes the resume against the job description using an LLM, and auto-applies via browser automation.

## Technology Stack (Python-Native)
We optimize for local, single-language development to ensure rapid integration of AI and web-automation:
- **UI / Frontend:** Streamlit (Pure Python interactive UI).
- **Backend / Brain:** Python integrated with Google Gemini API (Free Tier).
- **Database:** SQLite (Local, zero-config relational).
- **Sourcing:** Apify LinkedIn Actor (Safely pulls job feeds).
- **Auto-Apply Worker:** Playwright for Python.

## The 5-Step Pipeline
1. **Sourcing:** Apify runs on a schedule pulling jobs (filtered for <24h posted time) directly into SQLite.
2. **Quality Gate (F1-OPT):** The Python backend immediately queries Gemini using the raw JD: *"Does this ban international applicants?"*. Fails are rejected automatically.
3. **Semantic Scoring:** For passing jobs, Gemini is provided the JD and the user's base Markdown resume. It outputs a match confidence score (0-100%). Anything `< 80%` is hidden from the UI.
4. **Tailoring:** On the Streamlit Dashboard, clicking "Tailor Resume" triggers Gemini to rewrite the base markdown bullet points to securely inject missing JD keywords, raising the actual match percentage. It outputs a clean PDF and a Cover Letter.
5. **Auto-Apply Automation:** A background Playwright script consumes the Tailored PDF, logs into LinkedIn, navigates to the specific Easy Apply URL, uses the LLM to complete any complex form questions, and submits.

## Macroscopic Execution Strategy
*We only execute one phase at a time. Do not jump to automation before the UI data layer is pristine.*
- **Phase 1:** UI, SQLite DB, and Semantic Matching Engine (using mock Apify data).
- **Phase 2:** The Tailoring Engine (Markdown to PDF conversion + Cover Letters).
- **Phase 3:** Sourcing (Connecting the live Apify pipeline).
- **Phase 4:** Auto-Apply Automation (Playwright integration).
