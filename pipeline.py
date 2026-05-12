"""
pipeline.py — Multi-agent triage pipeline using LangGraph.

Architecture: each pipeline stage is an independent agent (node) in a directed graph.
Shared state (JobState) flows through every node. Conditional edges route the job
to the next agent or to an early exit based on decisions made at each stage.

Graph shape:
  START
    │
  [freshness_agent]  ── stale ──────────────────┐
    │ fresh                                      │
  [opt_agent]  ── denied ──────────────────────►[db_write_agent] ── END
    │ pass                                       │
  [legitimacy_agent] (annotates, never blocks)   │
    │                                            │
  [rag_agent]  (retrieves relevant resume chunks)│
    │                                            │
  [scoring_agent] (fit + ATS scoring)            │
    │                                            │
  [decision_agent] (Passed / Low Match / Error)  │
    │                                            │
    └───────────────────────────────────────────►┘

Why LangGraph over a plain for-loop:
  - Each node is independently testable and retryable.
  - Routing logic (conditional edges) is explicit, not buried in if/continue chains.
  - JobState makes the data flow transparent — you can inspect state at any node.
  - Tracing every node's inputs/outputs is built in (observability).
"""

import json
from datetime import datetime, timedelta
from typing import TypedDict

from langgraph.graph import END, StateGraph

from db import (
    get_pending_jobs,
    get_resume,
    insert_job,
    update_job_pipeline_result,
)
from llm import (
    SCORE_THRESHOLD,
    ats_check,
    fit_check,
    legitimacy_check,
    opt_filter,
)
from rag import index_resumes, retrieve_chunks

import os

MOCK_JOBS_PATH = os.path.join(os.path.dirname(__file__), "data", "mock_jobs.json")
FRESHNESS_DAYS = 3


# ── Shared state ───────────────────────────────────────────────────────────────
# JobState is the single dict that all agents read from and write to.
# Using TypedDict makes the structure explicit — every field is documented here.

class JobState(TypedDict):
    job:           dict    # raw job record (from mock JSON or DB)
    update_mode:   bool    # True = update existing DB row, False = insert new row
    status:        str     # current pipeline verdict
    filter_reason: str     # human-readable explanation for the status
    leg_label:     str     # legitimacy label ("High Confidence" | ...)
    leg_reason:    str     # legitimacy explanation
    resume_chunks: list    # RAG-retrieved resume chunks relevant to this JD
    fit_score:     int     # recruiter-lens score (0-100)
    fit_reason:    str
    ats_score:     int     # ATS keyword-match score (0-100)
    ats_reason:    str
    match_score:   int     # combined weighted score (0-100)


# ── Helper ─────────────────────────────────────────────────────────────────────

def _is_stale(posted_at: str) -> bool:
    try:
        posted = datetime.strptime(posted_at, "%Y-%m-%d")
    except ValueError:
        return True
    return datetime.today() - posted > timedelta(days=FRESHNESS_DAYS)


# ── Agents (nodes) ─────────────────────────────────────────────────────────────
# Each agent receives the full JobState and returns a dict of state updates.
# Only the keys that change need to be returned — LangGraph merges them in.

def freshness_agent(state: JobState) -> dict:
    """Agent 1: Drop jobs posted more than 3 days ago. No LLM call — pure date math."""
    if _is_stale(state["job"].get("posted_at", "")):
        return {"status": "Stale", "filter_reason": "Posted more than 3 days ago"}
    return {}


def opt_agent(state: JobState) -> dict:
    """
    Agent 2: Ask the LLM whether this JD bans OPT/visa sponsorship.
    Uses the fast 8b model — this is a binary yes/no decision.
    """
    try:
        company = state["job"].get("company_name", "")
        jd      = state["job"].get("job_description", "")
        denied, reason = opt_filter(company, jd)
        if denied:
            return {"status": "Rejected", "filter_reason": reason}
        return {}
    except Exception as e:
        return {"status": "Error", "filter_reason": f"OPT filter failed: {e}"}


def legitimacy_agent(state: JobState) -> dict:
    """
    Agent 3: Assess posting trustworthiness. Annotates only — never blocks.
    A suspicious job still gets scored; the label is shown in the UI for context.
    """
    try:
        company = state["job"].get("company_name", "")
        jd      = state["job"].get("job_description", "")
        label, reason = legitimacy_check(company, jd)
        return {"leg_label": label, "leg_reason": reason}
    except Exception as e:
        return {"leg_label": "Unknown", "leg_reason": f"Legitimacy check failed: {e}"}


def rag_agent(state: JobState) -> dict:
    """
    Agent 4: Retrieve the most relevant resume chunks for this JD using RAG.

    Embeds the JD → cosine similarity search → top-5 resume chunks.
    These chunks are passed to the scoring agents instead of the full resume.
    This is the RAG pattern: Retrieve relevant context → Augment the prompt → Generate.

    Fallback: if ChromaDB is empty or retrieval fails, use the full resume.
    """
    role = state["job"].get("assigned_resume_type", "DA")
    jd   = state["job"].get("job_description", "")

    try:
        chunks = retrieve_chunks(jd, role_type=role, k=5)
        if chunks:
            return {"resume_chunks": chunks}
    except Exception:
        pass  # fall through to full-resume fallback

    # Fallback: use the complete resume as a single chunk
    full_resume = get_resume(role)
    return {"resume_chunks": [full_resume] if full_resume else []}


def scoring_agent(state: JobState) -> dict:
    """
    Agent 5: Score the job on two lenses using the RAG-retrieved resume chunks.

    fit_score  — recruiter lens: does the candidate's experience actually demonstrate
                 what this role needs, even with different vocabulary?
    ats_score  — ATS lens: surface-level keyword and tool name overlap.

    Passing focused chunks (from rag_agent) instead of the full resume keeps the
    LLM context tight, reduces tokens, and produces more accurate per-section scoring.
    """
    if state.get("status") == "Error":
        return {}  # skip scoring if an earlier agent already errored

    role = state["job"].get("assigned_resume_type", "DA")

    # Safety check: if we somehow have no chunks, fetch the full resume
    if not state.get("resume_chunks"):
        full = get_resume(role)
        chunks = [full] if full else []
    else:
        chunks = state["resume_chunks"]

    if not chunks:
        return {"status": "Error", "filter_reason": f"No resume found for role: {role}"}

    resume_context = "\n\n---\n\n".join(chunks)
    company = state["job"].get("company_name", "")
    jd      = state["job"].get("job_description", "")

    try:
        fit_s, fit_r = fit_check(company, jd, resume_context)
        ats_s, ats_r = ats_check(company, jd, resume_context)
        return {
            "fit_score":  fit_s,
            "fit_reason": fit_r,
            "ats_score":  ats_s,
            "ats_reason": ats_r,
        }
    except Exception as e:
        return {"status": "Error", "filter_reason": f"Scoring failed: {e}"}


def decision_agent(state: JobState) -> dict:
    """
    Agent 6: Compute final score and decide Passed / Low Match.

    Fit is weighted higher (70%) because conceptual match matters more than
    exact keyword overlap — a strong candidate can learn the specific tools.
    """
    if state.get("status") == "Error":
        return {}

    fit_s = state.get("fit_score", 0)
    ats_s = state.get("ats_score", 0)
    score = round(0.7 * fit_s + 0.3 * ats_s)
    reason = (
        f"Fit: {fit_s}% — {state.get('fit_reason', '')} | "
        f"ATS: {ats_s}% — {state.get('ats_reason', '')}"
    )
    status = "Passed" if score >= SCORE_THRESHOLD else "Low Match"
    return {"match_score": score, "filter_reason": reason, "status": status}


def db_write_agent(state: JobState) -> dict:
    """
    Agent 7: Persist the result. This is the only agent that touches the DB.
    Handles both paths:
      update_mode=True  → update existing row (Phase 3: Pending jobs from sourcer)
      update_mode=False → insert new row (Phase 1: mock JSON jobs)
    """
    job        = state["job"]
    status     = state.get("status", "Error")
    job_id     = job.get("id")
    leg_label  = state.get("leg_label", "")
    leg_reason = state.get("leg_reason", "")
    reason     = state.get("filter_reason", "")
    fit_s      = state.get("fit_score")
    ats_s      = state.get("ats_score")
    match_s    = state.get("match_score")

    if state.get("update_mode") and job_id:
        update_job_pipeline_result(
            job_id, status,
            match_score=match_s, fit_score=fit_s, ats_score=ats_s,
            filter_reason=reason,
            legitimacy_label=leg_label, legitimacy_reason=leg_reason,
        )
    else:
        insert_job({
            **job,
            "status":            status,
            "match_score":       match_s,
            "fit_score":         fit_s,
            "ats_score":         ats_s,
            "filter_reason":     reason,
            "legitimacy_label":  leg_label,
            "legitimacy_reason": leg_reason,
        })

    return {}


# ── Routing functions ──────────────────────────────────────────────────────────
# These functions look at the current state and return the name of the next node.
# LangGraph uses them to draw the conditional edges in the graph.

def _route_after_freshness(state: JobState) -> str:
    # Stale jobs skip all LLM agents and go straight to DB write
    return "db_write" if state.get("status") == "Stale" else "opt"

def _route_after_opt(state: JobState) -> str:
    # Rejected (OPT ban) and errored jobs skip to DB write
    return "db_write" if state.get("status") in ("Rejected", "Error") else "legitimacy"


# ── Graph construction ─────────────────────────────────────────────────────────

def _build_graph() -> object:
    """
    Assemble the LangGraph StateGraph.

    Nodes  = agents (functions that transform state)
    Edges  = connections between agents
    Conditional edges = routing decisions based on current state
    """
    workflow = StateGraph(JobState)

    # Register every agent as a node
    workflow.add_node("freshness",  freshness_agent)
    workflow.add_node("opt",        opt_agent)
    workflow.add_node("legitimacy", legitimacy_agent)
    workflow.add_node("rag",        rag_agent)
    workflow.add_node("scoring",    scoring_agent)
    workflow.add_node("decision",   decision_agent)
    workflow.add_node("db_write",   db_write_agent)

    # Entry point
    workflow.set_entry_point("freshness")

    # After freshness: stale → db_write, fresh → opt
    workflow.add_conditional_edges(
        "freshness",
        _route_after_freshness,
        {"db_write": "db_write", "opt": "opt"},
    )

    # After opt: denied/error → db_write, pass → legitimacy
    workflow.add_conditional_edges(
        "opt",
        _route_after_opt,
        {"db_write": "db_write", "legitimacy": "legitimacy"},
    )

    # Remaining agents run in fixed sequence
    workflow.add_edge("legitimacy", "rag")
    workflow.add_edge("rag",        "scoring")
    workflow.add_edge("scoring",    "decision")
    workflow.add_edge("decision",   "db_write")
    workflow.add_edge("db_write",   END)

    return workflow.compile()


# Compile once at module load — reused for every job
_graph = _build_graph()


# ── Initial state builder ──────────────────────────────────────────────────────

def _initial_state(job: dict, update_mode: bool) -> JobState:
    """Build a clean starting state for a job. All scores default to 0."""
    return JobState(
        job=job,
        update_mode=update_mode,
        status="Pending",
        filter_reason="",
        leg_label="",
        leg_reason="",
        resume_chunks=[],
        fit_score=0,
        fit_reason="",
        ats_score=0,
        ats_reason="",
        match_score=0,
    )


def _count_result(counts: dict, status: str):
    """Increment the right counter based on final status."""
    mapping = {
        "Stale":     "stale",
        "Rejected":  "rejected",
        "Low Match": "low_match",
        "Passed":    "passed",
        "Error":     "errored",
    }
    key = mapping.get(status, "errored")
    counts[key] = counts.get(key, 0) + 1


# ── Public entry points ────────────────────────────────────────────────────────

def run_pipeline() -> dict:
    """
    Phase 1 path: load jobs from mock JSON, clear the DB, and run every job through
    the graph. Inserts new rows for each result.
    """
    # Ensure ChromaDB has the latest resume embeddings before scoring
    index_resumes()

    with open(MOCK_JOBS_PATH, "r") as f:
        jobs = json.load(f)

    from db import clear_jobs
    clear_jobs()

    counts = {"total": len(jobs), "stale": 0, "rejected": 0,
              "low_match": 0, "passed": 0, "errored": 0}

    for job in jobs:
        final_state = _graph.invoke(_initial_state(job, update_mode=False))
        _count_result(counts, final_state.get("status", "Error"))

    return counts


def run_pipeline_on_pending() -> dict:
    """
    Phase 3 path: run the graph on all jobs currently in the DB with status='Pending'.
    Updates existing rows in place — never inserts new ones.
    Called automatically by sourcer.run_sourcing() after ingestion.
    """
    index_resumes()

    jobs = get_pending_jobs()
    counts = {"total": len(jobs), "stale": 0, "rejected": 0,
              "low_match": 0, "passed": 0, "errored": 0}

    for job in jobs:
        final_state = _graph.invoke(_initial_state(job, update_mode=True))
        _count_result(counts, final_state.get("status", "Error"))

    return counts
