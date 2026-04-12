import sqlite3
import os

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
                posted_at, status, match_score, legitimacy_label,
                legitimacy_reason, assigned_resume_type, filter_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job.get("apify_url"),
            job.get("company_name"),
            job.get("job_title"),
            job.get("job_description"),
            job.get("posted_at"),
            job.get("status", "Pending"),
            job.get("match_score"),
            job.get("legitimacy_label"),
            job.get("legitimacy_reason"),
            job.get("assigned_resume_type"),
            job.get("filter_reason"),
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
