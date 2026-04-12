import os

import pandas as pd
import streamlit as st

from db import (
    get_all_jobs,
    get_resume,
    get_tailor_status,
    init_db,
    save_resume,
    seed_resumes_if_empty,
    update_tailor_result,
)
from gemini_orchestrator import run_pipeline

# ── Bootstrap ─────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Job_Seekr", page_icon="🎯", layout="wide")
init_db()
seed_resumes_if_empty()

# ── Helpers ───────────────────────────────────────────────────────────────────
_LEGITIMACY_ICON = {
    "High Confidence":      "✅",
    "Proceed with Caution": "⚠️",
    "Suspicious":           "🚫",
    "Unknown":              "❓",
}

def _leg_badge(label: str) -> str:
    icon = _LEGITIMACY_ICON.get(label, "❓")
    return f"{icon} {label}" if label else "—"


def _run_tailor(job_id: int, company: str):
    """Run the tailoring pipeline for a job and rerun the page on completion."""
    with st.spinner(f"Tailoring resume for {company} — ~30s..."):
        try:
            from tailor import tailor_resume
            pdf_path, kw_pct, tailored_score = tailor_resume(job_id)
            score_msg = f", ATS score → {tailored_score:.0f}%" if tailored_score else ""
            st.success(f"Done — keyword coverage {kw_pct}%{score_msg}")
        except Exception as exc:
            update_tailor_result(job_id, "", "Error")
            st.error(f"Tailoring failed: {exc}")
    st.rerun()

# ── Sidebar navigation ────────────────────────────────────────────────────────
st.sidebar.title("Job_Seekr")
page = st.sidebar.radio("", ["Triage Board", "Resume Manager"])

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — TRIAGE BOARD
# ═══════════════════════════════════════════════════════════════════════════════
if page == "Triage Board":
    st.title("Triage Board")

    col_btn, col_status = st.columns([1, 4])
    with col_btn:
        run = st.button("▶ Run Pipeline (Mock)", type="primary", use_container_width=True)

    if run:
        with st.spinner("Running pipeline — Groq primary, Gemini fallback..."):
            counts = run_pipeline()
        msg = (
            f"Done — {counts['passed']} passed · "
            f"{counts['rejected']} rejected (OPT) · "
            f"{counts['low_match']} low match · "
            f"{counts['stale']} stale · "
            f"{counts['total']} total"
        )
        if counts.get("errored", 0):
            msg += f" · ⚠️ {counts['errored']} errored"
        col_status.success(msg)

    st.divider()
    jobs = get_all_jobs()

    if not jobs:
        st.info("No jobs yet. Hit **Run Pipeline (Mock)** to populate.")
    else:
        passed    = [j for j in jobs if j["status"] == "Passed"]
        low_match = [j for j in jobs if j["status"] == "Low Match"]
        rejected  = [j for j in jobs if j["status"] == "Rejected"]
        stale     = [j for j in jobs if j["status"] == "Stale"]
        errored   = [j for j in jobs if j["status"] == "Error"]

        # ── Matched jobs ──────────────────────────────────────────────────────
        st.subheader(f"✅ Matched Jobs (≥80%) — {len(passed)} results")
        if passed:
            # Pre-fetch base resumes (one DB call per role type, not per job)
            _resume_cache = {r: get_resume(r) for r in ("DA", "BA", "AI")}

            # Column headers
            h = st.columns([2.2, 2.5, 0.7, 1.2, 1.8, 1.9])
            for col, label in zip(h, ["Company", "Title", "Resume", "Score", "Legitimacy", "Action"]):
                col.markdown(f"**{label}**")
            st.divider()

            for job in passed:
                job_id      = job["id"]
                base_score  = job.get("match_score")
                tail_score  = job.get("tailored_match_score")

                c1, c2, c3, c4, c5, c6 = st.columns([2.2, 2.5, 0.7, 1.2, 1.8, 1.9])
                c1.write(f"**{job['company_name']}**")
                c2.write(job["job_title"])
                c3.write(job.get("assigned_resume_type", "—"))

                # Score column: base only, or base→tailored once re-scored
                if tail_score is not None:
                    c4.write(f"{base_score:.0f}% → **{tail_score:.0f}%**")
                else:
                    c4.write(f"{base_score:.0f}%" if base_score is not None else "—")

                c5.write(_leg_badge(job.get("legitimacy_label", "")))

                # Action column
                ts       = get_tailor_status(job_id)
                pdf_path = ts.get("tailored_resume_path") or ""
                if ts.get("tailor_status") == "Done" and pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        c6.download_button(
                            "⬇ Download PDF",
                            data=f.read(),
                            file_name=os.path.basename(pdf_path),
                            mime="application/pdf",
                            key=f"dl_{job_id}",
                            use_container_width=True,
                        )
                elif ts.get("tailor_status") == "Error":
                    if c6.button("↩ Retry Tailor", key=f"tailor_{job_id}", use_container_width=True):
                        _run_tailor(job_id, job["company_name"])
                else:
                    from tailor import compute_projected_score
                    proj = compute_projected_score(
                        job.get("job_description", ""),
                        _resume_cache.get(job.get("assigned_resume_type", "DA"), ""),
                        base_score or 0,
                    )
                    gain = proj - int(base_score or 0)
                    if gain <= 1:
                        # Already well-matched — tailoring adds negligible value
                        c6.caption("✅ Already well-matched")
                    elif gain <= 3:
                        # Marginal gain — let user decide
                        if c6.button(f"✨ Tailor (+{gain} pts)", key=f"tailor_{job_id}", use_container_width=True):
                            _run_tailor(job_id, job["company_name"])
                        c6.caption("marginal gain")
                    else:
                        if c6.button(f"✨ Tailor (+{gain} pts)", key=f"tailor_{job_id}", use_container_width=True):
                            _run_tailor(job_id, job["company_name"])
        else:
            st.write("_No jobs cleared the threshold yet._")

        # ── Below threshold ───────────────────────────────────────────────────
        with st.expander(f"🟡 Below Threshold (<80%) — {len(low_match)}"):
            if low_match:
                df2 = pd.DataFrame(low_match)
                df2["Legitimacy"] = df2["legitimacy_label"].apply(_leg_badge)
                df2["Score"] = df2["match_score"].apply(lambda x: f"{x:.0f}%" if x is not None else "—")
                st.dataframe(
                    df2[["company_name", "job_title", "assigned_resume_type", "Score", "Legitimacy", "filter_reason"]].rename(columns={
                        "company_name": "Company", "job_title": "Title",
                        "assigned_resume_type": "Resume", "filter_reason": "AI Reasoning",
                    }),
                    use_container_width=True, hide_index=True,
                )

        # ── Rejected (OPT) ────────────────────────────────────────────────────
        with st.expander(f"❌ Rejected (OPT / Visa Filter) — {len(rejected)}"):
            for j in rejected:
                st.write(f"**{j['company_name']}** — {j['job_title']} | _{j.get('filter_reason', '')}_")

        # ── Stale ─────────────────────────────────────────────────────────────
        with st.expander(f"🕒 Stale (>3 days old) — {len(stale)}"):
            for j in stale:
                st.write(f"**{j['company_name']}** — {j['job_title']} | posted {j.get('posted_at', '?')}")

        # ── API errors ────────────────────────────────────────────────────────
        if errored:
            with st.expander(f"⚠️ API Errors — {len(errored)}"):
                for j in errored:
                    st.write(f"**{j['company_name']}** — {j['job_title']} | _{j.get('filter_reason', '')}_")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — RESUME MANAGER
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "Resume Manager":
    st.title("Resume Manager")
    st.caption("Resumes are auto-loaded from the `resumes/` folder. Edit and save to override.")

    tabs = st.tabs(["Data Analyst (DA)", "Business Analyst (BA)", "Data Scientist / AI (AI)"])
    role_types = ["DA", "BA", "AI"]

    for tab, role_type in zip(tabs, role_types):
        with tab:
            current = get_resume(role_type)
            content = st.text_area(
                "Resume content (Markdown)",
                value=current,
                height=520,
                key=f"resume_{role_type}",
            )
            if st.button(f"Save {role_type} Resume", key=f"save_{role_type}"):
                save_resume(role_type, content)
                st.success(f"{role_type} resume saved.")
