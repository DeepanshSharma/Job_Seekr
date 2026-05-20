# Job_Seekr — Overall Architecture & Execution Plan

**Last updated:** 2026-04-27
**Current status:** Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · AI Refactor ✅ · Phase 4 🔜

---

## Core Vision

A private, cost-free job application platform that:
1. Sources fresh jobs from ATS APIs + LinkedIn/Indeed
2. Filters out visa-hostile postings (F1-OPT constraint)
3. Semantically scores matches using a multi-agent RAG pipeline
4. Tailors resumes with RAG-grounded LLM rewriting + Playwright PDF rendering
5. Auto-applies via browser automation (Phase 4)

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| UI | Streamlit | Dashboard — Triage Board, Sourcing, Resume Manager |
| Database | SQLite (`jobseeker.db`) | Jobs, resumes, LLM call logs |
| LLM Primary | Groq (`llama-3.3-70b-versatile`) | Scoring, tailoring, OPT filter |
| LLM Fallback | Gemini (`gemini-2.0-flash`) | When Groq hits daily cap |
| Agent Orchestration | LangGraph | Multi-agent triage pipeline with state graph |
| RAG / Vector DB | ChromaDB + `all-MiniLM-L6-v2` | Resume chunk indexing + JD similarity retrieval |
| Structured Outputs | Pydantic + Groq JSON mode | Validated LLM responses, no regex parsing |
| PDF Rendering | Playwright (Chromium) | Headless HTML → Letter PDF |
| Job Sourcing | Apify (LinkedIn + Indeed) | Track B scraping |
| ATS Sourcing | Greenhouse / Lever / Ashby public APIs | Track A free sourcing |

---

## File Structure

```
Job_Seekr/
├── app.py                    # Streamlit dashboard (entry point)
├── db.py                     # SQLite schema, CRUD, llm_logs table
├── llm.py                    # LLM clients, call_llm(), Pydantic models, judgment functions
├── rag.py                    # ChromaDB: chunk resumes, embed, index, retrieve
├── pipeline.py               # LangGraph 7-agent triage graph
├── tailor.py                 # Resume tailoring engine + Playwright PDF renderer
├── eval.py                   # Custom LLM output evaluator (keyword coverage + hallucination)
├── sourcer.py                # Track A (ATS APIs) + Track B (Apify) sourcing engine
├── templates/
│   └── cv-template.html      # HTML resume template for Playwright
├── resumes/                  # Base markdown resumes (da, ba, ai)
├── output/                   # Generated PDFs
├── data/
│   └── mock_jobs.json        # Mock data for dev/testing
├── chroma_db/                # ChromaDB persistent vector store (gitignored)
├── requirements.txt
└── .env                      # API keys — never commit
```

---

## Pipeline Architecture (Multi-Agent LangGraph Graph)

Every job flows through this graph. Each node is an independent agent.

```
START
  │
[freshness_agent]  ── stale ──────────────────┐
  │ fresh                                      │
[opt_agent]  ── denied / error ──────────────►[db_write_agent] ── END
  │ pass                                       │
[legitimacy_agent]  (annotates, never blocks)  │
  │                                            │
[rag_agent]  (embed JD → top-5 resume chunks)  │
  │                                            │
[scoring_agent]  (fit score + ATS score)       │
  │                                            │
[decision_agent]  (Passed / Low Match)         │
  │                                            │
  └───────────────────────────────────────────►┘
```

**RAG in the pipeline:** `rag_agent` embeds the JD, runs cosine similarity against
ChromaDB resume chunks, and passes only the top-5 relevant chunks to `scoring_agent`.
This replaces sending the full resume to the LLM on every scoring call.

---

## Interview Concept Coverage

| Concept | File | What demonstrates it |
|---------|------|---------------------|
| RAG architecture | `rag.py` + `tailor.py` | Chunk → embed → cosine search → augmented prompt |
| Vector database | `rag.py` | ChromaDB PersistentClient, cosine space |
| Embeddings | `rag.py` | `all-MiniLM-L6-v2` via SentenceTransformerEmbeddingFunction |
| Structured outputs | `llm.py` | Pydantic models + Groq `response_format=json_object` |
| Multi-agent / LangGraph | `pipeline.py` | 7 agents, `JobState` TypedDict, conditional edges |
| LLM evaluation | `eval.py` | Keyword coverage % + hallucination detection |
| MLOps observability | `llm.py` + `db.py` | Every LLM call logged: model, latency, provider |
| Prompt engineering | `llm.py` + `tailor.py` | Structured prompts with role instructions + output schemas |
| Multi-model routing | `llm.py` | Groq primary → 8b fallback → Gemini fallback |

---

## Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Done | Triage board — OPT filter + legitimacy + dual scoring (fit + ATS) |
| 2 | ✅ Done | Tailoring engine — `tailor.py` + HTML template + Playwright PDF + one-page fitting |
| 3 | ✅ Done | Live sourcing — Track A (ATS APIs) + Track B (Apify LinkedIn + Indeed) |
| AI Refactor | ✅ Done | LangGraph pipeline, RAG/ChromaDB, Pydantic outputs, eval layer, LLM observability |
| 4 | 🔜 Planned | Auto-apply — Playwright form filling + LinkedIn Easy Apply submission |
