-- Job_Seekr Phase 1 Schema
-- Run this in the Supabase SQL Editor: https://supabase.com/dashboard/project/ixlrveatukxdcevfigyn/sql

-- ============================================================
-- TABLE: resumes
-- ============================================================
CREATE TABLE IF NOT EXISTS resumes (
  id            UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id       TEXT        DEFAULT 'deepansh',
  role_type     TEXT        NOT NULL CHECK (role_type IN ('DA', 'BA', 'AI')),
  content       TEXT,
  file_name     TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- TABLE: jobs
-- ============================================================
CREATE TABLE IF NOT EXISTS jobs (
  id                 UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  apify_source_url   TEXT,
  company_name       TEXT        NOT NULL,
  job_title          TEXT        NOT NULL,
  job_description    TEXT,
  location           TEXT,
  sponsor_risk_flag  BOOLEAN     DEFAULT false,
  rejection_reason   TEXT,         -- 'too_old' | 'blocks_opt' | null
  posted_at          TIMESTAMPTZ,
  created_at         TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- TABLE: applications  (the triage board rows)
-- ============================================================
CREATE TABLE IF NOT EXISTS applications (
  id                  UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  job_id              UUID        REFERENCES jobs(id) ON DELETE CASCADE,
  assigned_resume_id  UUID        REFERENCES resumes(id),
  priority_tier       INTEGER     CHECK (priority_tier IN (1, 2, 3)),
  edge_score          FLOAT       DEFAULT 0,
  status              TEXT        DEFAULT 'Pending'
                                  CHECK (status IN ('Pending', 'Auto-Apply_Ready', 'Manual_Review', 'Rejected')),
  routing_reason      TEXT,
  created_at          TIMESTAMPTZ DEFAULT now()
);
