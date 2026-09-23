import pandas as pd
import altair as alt
import streamlit as st
from typing import Optional
import io

import helper_general
import helper_data_loader

"""
Helper function for Experiment Planner tab
Answers: "Which missing readouts should I run next, and in what order?"

Operates on DiversityPlus 148-readout panel using helper_general's compute_readout_gaps.

Sections include:
    - Strategy selector
    - Options (scope filters, max rows, batch size)
    - Ranked experiment list <--------** PRIMARY OUTPUT **
    - Priority chart
    - Batch planning
    - Download
"""

_STATUS_DOMAIN = ["Complete", "Partial", "Missing"]
_STATUS_RANGE = ["#3cb44b", "#ffe119", "#e6194B"]

_ROW_DOMAIN = ["Present", "Missing"]
_ROW_RANGE = ["#3cb44b", "#e6194B"]

_PLATE_FORMATS = {
    "96-well (96)":     96,
    "384-well (384)":   384,
    "48-well (48)":     48,
    "24-well (24)":     24,
    "Custom":           None,
}

#######################################################
###              STRATEGY DEFINITIONS               ###
#######################################################

STRATEGIES = {
    "missing_first": {
        "label":            "Missing first",
        "description":  (
                            "Prioritize readouts with zero observations before partial ones.\n"
                        ),
    },
    "coverage_first": {
        "label":            "Coverage first",
        "description":  (
                            "Prioritize agents closest to full coverage: fewest readouts still missing.\n"
                            "Get agents to 100% as quickly as possible."
        ),
    },
    "agent_first": {
        "label":            "Agent first",
        "description":  (
                            "Fully complete one agent before moving to the next.\n"
                            "Best when per-compound charactertization is the priority."
        ),
    },
    "marker_first":{
        "label":            "Marker first",
        "description":  (
                            "Fill gaps in the most underrepresented markers first.\n"
                            "Best when specific readouts are scientifically crtitical."
        ),
    },
}

#######################################################
###                  RANKING LOGIC                  ###
#######################################################

def _rank_gaps(readout_table: pd.DataFrame, agent_summary: pd.DataFrame, strategy: str, max_rows: int = 500,) -> pd.DataFrame:

    """
    Build a ranked experiment list from readout_table. Only missing readouts are considered actionable.
    """

    # Only look at Missing readout rows as experiments to run
    base = readout_table[readout_table["Status"] == "Missing"].copy()

    if base.empty:
        return base
    
    # Attach agent-level summary columns for scoring
    base = base.merge(
        agent_summary[["AGENT", "ObservedReadouts", "MissingReadouts", "PctComplete", "Status"]]
        .rename(columns={"Status": "AgentStatus"}),
        on="AGENT", how="left",
    )
    
    # STRATEGY SCORING

    # Coverage first: agents closest to being 100% complete are prioritized
    if strategy == "coverage_first":
        base = base.sort_values(
            ["MissingReadouts", "AGENT", "SYSTEM", "MARKER"],
            ascending=[True, True, True, True],
        )
    
    # Agent first: least covered agent first, then alphabetically within agent
    elif strategy == "agent_first":
        base = base.sort_values(
            ["PctComplete", "AGENT", "SYSTEM", "MARKER"],
            ascending=[True, True, True, True]
        )

    # Marker first: Markers missing from most agents come first
    elif strategy == "marker_first":
        marker_miss_count = (
            readout_table[readout_table["Status"] == "Missing"]
            .groupby("MARKER")
            .size()
            .rename("MarkerMissCount")
            .reset_index()
        )
        base = base.merge(marker_miss_count, on="MARKER", how="left")
        base["MarkerMissCount"] = base["MarkerMissCount"].fillna(0)
        base = base.sort_values(
            ["MarkerMissCount", "MissingReadouts", "AGENT", "SYSTEM", "MARKER"],
            ascending=[False, False, True, True, True]
        )
    
    # Missing first (DEFAULT): agents with most missing readouts prioritized, ie biggest gaps. Tie broken by system then marker.
    else:
        base = base.sort_values(
            ["MissingReadouts", "AGENT", "SYSTEM", "MARKER"],
            ascending=[False, True, True, True]
        )

    base = base.head(max_rows).reset_index(drop=True)
    base.insert(0, "Priority", range(1, len(base) + 1))

    # Human-readable rationale
    base["Rationale"] = base.apply(
        lambda r: (
            f"Agent {r.get('PctComplete', 0):.0f}% complete -"
            f"{int(r.get('ObservedReadouts', 0))} observed, "
            f"{int(r.get('MissingReadouts', 0))} missing"
        ), axis=1
    )

    return base

#######################################################
###                  BATCH PLANNER                 ###
#######################################################

def _plan_batches(ranked: pd.DataFrame, batch_size: int) -> pd.DataFrame:

    if ranked.empty:
        return ranked
    batched = ranked.copy()
    batched["Batch"] = ((batched["Priority"] - 1) // batch_size) + 1

    return batched

#######################################################
###                CHART HELPERS                    ###
#######################################################

def _render_priority_chart(ranked: pd.DataFrame, top_n: int = 30) -> None:

    """
    Horizontal bar chart with one bar per readout. X axis is Priority rank (inverted so 1 is at top) and colored by System
    """

    top = ranked.head(top_n).copy()
    top["Label"] = top["AGENT"] + ", " + top["SYSTEM"] + ":" + top["MARKER"]

    bar = (alt.Chart(top)
           .mark_bar(cornerRadiusEnd=4)
           .encode(
               x=alt.X("MissingReadouts:Q", title="Missing readouts for this agent", scale=alt.Scale(domain=[0, ranked["MissingReadouts"].max() * 1.05]),), 
               y=alt.Y("Label:N", sort=alt.EncodingSortField("Priority", order="ascending"), title="", axis=alt.Axis(labelLimit=300)),
               color=alt.Color("SYSTEM:N", legend=alt.Legend(title="System"),),
               opacity=alt.Opacity("Priority:Q", scale=alt.Scale(range=[1.0, 0.4]), legend=None,),
               tooltip=[
                   alt.Tooltip("Priority:Q",        title="Priority"),
                   alt.Tooltip("AGENT:N",           title="Agent"),
                   alt.Tooltip("SYSTEM:N",          title="System"),
                   alt.Tooltip("MARKER:N",          title="Marker"),
                   alt.Tooltip("AgentStatus:N",     title="Agent status"),
                   alt.Tooltip("PctComplete:Q",     title="Agent coverage %", format=".1f"),
                   alt.Tooltip("ObservedReadouts:Q",title="Observed readouts", format=","),
                   alt.Tooltip("MissingReadouts:Q", title="Missing readouts", format=","),
                   alt.Tooltip("Rationale:N"),
               ],
           ).properties(height=max(min(22 * len(top), 700), 200), title=f"Top {len(top)} prioritized readouts to run",))
    
    st.altair_chart(bar, width="stretch")

def _render_batch_chart(batched: pd.DataFrame) -> None:

    batch_summary = (batched.groupby(["Batch", "AgentStatus"], as_index=False).size().rename(columns={"size": "Readouts"}))
    chart = (alt.Chart(batch_summary)
             .mark_bar()
             .encode(
                 x=alt.X("Batch:O", title="Batch"),
                 y=alt.Y("Readouts:Q"),
                 color=alt.Color(
                     "AgentStatus:N",
                     scale=alt.Scale(domain=_STATUS_DOMAIN, range=_STATUS_RANGE),
                     legend=alt.Legend(title="Agent status"),
                 ),
                 tooltip=["Batch:O", "AgentStatus:N", alt.Tooltip("Readouts:Q", format=","),],
             ).properties(height=250, title="Readouts per batch colored by agent status"))
    
    st.altair_chart(chart, width="stretch")

#######################################################
###                   TAB RENDERING                ###
#######################################################

def render(df: pd.DataFrame, denom: int=148) -> None:

    st.title("Experiment Planner")
    st.caption("Turn gap data into ranked, downloadable list of readouts to run.\n"
               "Based on the DiversityPlus panel with 148 readouts.")
    st.divider()

    # 1: Strategy picker
    st.subheader("1. Choose a prioritization strategy")

    strategy = st.radio("Prioritization strategy", options=list(STRATEGIES.keys()), format_func=lambda k: STRATEGIES[k]["label"], horizontal=True, key="ep_strategy", label_visibility="collapsed",)
    st.caption(STRATEGIES[strategy]["description"])

    st.divider()

    # 2: Options
    st.subheader("2. Select options")

    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        max_rows = st.number_input("Max readouts in output", min_value=10, max_value=5000, value=200, step=50, key="ep_max_rows",)
    with col_opt2:
        plate_label = st.selectbox("Plate format (batch size)", options=list(_PLATE_FORMATS.keys()), index=0, key="ep_plate_format", help="Sets number of readouts per batch. Choose Custom to enter any value.")
        if _PLATE_FORMATS[plate_label] is None:
            batch_size = st.number_input("Custom batch size", min_value=1, max_value=500, value=96, step=1, key="ep_batch_custom",)
        else:
            batch_size = _PLATE_FORMATS[plate_label]
            st.caption(f"Batch size: **{batch_size}** readouts per plate")
    
    with st.expander("Restrict scope (optional)", expanded=False):
        agents_all      =       sorted(df["AGENT"].dropna().unique().tolist())
        systems_all     =       sorted(df["SYSTEM"].dropna().unique().tolist())
        markers_all     =       sorted(df["MARKER"].dropna().unique().tolist())

        ep_agents       =       st.multiselect("Agents", agents_all, default=[], key="ep_agents", placeholder="All agents")
        ep_systems      =       st.multiselect("Systems", systems_all, default=[], key="ep_systems", placeholder="All systems")
        ep_markers      =       st.multiselect("Markers", markers_all, default=[], key="ep_markers", placeholder="All markers")

    st.divider()

    # Load pre-computed aggregates
    st.subheader("3. Results")
    with st.spinner("Loading gap data..."):
        readout_grid    =   helper_data_loader.load_readout_grid()
        agent_summary   =   helper_data_loader.load_agent_summary()

    # Apply scope filters
    if ep_agents:
        readout_grid    =   readout_grid[readout_grid["AGENT"].isin(ep_agents)]
        agent_summary   =   agent_summary[agent_summary["AGENT"].isin(ep_agents)]

    if ep_systems:
        readout_grid    =    readout_grid[readout_grid["SYSTEM"].isin(ep_systems)]

    if ep_markers:
        readout_grid    =   readout_grid[readout_grid["MARKER"].isin(ep_markers)]

    if readout_grid.empty:
        st.warning("No data after applying scope filters.")
        return
    
    if ep_systems or ep_markers:
        scoped_denom = readout_grid["MARKER"].nunique() * 1 # Pairs in scope
        counts = (
            readout_grid.groupby(["AGENT", "Status"])
            .size()
            .unstack(fill_value=0)
            .reset_index()
        )
        for col in ("Present", "Missing"):
            if col not in counts.columns:
                counts[col] = 0
        counts = counts.rename(columns={"Present": "ObservedReadouts", "Missing": "MissingReadouts"})
        scoped_denom = int(readout_grid.groupby("AGENT").size().max())
        counts["ObservedReadouts"] = counts["ObservedReadouts"].clip(upper=scoped_denom)
        counts["MissingReadouts"] = scoped_denom - counts["ObservedReadouts"]
        counts["PctComplete"] = (100 * counts["ObservedReadouts"] / max(scoped_denom, 1)).round(1)
        counts["Status"] = np.select(
            [counts["ObservedReadouts"] == scoped_denom, counts["ObservedReadouts"] == 0],
            ["Complete", "Missing"],
            default="Partial",
        )
        agent_summary = counts[["AGENT", "ObservedReadouts", "MissingReadouts", "PctComplete", "Status"]]
    
    n_missing = int((readout_grid["Status"] == "Missing").sum())
    if n_missing == 0:
        st.success("No missing readouts: all agents have a full panel.")
        return
    
    ranked = _rank_gaps(readout_grid, agent_summary, strategy=strategy,  max_rows=int(max_rows))

    if ranked.empty:
        st.success("No gaps match selected filters.")
        return
    
    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Readouts to run",                    f"{len(ranked):,}")
    c2.metric("Agents involved",                    f"{ranked['AGENT'].nunique():,}")
    c3.metric("Agents with partial readouts",       f"{(agent_summary['Status'] == 'Partial').sum():,}")
    c4.metric("Agents with missing readouts",       f"{(agent_summary['Status']=='Missing').sum():,}")

    # Priority chart
    top_n_chart = st.slider("Show top N in the chart", 10, min(100, len(ranked)), min(30, len(ranked)), 5, key="ep_top_n",)
    _render_priority_chart(ranked, top_n=top_n_chart)

    # Ranked table
    st.subheader("Ranked readout list")

    display_cols = ["Priority", "AGENT", "SYSTEM", "MARKER", "AgentStatus", "PctComplete", "ObservedReadouts", "MissingReadouts", "Rationale",]
    display_cols = [c for c in display_cols if c in ranked.columns]
    _STATUS_TAG = {"Complete": "🟢 Complete", "Partial": "🟡 Partial", "Missing": "🔴 Missing"}
    table_df = ranked[display_cols].copy()
    table_df["AgentStatus"] = table_df["AgentStatus"].map(lambda v: _STATUS_TAG.get(v, v))
    table_df["PctComplete"] = table_df["PctComplete"].round(1)
    st.dataframe(table_df, width="stretch", hide_index=True, height=400, column_config={
        "Priority":                 st.column_config.NumberColumn("Priority", format="%d"),
        "PctComplete":              st.column_config.NumberColumn("Coverage %", format="%.1f%%"),
        "ObservedReadouts":         st.column_config.NumberColumn("Observed", format="%d"),
        "MissingReadouts":          st.column_config.NumberColumn("Missing", format="%d"),
        "AgentStatus":              st.column_config.TextColumn("Agent Status"),
    },)
    
    st.divider()

    # 4. Batch planning
    st.subheader("4. Batch planning")
    st.caption(f"Readouts are divided into batches of **{int(batch_size)}** Please adjust plate format in options above if desired.")

    batched     = _plan_batches(ranked, int(batch_size))
    n_batches   = int(batched["Batch"].max())
    b1, b2, b3  = st.columns(3)
    b1.metric("Total batches needed", f"{n_batches:,}")
    b2.metric("Plate format", plate_label)
    b3.metric("Readouts in last batch",
              f"{len(batched[batched['Batch'] == n_batches]):,}")

    _render_batch_chart(batched)

    batch_sel = st.selectbox("Preview batch", options=list(range(1, n_batches + 1)), format_func=lambda x: f"Batch {x} ({len(batched[batched['Batch'] == x])} readouts)", key="ep_batch_sel",)
    st.dataframe(batched[batched["Batch"] == batch_sel][display_cols + ["Batch"]], width="stretch", hide_index=True,)

    st.divider()

    # 5. Download
    st.subheader("5. Download")
    col_dl1, col_dl2, col_dl3 = st.columns(3)
    with col_dl1:
        st.download_button("Ranked list (CSV)", data=ranked[display_cols].to_csv(index=False).encode("utf-8"),
                           file_name="experiment_plan_ranked.csv", mime="text/csv", width="stretch", key="ep_dl_ranked_csv")
    with col_dl2:
        st.download_button("With batches (CSV)", data=batched[display_cols + ["Batch"]].to_csv(index=False).encode("utf-8"),
                           file_name="experiment_plan_batched.csv", mime="text/csv", width="stretch", key="ep_dl_batched_csv",)
    with col_dl3:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            ranked[display_cols].to_excel(writer, index=False, sheet_name="All readouts")
            agent_summary.to_excel(writer, index=False, sheet_name="Agent summary")
            for b in sorted(batched["Batch"].unique()):
                sheet_name = f"Batch {b}"
                batched[batched["Batch"] == b][display_cols].to_excel(writer, index=False, sheet_name=sheet_name)
        st.download_button("Excel (one sheet/batch)", data=buf.getvalue(), file_name="experiment_plan.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch", key="ep_dl_excel")