"""Minimal Streamlit viewer for the PD TeamTracker data.

Standalone — not wired into the main AFL dashboard. The MGS app can copy
this as a starting point.

Run:
    .venv/bin/streamlit run pd_scraper/viewer.py
"""
from __future__ import annotations

import streamlit as st

from pd_scraper import query

st.set_page_config(page_title="PD TeamTracker", layout="wide")
st.title("PD TeamTracker — Mentone Grammar")

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Filters")
    all_matches = query.matches()
    if all_matches.empty:
        st.error("No matches in data/pd/pd.db — run `python -m pd_scraper.cli backfill` first.")
        st.stop()
    seasons = sorted(all_matches["season"].dropna().unique().tolist())
    season = st.selectbox("Season", seasons, index=len(seasons) - 1)
    season_matches = all_matches[all_matches["season"] == season]

    match_labels = {
        r["match_id"]: f"R{r['round']} — {r['home_team']} {r['home_score']} vs {r['away_team']} {r['away_score']}"
        for _, r in season_matches.iterrows()
    }
    match_id = st.selectbox(
        "Match",
        list(match_labels),
        format_func=lambda mid: match_labels.get(mid, mid),
    )
    period = st.selectbox("Period", ["TOTAL", "Q1", "Q2", "Q3", "Q4"])
    view = st.selectbox("Player stats view", ["Basic", "Advanced", "Involvements"])

# ---------------------------------------------------------------- header
hdr = season_matches[season_matches["match_id"] == match_id].iloc[0]
cols = st.columns(3)
cols[0].metric(hdr["home_team"], hdr["home_score"], hdr["home_goals_behinds"])
cols[1].metric("Round", hdr["round"])
cols[2].metric(hdr["away_team"], hdr["away_score"], hdr["away_goals_behinds"])

# ---------------------------------------------------------------- tabs
tabs = st.tabs(["Team stats", "Player stats", "Shots", "Season totals"])

with tabs[0]:
    df = query.team_stats(match_id, period=period)
    if df.empty:
        st.info(f"No team stats for period {period}")
    else:
        wide = df.pivot_table(
            index=["tab", "section", "stat_name"],
            columns="side", values="value_num", aggfunc="first",
        ).reset_index()
        st.dataframe(wide, use_container_width=True, hide_index=True)

with tabs[1]:
    df = query.player_stats(match_id, view=view, period=period)
    if df.empty:
        st.info("No player stats available for this slice")
    else:
        for side, label in (("home", hdr["home_team"]), ("away", hdr["away_team"])):
            sub = df[df["side"] == side]
            if sub.empty:
                continue
            st.subheader(label)
            st.dataframe(sub.drop(columns=["side"]),
                         use_container_width=True, hide_index=True)

with tabs[2]:
    df = query.shots(match_id)
    if df.empty:
        st.info("No shot data for this match")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

with tabs[3]:
    df = query.season_player_totals(int(season), view=view)
    if df.empty:
        st.info("No season totals yet")
    else:
        team_filter = st.selectbox("Filter team", ["(all)"] + sorted(df["team"].dropna().unique()))
        if team_filter != "(all)":
            df = df[df["team"] == team_filter]
        st.dataframe(df, use_container_width=True, hide_index=True)
