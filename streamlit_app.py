import json
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="Job Finder Dashboard", page_icon="🎯", layout="wide")

DB_PATH = "jobs.db"


@st.cache_resource
def get_engine():
    return create_engine(f"sqlite:///{DB_PATH}", echo=False)


def load_jobs() -> pd.DataFrame:
    engine = get_engine()
    query = text("SELECT * FROM jobs ORDER BY created_at DESC")
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    if df.empty:
        return df
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True).dt.tz_localize(None)
    df["match_score"] = pd.to_numeric(df["match_score"], errors="coerce")
    return df


def main():
    st.title("🎯 Job Finder Dashboard")

    df = load_jobs()
    if df.empty:
        st.warning("No jobs in the database yet. Run the pipeline first.")
        return

    scored = df[df["match_score"].notna()]
    notified = df[df["notified"] == 1]

    # ── KPI Row ───────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Jobs", len(df))
    col2.metric("Scored", len(scored))
    col3.metric("Notified", len(notified))
    col4.metric("Avg Score", f"{scored['match_score'].mean():.0f}" if len(scored) else "—")
    col5.metric("Pre-filtered", int(df["passed_prefilter"].sum()))

    st.divider()

    # ── Filters ───────────────────────────────────────────────
    with st.sidebar:
        st.header("Filters")

        score_range = st.slider(
            "Score range",
            0, 100, (0, 100),
            help="Filter jobs by AI match score",
        )

        companies = sorted(scored["company"].unique()) if len(scored) else []
        selected_companies = st.multiselect("Companies", companies)

        work_types = sorted(df["work_type"].dropna().unique())
        work_types = [w for w in work_types if w]
        selected_work_type = st.multiselect("Work type", work_types)

        days_back = st.selectbox("Time window", [7, 14, 30, 90, 365], index=0)
        cutoff = datetime.now() - timedelta(days=days_back)

    # ── Apply Filters ─────────────────────────────────────────
    filtered = scored.copy()
    filtered = filtered[
        (filtered["match_score"] >= score_range[0])
        & (filtered["match_score"] <= score_range[1])
    ]
    if selected_companies:
        filtered = filtered[filtered["company"].isin(selected_companies)]
    if selected_work_type:
        filtered = filtered[filtered["work_type"].isin(selected_work_type)]
    if "created_at" in filtered.columns:
        filtered = filtered[filtered["created_at"] >= cutoff]

    # ── Charts ────────────────────────────────────────────────
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.subheader("Score Distribution")
        if len(filtered):
            st.bar_chart(
                filtered["match_score"]
                .dropna()
                .astype(int)
                .value_counts()
                .sort_index(),
            )
        else:
            st.info("No data for selected filters.")

    with chart_col2:
        st.subheader("Top Companies")
        if len(filtered):
            top = (
                filtered.groupby("company")["match_score"]
                .mean()
                .sort_values(ascending=False)
                .head(10)
            )
            st.bar_chart(top)
        else:
            st.info("No data for selected filters.")

    # ── Jobs Over Time ────────────────────────────────────────
    st.subheader("Jobs Over Time")
    if len(filtered) and "created_at" in filtered.columns:
        daily = (
            filtered.set_index("created_at")
            .resample("D")
            .size()
            .rename("count")
        )
        st.line_chart(daily)

    # ── Job Table ─────────────────────────────────────────────
    st.subheader(f"Jobs ({len(filtered)})")

    if len(filtered):
        display_cols = [
            "match_score", "title", "company", "location",
            "work_type", "notified", "created_at", "url",
        ]
        display = filtered[display_cols].copy()
        display = display.sort_values("match_score", ascending=False)
        display.columns = [
            "Score", "Title", "Company", "Location",
            "Work Type", "Notified", "Date", "URL",
        ]

        st.dataframe(
            display,
            column_config={
                "Score": st.column_config.NumberColumn(format="%d"),
                "URL": st.column_config.LinkColumn("Link", display_text="Open"),
                "Notified": st.column_config.CheckboxColumn(),
            },
            use_container_width=True,
            hide_index=True,
        )

    # ── Expandable: Rejected Jobs ─────────────────────────────
    with st.expander("AI-Rejected Jobs (below threshold)"):
        rejected = scored[scored["match_score"] < 60].sort_values(
            "match_score", ascending=False,
        )
        if len(rejected):
            for _, row in rejected.head(20).iterrows():
                reasons = json.loads(row["match_reasons"] or "[]")
                reason_str = reasons[0] if reasons else "—"
                st.markdown(
                    f"**[{int(row['match_score'])}]** {row['title']} @ {row['company']}  \n"
                    f"_{reason_str}_  \n"
                    f"[Link]({row['url']})"
                )
        else:
            st.info("No rejected jobs.")

    # ── Missing Skills Analysis ───────────────────────────────
    st.subheader("Most Requested Missing Skills")
    if len(scored):
        all_missing = []
        for raw in scored["missing_skills"].dropna():
            try:
                all_missing.extend(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                pass
        if all_missing:
            skill_counts = pd.Series(all_missing).str.lower().value_counts().head(15)
            st.bar_chart(skill_counts)
        else:
            st.info("No missing skills data yet.")


if __name__ == "__main__":
    main()
