import pandas as pd
import streamlit as st

from db import get_all_jobs, get_resume, init_db, save_resume, seed_resumes_if_empty
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
            df = pd.DataFrame(passed)
            df["Legitimacy"] = df["legitimacy_label"].apply(_leg_badge)
            df["Score"] = df["match_score"].apply(lambda x: f"{x:.0f}%" if x is not None else "—")
            st.dataframe(
                df[["company_name", "job_title", "assigned_resume_type", "Score", "Legitimacy", "posted_at", "filter_reason"]].rename(columns={
                    "company_name": "Company", "job_title": "Title",
                    "assigned_resume_type": "Resume", "posted_at": "Posted",
                    "filter_reason": "AI Reasoning",
                }),
                use_container_width=True, hide_index=True,
            )
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
