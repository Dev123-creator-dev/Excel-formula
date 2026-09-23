import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
from typing import Optional
import io

import helper_data_loader

FILTERABLE_COLUMNS = ["SYSTEM", "MARKER", "AGENT"]

_STATUS_DOMAIN = ["Complete", "Partial", "Missing"]
_STATUS_RANGE = ["#3cb44b", "#ffe119", "#e6194B"]

_PRESENT_DOMAIN = ["Present", "Missing"]
_PRESENT_RANGE = ["#3cb44b", "#e6194B"]

#######################################################
###                 SHARED HELPERS                  ###
#######################################################

def _agent_summary_metrics(gap_table: pd.DataFrame) -> None:

    total           =   len(gap_table)
    n_complete      =   int((gap_table["Status"] == "Complete").sum())
    n_partial       =   int((gap_table["Status"] == "Partial").sum())
    n_missing       =   int((gap_table["Status"] == "Missing").sum())

    c1, c2, c3, c4  =   st.columns(4)
    c1.metric("Total",      f"{total:,}")
    c2.metric("Complete",   f"{n_complete:,}",  f"{100*n_complete/max(total,1):.0f}%")
    c3.metric("Partial",    f"{n_partial:,}",   f"{100*n_partial/max(total,1):.0f}%")
    c4.metric("Missing",    f"{n_missing:,}",   f"{100*n_missing/max(total,1):.0f}%")

def _single_agent_summary_metrics(row: pd.Series, denom: int) -> None:

    """
    Headline metrics for one agent row from agent_summary
    """

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Expected readouts",      f"{denom}")
    c2.metric("Observed readouts",      f"{int(row['ObservedReadouts']):,}")
    c3.metric("Missing readouts",       f"{int(row['MissingReadouts']):,}")
    c4.metric("Coverage",               f"{row['PctComplete']:.1f}%",
              delta=row["Status"], delta_color="normal" if row["Status"] == "Present" else "inverse" if row["Status"] == "Missing" else "off")

def _readout_heatmap(df: pd.DataFrame, status_col: str, domain: list, colors: list,) -> alt.Chart:

    """
    Sys:Mrk heatmap colored by Present or Missing.
    """

    readout_table = df.copy()

    readout_table[status_col] = pd.Categorical(readout_table[status_col], categories=domain, ordered=True)
    
    chart = (alt.Chart(readout_table)
            .mark_rect(stroke="white", strokeWidth=0.8, cornerRadius=2)
            .encode(
            x=alt.X("SYSTEM:N", axis=alt.Axis(labelAngle=-35), title="System"),
            y=alt.Y("MARKER:N", title="Marker"),
            color=alt.Color(f"{status_col}:N",
                            scale=alt.Scale(domain=domain, range=colors), legend=alt.Legend(title="Status"),),
            tooltip=[alt.Tooltip(f"SYSTEM:N", title="System"),
                        alt.Tooltip(f"MARKER:N", title="Marker"),
                        alt.Tooltip(f"{status_col}:N", title="Status"),
                        ],
            ).properties(height= max(min(24 * readout_table["MARKER"].nunique(), 700), 250)))

    return chart

def _render_export(key: str, readout_table: pd.DataFrame, agent_summary: pd.DataFrame, ) -> None:

    with st.expander("Export gap data", expanded=False):
        status_filter = st.selectbox("Readouts to include", ["Missing only", "Present only", "All"], index=0, key=f"exp_filter_{key}")

        if status_filter == "Missing only":
            out_rows = readout_table[readout_table["Status"] == "Missing"]
        elif status_filter == "Present only":
            out_rows = readout_table[readout_table["Status"] == "Present"]
        else:
            out_rows = readout_table

        include_summary = st.checkbox("Include agent summary sheet", value=True, key=f"exp_summary_{key}")

        if not out_rows.empty:
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("Download CSV", data=out_rows.to_csv(index=False).encode("utf-8"), file_name=f"readout_gaps_{key}.csv", mime="text/csv", key=f"dl_csv_{key}", width="stretch")
            with c2:
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    out_rows.to_excel(writer, index=False, sheet_name="Readout gaps")
                    if include_summary:
                        agent_summary.to_excel(writer, index=False, sheet_name="Agent summary")
                st.download_button("Download Excel", data=buf.getvalue(), file_name=f"readout_gaps_{key}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"dl_xlsx_{key}", width="stretch")
            with st.expander("Preview (first 50 rows)", expanded=False):
                st.dataframe(out_rows.head(50), width="stretch", hide_index=True)


#######################################################
###                SINGLE AGENT VIEW                ###
#######################################################


def _render_single_agent(readout_grid: pd.DataFrame, agent_summary: pd.DataFrame, denom: int,) -> None:

    agents = sorted(agent_summary["AGENT"].dropna().unique().tolist())
    if not agents:
        st.info("No agents in dataset.")
        return
    
    agent = st.selectbox("Select agents", agents, key="gap_agent_select")

    agent_row = agent_summary[agent_summary["AGENT"] == agent].iloc[0]
    agent_rows = readout_grid[readout_grid["AGENT"] == agent].copy()

    st.markdown(f"#### {agent} readout coverage")
    _single_agent_summary_metrics(agent_row, denom=denom)
    st.divider()

    # Clickable heatmap
    st.subheader("Coverage Heatmap")
    st.caption("Present (green): at least one observation exists for this System:Marker"
               "Missing (red): no observations found")
    
    hm = _readout_heatmap(agent_rows, status_col="Status", domain=_PRESENT_DOMAIN, colors=_PRESENT_RANGE)
    st.altair_chart(hm, width="stretch")

    # Missing readout table
    missing_rows = agent_rows[agent_rows["Status"] == "Missing"]
    if missing_rows.empty:
        st.success(f"{agent} has all {denom} readouts present.")
    else:
        with st.expander(f"Missing readouts: {len(missing_rows)} of {denom}", expanded=True):
            st.dataframe(missing_rows[["SYSTEM", "MARKER"]].sort_values(["SYSTEM", "MARKER"]).reset_index(drop=True),
                        width="stretch", hide_index=True,)

    _render_export(f"agent_{agent}", agent_rows, agent_summary[agent_summary["AGENT"] == agent])


#######################################################
###                 MULTI-AGENT VIEW                ###
#######################################################

def _render_multi_agent(readout_grid: pd.DataFrame, agent_summary: pd.DataFrame, denom: int) -> None:

    all_agents = sorted(agent_summary["AGENT"].dropna().unique().tolist())

    pick_mode = st.radio("Agent scope", ["All agents", "Choose agents"], horizontal=True, key="multi_scope",)

    if pick_mode == "Choose agents":
        agents = st.multiselect("Select agents", all_agents, default=all_agents[:min(8, len(all_agents))], key="multi-pick",)
    else:
        agents = all_agents
    
    if not agents:
        st.warning("Select at least one agent.")
        return
    
    readout_table       = readout_grid[readout_grid["AGENT"].isin(agents)].copy()
    agent_sum           = agent_summary[agent_summary["AGENT"].isin(agents)].copy()

    st.markdown(f"#### Coverage Summary")
    _agent_summary_metrics(agent_sum)

    st.divider()

    # Per-agent percent coverage bar
    st.subheader("Per-agent status breakdown")
    agent_bar = (alt.Chart(agent_sum)
                 .mark_bar(cornerRadiusEnd=4)
                 .encode(
                     x=alt.X("PctComplete:Q", title=f"Percentage of {denom} readouts observed", scale=alt.Scale(domain=[0,100])),
                     y=alt.Y("AGENT:N", sort=alt.EncodingSortField("PctComplete", order="ascending"), title="Agent"),
                     color=alt.Color("Status:N", scale=alt.Scale(domain=_STATUS_DOMAIN, range=_STATUS_RANGE),legend=alt.Legend(title="Status"),),
                     tooltip=[
                         alt.Tooltip("AGENT:N",             title="Agent"),
                         alt.Tooltip("Status:N",            title="Status"),
                         alt.Tooltip("PctComplete:Q",       title="Coverage %",     format=".1f"),
                         alt.Tooltip("ObservedReadouts:Q",  title="Observed",       format=","),
                         alt.Tooltip("MissingReadouts:Q",   title="Missing",        format=",")],
                 ).properties(height=max(min(28 * len(agent_summary), 700), 200)))
    rule = (alt.Chart(pd.DataFrame({"x": [80]})).mark_rule(color="#64748b", strokeDash=[4, 4]).encode(x="x:Q"))
    st.altair_chart(agent_bar + rule, width="stretch")

    st.divider()

    # Cross-agent Percent Completed Heatmap
    st.subheader("Cross-agent Coverage Heatmap")
    st.caption("Color is the percentage of selected agents considered present. Red means everyone has a gap.")

    pct_df = (readout_table.assign(IsPresent=lambda d: d["Status"] == "Present")
              .groupby(["SYSTEM", "MARKER"], as_index=False)["IsPresent"]
              .agg(["sum", "count"])
              .assign(PctPresent=lambda d: 100 * d["sum"] / d["count"].clip(lower=1)))
    
    cross_hm = (alt.Chart(pct_df)
                .mark_rect(stroke="white", strokeWidth=0.5)
                .encode(
                    x=alt.X("SYSTEM:N", axis=alt.Axis(labelAngle=-35), title="System"),
                    y=alt.Y("MARKER:N", title="Marker"),
                    color=alt.Color("PctPresent:Q", scale=alt.Scale(scheme="redyellowgreen", domain=[0,100]),title="% Present",),
                    tooltip=[alt.Tooltip("SYSTEM:N",    title="System"),
                             alt.Tooltip("MARKER:N",    title="Marker"),
                             alt.Tooltip("PctPresent:Q",title="% Present", format=".1f"),
                             alt.Tooltip("sum:Q",       title="Agents with readout"),
                             alt.Tooltip("count:Q",     title="Total agents"),],
                ).properties(height=max(min(24 * pct_df["MARKER"].nunique(), 700), 250),))
    st.altair_chart(cross_hm, width="stretch")

    st.divider()

    # Hotspot chart
    st.subheader("Gap hotspots")
    st.caption("System:Marker pairs where the most agents have incomplete data")

    hotspot = (readout_table[readout_table["Status"] == "Missing"]
               .groupby(["SYSTEM", "MARKER"], as_index=False)
               .size()
               .rename(columns={"size": "AgentsMissing"})
               .sort_values("AgentsMissing", ascending=False)
               .head(30))
    
    if hotspot.empty or hotspot["AgentsMissing"].sum() == 0:
        st.success("No hotspots. All selected agents have all readouts present.")
    else:
        hot_chart = (alt.Chart(hotspot)
                     .mark_bar(cornerRadiusEnd=4)
                     .encode(
                         x=alt.X("AgentsMissing:Q", title="# Agents missing readout"),
                         y=alt.Y("MARKER:N", sort="-x", title="Marker"),
                         color=alt.Color("SYSTEM:N", title="System"),
                         tooltip=[alt.Tooltip("SYSTEM:N",       title="System"),
                                  alt.Tooltip("MARKER:N",       title="Marker"),
                                  alt.Tooltip("AgentsMissing:Q",title="Agents missing", format=","),],
                     ).properties(height=max(min(26 * len(hotspot), 600), 200)))
        st.altair_chart(hot_chart, width="stretch")

    _render_export("multi_agent", readout_table, agent_sum)


#######################################################
###                 AGENT DIFF VIEW                 ###
#######################################################

def _render_agent_diff(readout_grid: pd.DataFrame, agent_summary: pd.DataFrame, denom: int) -> None:

    st.caption("Compare two agents side-by-side.\n"
               "The difference table shows every readout where status differs.")
    
    agents = sorted(agent_summary["AGENT"].dropna().unique().tolist())
    if len(agents) < 2:
        st.info("Need at least two agents for comparison.")
        return
    
    col_a, col_b = st.columns(2)
    with col_a:
        agent_a = st.selectbox("Agent A", agents, index=0, key="diff_a")
    with col_b:
        agent_b = st.selectbox("Agent B", agents, index=min(1, len(agents)-1), key="diff_b")

    if agent_a == agent_b:
        st.warning("Please select two different agents.")
        return
    
    agent_a_rows = readout_grid[readout_grid["AGENT"] == agent_a].copy()
    agent_b_rows = readout_grid[readout_grid["AGENT"] == agent_b].copy()
    a_row = agent_summary[agent_summary["AGENT"] == agent_a].iloc[0]
    b_row = agent_summary[agent_summary["AGENT"] == agent_b].iloc[0]

    ca1, ca2, cb1, cb2 = st.columns(4)
    ca1.metric(f"{agent_a} observed",   f"{int(a_row['ObservedReadouts'])}")
    ca2.metric(f"{agent_a} missing",    f"{int(a_row['MissingReadouts'])}")
    cb1.metric(f"{agent_b} observed",   f"{int(b_row['ObservedReadouts'])}")
    cb2.metric(f"{agent_b} missing",    f"{int(b_row['MissingReadouts'])}")

    # Diff table
    merged = agent_a_rows[["SYSTEM", "MARKER", "Status"]].rename(columns={"Status": f"{agent_a} Status"}).merge(
        agent_b_rows[["SYSTEM", "MARKER", "Status"]].rename(columns={"Status": f"{agent_b} Status"}), on=["SYSTEM", "MARKER"], how="outer",
    ).fillna("Missing")

    merged["Differs"] = merged[f"{agent_a} Status"] != merged[f"{agent_b} Status"]
    n_differ = int(merged["Differs"].sum())

    c1, c2 = st.columns(2)
    c1.metric("Readouts compared",              f"{len(merged):,}")
    c2.metric("Readouts with different status", f"{n_differ:,}", f"{100*n_differ/max(len(merged),1):.0f}%")

    # Side-by-side heatmaps
    col1, col2 = st.columns(2)
    h = max(min(22 * agent_a_rows["MARKER"].nunique(), 600), 200)
    with col1:
        st.markdown(f"**{agent_a}**")
        hm_a = _readout_heatmap(agent_a_rows, status_col="Status", domain=_PRESENT_DOMAIN, colors=_PRESENT_RANGE)
        st.altair_chart(hm_a, width="stretch")
    with col2:
        st.markdown(f"**{agent_b}**")
        hm_b = _readout_heatmap(agent_b_rows, status_col="Status", domain=_PRESENT_DOMAIN, colors=_PRESENT_RANGE)
        st.altair_chart(hm_b, width="stretch")


#######################################################
###                 TAB RENDERING                   ###
#######################################################


def render(df: pd.DataFrame, denom: int=148) -> None:

    st.title("Gap Finder")
    st.caption(f"Examination of which of the {denom} Diversity PLUS System:Marker readouts each agent has\n\n"
               "**Present** = observed, **Missing** = not observed, **Partial** = some readouts observed, not all.")
    
    # Settings row
    view = st.radio("View", ["Single agent", "Multi-agent", "Agent diff"], horizontal=True, key="gap_view",)
    
    st.divider()

    with st.spinner("Loading gap data..."):
        readout_grid    =  helper_data_loader.load_readout_grid()
        agent_summary   =  helper_data_loader.load_agent_summary()
        #multi_grid      =  helper_data_loader.load_multi_grid()

    if view == "Single agent":
        _render_single_agent(readout_grid, agent_summary, denom=denom)
    elif view == "Multi-agent":
        _render_multi_agent(readout_grid, agent_summary, denom=denom)
    else:
        _render_agent_diff(readout_grid, agent_summary, denom=denom)