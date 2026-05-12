import sqlite3
import os
from datetime import datetime

DB_PATH = "jobseeker.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS resumes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            role_type   TEXT UNIQUE NOT NULL,
            content     TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            apify_url            TEXT,
            company_name         TEXT,
            job_title            TEXT,
            job_description      TEXT,
            posted_at            TEXT,
            status               TEXT DEFAULT 'Pending',
            match_score          REAL,
            legitimacy_label     TEXT,
            legitimacy_reason    TEXT,
            assigned_resume_type TEXT,
            filter_reason        TEXT
        )
    """)
    # Migrate existing DBs that predate the legitimacy columns
    for col in ("legitimacy_label", "legitimacy_reason"):
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
        except Exception:
            pass

    # Phase 2 columns
    for col_def in (
        "fit_score            REAL",
        "ats_score            REAL",
        "tailored_resume_path TEXT",
        "tailor_status        TEXT DEFAULT 'Pending'",
        "tailored_match_score REAL",
    ):
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col_def}")
        except Exception:
            pass

    # Phase 3 columns
    for col_def in (
        "source        TEXT",
        "external_id   TEXT",
        "sourced_at    TEXT",
        "apply_url     TEXT",
        "ats_type      TEXT",
        "is_easy_apply INTEGER DEFAULT 0",
    ):
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col_def}")
        except Exception:
            pass

    # MLOps: log every LLM call for observability (model, latency, provider)
    c.execute("""
        CREATE TABLE IF NOT EXISTS llm_logs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp      TEXT NOT NULL,
            model          TEXT NOT NULL,
            prompt_preview TEXT,
            latency_ms     INTEGER,
            provider       TEXT
        )
    """)

    conn.commit()
    conn.close()


# ── Resumes ──────────────────────────────────────────────────────────────────

def save_resume(role_type: str, content: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO resumes (role_type, content) VALUES (?, ?)
           ON CONFLICT(role_type) DO UPDATE SET content = excluded.content""",
        (role_type, content),
    )
    conn.commit()
    conn.close()


def get_resume(role_type: str) -> str:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT content FROM resumes WHERE role_type = ?", (role_type,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else ""


def seed_resumes_if_empty():
    """Auto-load the .md files into SQLite on first run."""
    base = os.path.join(os.path.dirname(__file__), "resumes")
    mapping = {
        "DA": os.path.join(base, "da_resume.md"),
        "BA": os.path.join(base, "ba_resume.md"),
        "AI": os.path.join(base, "ai_resume.md"),
    }
    for role_type, path in mapping.items():
        if not get_resume(role_type) and os.path.exists(path):
            with open(path, "r") as f:
                save_resume(role_type, f.read())


# ── Jobs ──────────────────────────────────────────────────────────────────────

def insert_job(job: dict):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO jobs
               (apify_url, company_name, job_title, job_description,
                posted_at, status, match_score, fit_score, ats_score,
                legitimacy_label, legitimacy_reason,
                assigned_resume_type, filter_reason,
                source, external_id, sourced_at,
                apply_url, ats_type, is_easy_apply)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job.get("apify_url"),
            job.get("company_name"),
            job.get("job_title"),
            job.get("job_description"),
            job.get("posted_at"),
            job.get("status", "Pending"),
            job.get("match_score"),
            job.get("fit_score"),
            job.get("ats_score"),
            job.get("legitimacy_label"),
            job.get("legitimacy_reason"),
            job.get("assigned_resume_type"),
            job.get("filter_reason"),
            job.get("source"),
            job.get("external_id"),
            job.get("sourced_at"),
            job.get("apply_url"),
            job.get("ats_type"),
            1 if job.get("is_easy_apply") else 0,
        ),
    )
    conn.commit()
    conn.close()


def get_all_jobs() -> list[dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM jobs
        ORDER BY
            CASE status WHEN 'Passed' THEN 0 ELSE 1 END,
            match_score DESC
    """)
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def clear_jobs():
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM jobs")
    conn.commit()
    conn.close()


# ── Phase 2 — Tailoring ──────────────────────────────────────────────────────

def get_job_by_id(job_id: int) -> dict | None:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = c.fetchone()
    cols = [d[0] for d in c.description]
    conn.close()
    return dict(zip(cols, row)) if row else None


def update_tailor_result(
    job_id: int,
    pdf_path: str,
    status: str = "Done",
    tailored_score: float | None = None,
):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """UPDATE jobs
           SET tailored_resume_path = ?,
               tailor_status        = ?,
               tailored_match_score = ?
           WHERE id = ?""",
        (pdf_path, status, tailored_score, job_id),
    )
    conn.commit()
    conn.close()


def get_tailor_status(job_id: int) -> dict:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT tailor_status, tailored_resume_path FROM jobs WHERE id = ?",
        (job_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return {"tailor_status": None, "tailored_resume_path": None}
    return {"tailor_status": row[0], "tailored_resume_path": row[1]}


# ── Phase 3 — Sourcing ────────────────────────────────────────────────────────

def job_url_exists(url: str) -> bool:
    """Primary dedup check — URL already in DB."""
    if not url:
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM jobs WHERE apify_url = ? LIMIT 1", (url,))
    exists = c.fetchone() is not None
    conn.close()
    return exists


def job_composite_exists(company: str, title: str) -> bool:
    """Secondary dedup check — same company+title already in DB."""
    if not company or not title:
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM jobs WHERE LOWER(company_name) = LOWER(?) AND LOWER(job_title) = LOWER(?) LIMIT 1",
        (company, title),
    )
    exists = c.fetchone() is not None
    conn.close()
    return exists


def get_pending_jobs() -> list[dict]:
    """Return all jobs with status='Pending' for pipeline processing."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE status = 'Pending'")
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def update_job_pipeline_result(
    job_id: int,
    status: str,
    match_score: float | None = None,
    fit_score: float | None = None,
    ats_score: float | None = None,
    filter_reason: str | None = None,
    legitimacy_label: str | None = None,
    legitimacy_reason: str | None = None,
):
    """Update pipeline results for a job already in the DB (Phase 3 path)."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """UPDATE jobs
           SET status            = ?,
               match_score       = ?,
               fit_score         = ?,
               ats_score         = ?,
               filter_reason     = ?,
               legitimacy_label  = ?,
               legitimacy_reason = ?
           WHERE id = ?""",
        (status, match_score, fit_score, ats_score,
         filter_reason, legitimacy_label, legitimacy_reason, job_id),
    )
    conn.commit()
    conn.close()


def log_llm_call(model: str, prompt_preview: str, latency_ms: int, provider: str):
    """Record one LLM call. Called by llm.py after every successful call."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO llm_logs (timestamp, model, prompt_preview, latency_ms, provider)
           VALUES (?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(timespec="seconds"), model, prompt_preview, latency_ms, provider),
    )
    conn.commit()
    conn.close()


def get_llm_logs(limit: int = 50) -> list[dict]:
    """Return the most recent LLM calls — used by the UI for observability."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM llm_logs ORDER BY id DESC LIMIT ?", (limit,)
    )
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def get_sourcing_stats() -> dict:
    """Stats for the Sourcing page: totals, by-source counts, new today."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM jobs")
    total = c.fetchone()[0]

    c.execute("""
        SELECT source, COUNT(*) FROM jobs
        WHERE source IS NOT NULL
        GROUP BY source
    """)
    by_source = {row[0]: row[1] for row in c.fetchall()}

    c.execute("SELECT COUNT(*) FROM jobs WHERE DATE(sourced_at) = DATE('now', 'localtime')")
    new_today = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM jobs WHERE status = 'Pending'")
    pending = c.fetchone()[0]

    conn.close()
    return {"total": total, "by_source": by_source, "new_today": new_today, "pending": pending}
