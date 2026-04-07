"""
Jobs router — exposes the pipeline endpoint.
POST /api/process-jobs  →  runs the full Phase 1 pipeline on mock data
GET  /api/jobs          →  returns all jobs + applications from Supabase
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from services.supabase_client import get_client
from services.opt_filter import check_opt_eligibility
from services.routing import route_job

router = APIRouter(prefix="/api", tags=["jobs"])

MOCK_DATA_PATH = Path(__file__).parent.parent / "data" / "mock_jobs.json"
FRESHNESS_DAYS = 3


def resolve_posted_at(raw_value: str) -> datetime:
    """
    Converts placeholder strings like 'DAYS_AGO_2' into real datetimes.
    In production this will be replaced by the real Apify timestamp.
    """
    now = datetime.now(timezone.utc)
    if raw_value.startswith("DAYS_AGO_"):
        days = int(raw_value.split("_")[-1])
        return now - timedelta(days=days)
    # Try parsing as ISO string
    try:
        dt = datetime.fromisoformat(raw_value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return now


@router.post("/process-jobs")
async def process_jobs():
    """
    Full Phase 1 pipeline:
    1. Load mock Apify payload
    2. Freshness filter  (drop > 3 days old)
    3. OPT filter        (drop jobs that ban international applicants)
    4. Routing + tiering (assign best resume + priority tier via Gemini)
    5. Save to Supabase
    """
    sb = get_client()

    with open(MOCK_DATA_PATH) as f:
        raw_jobs = json.load(f)

    now = datetime.now(timezone.utc)
    results = {
        "total": len(raw_jobs),
        "dropped_too_old": [],
        "dropped_blocks_opt": [],
        "passed": [],
    }

    for job in raw_jobs:
        posted_at = resolve_posted_at(job["posted_at"])
        age_days = (now - posted_at).days

        # ── 1. Freshness filter ──────────────────────────────────────────
        if age_days > FRESHNESS_DAYS:
            # Still save the job record so the UI can show it as rejected
            job_row = sb.table("jobs").insert({
                "apify_source_url": job.get("apify_source_url"),
                "company_name": job["company_name"],
                "job_title": job["job_title"],
                "job_description": job.get("job_description", ""),
                "location": job.get("location", ""),
                "sponsor_risk_flag": False,
                "rejection_reason": "too_old",
                "posted_at": posted_at.isoformat(),
            }).execute()

            saved_job = job_row.data[0]
            sb.table("applications").insert({
                "job_id": saved_job["id"],
                "assigned_resume_id": None,
                "priority_tier": None,
                "edge_score": 0,
                "status": "Rejected",
                "routing_reason": f"Posted {age_days} days ago — exceeds {FRESHNESS_DAYS}-day freshness window.",
            }).execute()

            results["dropped_too_old"].append(job["company_name"] + " — " + job["job_title"])
            continue

        # ── 2. OPT filter ────────────────────────────────────────────────
        opt_result = check_opt_eligibility(
            job["job_title"], job["company_name"], job.get("job_description", "")
        )

        job_row = sb.table("jobs").insert({
            "apify_source_url": job.get("apify_source_url"),
            "company_name": job["company_name"],
            "job_title": job["job_title"],
            "job_description": job.get("job_description", ""),
            "location": job.get("location", ""),
            "sponsor_risk_flag": opt_result["blocks_opt"],
            "rejection_reason": "blocks_opt" if opt_result["blocks_opt"] else None,
            "posted_at": posted_at.isoformat(),
        }).execute()

        saved_job = job_row.data[0]

        if opt_result["blocks_opt"]:
            sb.table("applications").insert({
                "job_id": saved_job["id"],
                "assigned_resume_id": None,
                "priority_tier": None,
                "edge_score": 0,
                "status": "Rejected",
                "routing_reason": opt_result["reason"],
            }).execute()

            results["dropped_blocks_opt"].append(job["company_name"] + " — " + job["job_title"])
            continue

        # ── 3. Routing + tier assignment ─────────────────────────────────
        route_result = route_job(
            job["job_title"], job["company_name"], job.get("job_description", "")
        )

        # Look up the resume ID for the assigned type
        resume_type = route_result["best_resume"]
        resume_lookup = sb.table("resumes").select("id").eq("role_type", resume_type).limit(1).execute()
        resume_id = resume_lookup.data[0]["id"] if resume_lookup.data else None

        tier = route_result["priority_tier"]
        status = "Manual_Review" if tier == 1 else "Auto-Apply_Ready" if tier == 3 else "Pending"

        sb.table("applications").insert({
            "job_id": saved_job["id"],
            "assigned_resume_id": resume_id,
            "priority_tier": tier,
            "edge_score": round(10 - (age_days * 1.5), 2),
            "status": status,
            "routing_reason": route_result.get("reasoning", ""),
        }).execute()

        results["passed"].append({
            "company": job["company_name"],
            "title": job["job_title"],
            "resume": resume_type,
            "tier": tier,
            "status": status,
        })

    return results


@router.get("/jobs")
async def get_jobs():
    """Returns all applications joined with job and resume data for the triage board."""
    sb = get_client()
    response = sb.table("applications").select(
        "*, jobs(*), resumes(role_type)"
    ).order("created_at", desc=True).execute()
    return response.data


@router.delete("/jobs/clear")
async def clear_jobs():
    """Clears all pipeline data — useful for re-running the mock pipeline."""
    sb = get_client()
    sb.table("applications").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    sb.table("jobs").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    return {"message": "All jobs and applications cleared."}
