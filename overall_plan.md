# Job_Seekr - Overall Architecture & Application Plan

This document serves as the "North Star" for the Job_Seekr platform. It maps out the long-term goals and architecture. Specific phase-by-phase execution details belong in their respective `phase_X_plan.md` files.

## 1. Core Logic & F1-OPT Filtering
The platform is built with International Student constraints as a priority.
- **Sponsorship Filter:** A lightweight LLM (or regex) will read raw Job Descriptions (JDs) and immediately reject jobs hinting at "Citizens only", "No Sponsorship", or "Green Card required".
- **The "Edge" Score:** Passed jobs will be assigned an Edge Score factoring in local proximity, university matches, or specific tech stack dominance to prioritize them.

## 2. Multi-Resume Routing & Priority Pools
Users will apply to different tier companies with different strategies.
- **Resume Hub:** The system stores multiple variants (e.g., Data Analyst, BA, AI Engineer). The incoming job is mapped to the most relevant resume.
- **Priority Tier 1 (Top Tech/Dream Jobs):** Flagged for manual review or highly-tailored PDF generation. No blanket auto-applying here.
- **Priority Tier 2 (Mid-size):** Light tailoring of the resume/summary before auto-applying.
- **Priority Tier 3 (Broad Cast):** Blanket auto-apply using the mapped resume template.

## 3. Automation Engine & Sourcing
- **Sourcing:** Use **Apify Actors** to ingest job posts securely from LinkedIn/Indeed without triggering anti-bot constraints.
- **Simple Auto-Apply (Single Page Apps):** Quick Playwright automation mapping exact fields for platforms like Lever or Greenhouse.
- **Complex Auto-Apply (Multi-Page ATS like Workday):** Uses a Multi-Agent structural approach where a premium LLM reads the DOM step-by-step to progress through complex application wizards.
- **Email Verification Handshake:** For applications requiring account setup, we will use your **primary personal email** so you can seamlessly track all follow-up employer communications. The system will use the Gmail API via a scoped integration to quietly extract verification PINs/magic links in real time during the auto-apply flow.

## 4. Technology Stack & Free-Tier Strategy
We are optimizing for zero or negligible running costs:
- **Frontend:** Next.js (React).
- **Backend & Brain:** Python/FastAPI integrating LLMs via **LangChain and LangGraph** (LangGraph is essential here for orchestrating the stateful, cyclical "Observe -> Act -> Evaluate" multi-agent navigation flow for complex ATS systems).
- **Database:** Supabase (PostgreSQL) + Auth (Free Tier).
- **Sourcing API:** Apify (Leveraging the free $5/mo recurring credit for personal scraping).
- **LLM APIs:** 
  - Primary Reasoning (LangGraph agents): **Gemini API** via Google AI Studio (generous free tier).
  - Fast Extraction (JSON formatting, OPT filtering): **Groq** (free fast inference) or Local **Ollama** if preferred.

---
*Note: We iterate through this plan phase by phase. Do not begin work on subsequent phases until the current phase is firmly validated.*
