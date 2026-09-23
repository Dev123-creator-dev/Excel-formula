import pandas as pd
import altair as alt
import streamlit as st
import numpy as np

import helper_general
import helper_data_loader

"""
Helper function that examines landscape of the data: What does BioMap dataset look like, what is covered, and how well is it covered?

Including:
    - Headline metrics
    - Coverage completeness per agent
    - Distribution explorer of system, marker, agent counts
    - System x Marker heatmap (observation counts)
    - Concentration profile: histogram and per-agent table
"""

FILTERABLE_COLUMNS = ["SYSTEM", "MARKER", "AGENT"]

_STATUS_DOMAIN = ["Complete", "Partial", "Missing"]
_STATUS_RANGE = ["#3cb44b", "#ffe119", "#e6194B"]

def _render_headline_metrics(agent_summary: pd.DataFrame, sys_marker: pd.DataFrame, dim_counts: pd.DataFrame, denom: int,) -> None:

    """
    Output metrics such as total rows, total number of unique agents, and total coverage
    """

    n_agents    = len(agent_summary)
    n_systems   = dim_counts[dim_counts["Dimension"] == "SYSTEM"]["Value"].nunique()
    n_markers   = dim_counts[dim_counts["Dimension"] == "MARKER"]["Value"].nunique()
    n_rows      = dim_counts[dim_counts["Dimension"] == "AGENT"]["Count"].sum()

    n_full      = int((agent_summary["Status"] == "Complete").sum())
    n_partial   = int((agent_summary["Status"] == "Partial").sum())
    n_none      = int((agent_summary["Status"] == "Missing").sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total rows",                     f"{n_rows:,}")
    c2.metric("Unique agents",                  f"{n_agents:,}")
    c3.metric("Unique systems",                 f"{n_systems:,}")
    c4.metric("Unique markers",                 f"{n_markers:,}")

    st.markdown("##### Agent profile completeness")
    d1, d2, d3 = st.columns(3)
    d1.metric("Full profiles", f"{n_full:,}", f"{100*n_full/max(n_agents,1):.0f}% of agents",)
    d2.metric("Partial profiles", f"{n_partial:,}", f"{100*n_partial/max(n_agents,1):.0f}% of agents",)
    d3.metric("No readouts", f"{n_none:,}", f"{100*n_none/max(n_agents,1):.0f}% of agents",)

def _render_coverage_tiers(agent_summary: pd.DataFrame, denom: int) -> None:

    st.subheader("Agent coverage distribution")
    st.caption("How many agents fall into each coverage band.\nEach bar equals the number of agents with that % of the panel observed.")

    bins    = [0, 25, 50, 75, 90, 99, 100]
    labels  = ["0-25%", "26-50%", "51-75%", "76-90%", "91-99%", "100%"]

    binned  = pd.cut(agent_summary["PctComplete"], bins=bins, labels=labels, include_lowest=True)
    tier_counts = (binned.value_counts().reindex(labels, fill_value=0).reset_index().rename(columns={"index": "Coverage tier", "PctComplete": "Agents", "count": "Agents"}))
    tier_counts.columns = ["Coverage tier", "Agents"]

    chart = (alt.Chart(tier_counts).mark_bar(cornerRadiusEnd=4, color="#3b82f6").encode(
        x=alt.X("Coverage tier:N", sort=labels, title="Coverage band"),
        y=alt.Y("Agents:Q", title="Number of agents"),
        tooltip=[alt.Tooltip("Coverage tier:N"), alt.Tooltip("Agents:Q", format=","),],
    ).properties(height=250))

    st.altair_chart(chart, width="stretch")

def _render_full_profiles_per_system(full_per_system: pd.DataFrame) -> None:
    
    st.subheader("Full profiles per system")
    st.caption("For each system, how many agents have observations for **every marker** in that system.")

    plot_df = full_per_system.sort_values("PctFull", ascending=True)
    
    bar = (alt.Chart(plot_df).mark_bar(cornerRadiusEnd=4).encode(
               x=alt.X("PctFull:Q", title="% of tested agents with full profile", scale=alt.Scale(domain=[0,100])),
               y=alt.Y("SYSTEM:N", sort=None, title="System"),
               color=alt.Color("PctFull:Q", scale=alt.Scale(scheme="redyellowgreen", domain=[0,100]), legend=None,),
               tooltip=[
                   alt.Tooltip("SYSTEM:N",                  title="System"),
                   alt.Tooltip("AgentsWithFullProfile:Q",   title="Agents with full profile",       format=","),
                   alt.Tooltip("AgentsTested:Q",            title="Agents tested",                  format=","),
                   alt.Tooltip("PctFull:Q",                 title="% full",                         format=".1f"),
               ]
           ).properties(height=max(min(32 * len(plot_df), 600), 180)))
    
    st.altair_chart(bar, width="stretch")

    with st.expander("Full profiles per system", expanded=False):
        st.dataframe(plot_df.rename(columns={
            "AgentsWithFullProfile":        "Agents with full profile",
            "AgentsTested":                 "Agents tested",
            "PctFull":                      "% full",
        }).sort_values("% full", ascending=False).reset_index(drop=True), width="stretch", hide_index=True,)

def _render_agent_coverage(agent_summary: pd.DataFrame, denom: int) -> None:

    st.subheader("Coverage completeness per agent")
    st.caption("Percentage of System:Marker slots that have at least one observation per agent.\n"
               "Sorted by coverage ascending to highlight agents with low coverage.")

    bar = (alt.Chart(agent_summary).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("PctComplete:Q", title="% of System:Marker readouts covered", scale=alt.Scale(domain=[0, 100]),),
        y=alt.Y("AGENT:N", sort=alt.EncodingSortField("PctComplete", order="ascending"), title="Agent"),
        color=alt.Color("Status:N", scale=alt.Scale(domain=_STATUS_DOMAIN, range=_STATUS_RANGE), legend=alt.Legend(title="Status"),),
        tooltip=[
            alt.Tooltip("AGENT:N", title="Agent"),
            alt.Tooltip("Status:N", title="Status"),
            alt.Tooltip("PctComplete:Q", title="PctComplete", format=".1f"),
            alt.Tooltip("ObservedReadouts:Q", title="Observed readouts", format=","),
            alt.Tooltip("MissingReadouts:Q", title="Missing readouts", format=","),],
    ).properties(height=max(min(28 * len(agent_summary), 700), 200))
    )

    rule = (alt.Chart(pd.DataFrame({"x": [80]})).mark_rule(color="#64748b", strokeDash=[4,4]).encode(x="x:Q"))

    st.altair_chart(bar + rule, width="stretch")
    st.caption("Dashed line represents 80% coverage threshold")


#######################################################
###             DISTRIBUTION EXPLORER               ###
#######################################################

def _render_distribution_explorer(dim_counts: pd.DataFrame) -> None:

    st.subheader("Distribution explorer")
    st.caption("Observation counts per value for a chosen dimension")

    col_ctrl, col_n = st.columns([2, 1])
    with col_ctrl:
        dim = st.selectbox("Dimension", FILTERABLE_COLUMNS, key="landscape_dist_dim",)
    
    with col_n:
        top_n = st.slider("Top N", 5, 100, 20, 5, key="landscape_top_n")

    counts = (dim_counts[dim_counts["Dimension"] == dim]
              .drop(columns="Dimension")
              .rename(columns={"Value": dim})
              .sort_values("Count", ascending=False)
              .head(top_n)
              .reset_index(drop=True)
            )

    chart = (alt.Chart(counts).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("Count:Q", title="Observations"),
        y=alt.Y(f"{dim}:N", sort="-x", title=dim),
        color=alt.Color("Count:Q", scale=alt.Scale(scheme="blues"),legend=None,),
        tooltip=[alt.Tooltip(f"{dim}:N"), alt.Tooltip("Count:Q", title="Observations", format=","),],
    ).properties(height=max(min(28 * len(counts), 600), 200)))

    st.altair_chart(chart, width="stretch")

#######################################################
###             SYSTEM:MARKER HEATMAP               ###
#######################################################


def _render_system_marker_heatmap(sys_marker: pd.DataFrame) -> None:

    """
    Create cross-filtered heatmap
    """

    st.subheader("System:Marker observation heatmap")
    st.caption("Click a system in the legend to highlight it.")

    selection = alt.selection_point(fields=["SYSTEM"], bind="legend", name="SystemSelect")

    chart = (alt.Chart(sys_marker).mark_rect().encode(
        x=alt.X("SYSTEM:N", title="System", axis=alt.Axis(labelAngle=-35)),
        y=alt.Y("MARKER:N", title="Marker"),
        color=alt.Color("Count:Q", scale=alt.Scale(scheme="blues"), title="Observations",),
        opacity=alt.condition(selection, alt.value(1.0), alt.value(0.2)),
        tooltip=[
            alt.Tooltip("SYSTEM:N", title="System"),
            alt.Tooltip("MARKER:N", title="Marker"),
            alt.Tooltip("Count:Q", title="Observations", format=","),
            ],
        ).add_params(selection).properties(height=max(min(24 * sys_marker["MARKER"].nunique(), 700), 250))
    )

    st.altair_chart(chart, width="stretch")

    with st.expander("Pivot Table", expanded=False):
        pivot = sys_marker.pivot_table(index="MARKER", columns="SYSTEM", values="Count", fill_value=0)
        st.dataframe(pivot, width="stretch")

def _render_underrepresented(marker_agent: pd.DataFrame) -> None:

    st.subheader("Least-covered markers")
    st.caption("Markers observed for the fewest distinct agents: useful for identifying systematic gaps in dataset.")

    plot_df = marker_agent.sort_values("AgentCount", ascending=True).head(20)

    chart = (alt.Chart(plot_df).mark_bar(cornerRadiusEnd=4, color="#f59e0b").encode(
        x=alt.X("AgentCount:Q", title="Distinct agents with this marker"),
        y=alt.Y("MARKER:N", sort=None, title="Marker"),
        tooltip=[
            alt.Tooltip("MARKER:N", title="Marker"),
            alt.Tooltip("AgentCount:Q", title="Agent with readout", format=","),
        ],
    ).properties(height=max(min(28*len(plot_df), 600), 200)))

    st.altair_chart(chart, width="stretch")

#######################################################
###          RENDER FULL TAB FUNCTIONALITY          ###
#######################################################

def render(denom: int = 148) -> None:

    st.header("Dataset Information")
    st.caption("Understand shape and coverage of the BioMAP database.")

    with st.spinner("Loading dataset information..."):
        agent_summary   =   helper_data_loader.load_agent_summary()
        sys_marker      =   helper_data_loader.load_sys_mrk_counts_real()
        full_per_sys    =   helper_data_loader.load_full_per_system()
        marker_agent    =   helper_data_loader.load_marker_agent_counts()
        dim_counts      =   helper_data_loader.load_dim_counts()

    print("This is the agent summary from the render tab of dataset info:\n")
    print(agent_summary)

    _render_headline_metrics(agent_summary, sys_marker, dim_counts, denom=denom)
    st.divider()

    _render_coverage_tiers(agent_summary, denom=denom)
    st.divider()

    _render_full_profiles_per_system(full_per_sys)
    st.divider()

    _render_agent_coverage(agent_summary, denom=denom)
    st.divider()

    _render_distribution_explorer(dim_counts)
    st.divider()

    _render_system_marker_heatmap(sys_marker)
    st.divider()

    _render_underrepresented(marker_agent)