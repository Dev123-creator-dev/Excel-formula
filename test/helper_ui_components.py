import pandas as pd
import streamlit as st
import io
from pathlib import Path
import helper_general
import helper_plot_profiles
import helper_data_loader

"""
User interface components for dimension filtering of System, Marker, Agent in sidebar of MEGA Streamlit application
"""

FUZZY_THRESHOLD:   int       = 80 #This is the minimum WRatio score to auto-accept a fuzzy match
FUZZY_SUGGEST_MIN: int       = 60 #This is the minimum score to surface a "did you mean?" suggestion

FILTERABLE_COLUMNS: list[str] = ["SYSTEM", "MARKER", "AGENT"]

BASE_PATH = Path("data/snapshots")

@st.cache_data
def load_excel_bytes(path):
    with open(path, "rb") as f:
        return f.read()

def init_session_state():

    """
    Initialize session state keys exactly once
    If not done, user selections are destroyed every time a user interacts with any widget.
    """

    defaults = {
        "accepted_canonicals":      {col: set() for col in FILTERABLE_COLUMNS},
        "pending_suggestions":      {col: {} for col in FILTERABLE_COLUMNS},
        "last_column":              FILTERABLE_COLUMNS[0],
        "export_ready":             False,
        "export_zip_bytes":         None,
        "export_zip_name":          None,
        "raw_df":                   None,
        "conc_col":                 "CONCENTRATION",
        "unit_col":                 "UNIT",
    }

    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

def render_sidebar(raw_df: pd.DataFrame) -> None:

    """
    Set up Streamlit application's sidebar with options for System, Marker, Agent
    """

    with st.sidebar:
        
        st.markdown("### Filters")
        st.caption("Selections apply to Exporter tab only.")

        column_picked: str = st.selectbox("Filter by dimension", options=FILTERABLE_COLUMNS, key="sidebar_column_picker")

        #Clear pending suggestions when user switches choice of dimension
        if st.session_state.last_column != column_picked:
            st.session_state.pending_suggestions[st.session_state.last_column] = {}
            st.session_state.last_column = column_picked

        render_canonical_filter(column_picked)
        
        st.markdown("---")
        render_active_filter_summary()
        
        #Row count feedback
        filtered_df = helper_general.resolve_canonicals_to_df(raw_df)
        n_raw = len(raw_df)
        n_filt = len(filtered_df)
        if n_filt < n_raw:
            st.caption(f"Showing **{n_filt:,}** / {n_raw:,} rows after filters")

        st.markdown("---")
        st.markdown("### Data snapshot")
        info = helper_data_loader.snapshot_info()
        if info["status"] == "current":
            st.success(f"Updated today at {info['last_updated']}")
        elif info["status"] == "stale":
            st.warning(f"Last updated {info['last_updated']}. Today's pull pending.")
        else:
            st.warning("No snapshot found. Using fallback data.")

        st.markdown("### Downloads")
        info = helper_data_loader.snapshot_info()
        last_updated = info.get("last_updated")
        date_str = last_updated.split(" ")[0].replace("-", "_")
        if last_updated:
            snap_parquet = BASE_PATH / f"snapshot_{date_str}.parquet"
            snap_csv = BASE_PATH / f"snapshot_{date_str}.csv"
            excel_name = BASE_PATH / f"MEGA_Export_{date_str}.xlsx"
            try:
                df = pd.read_parquet(snap_parquet)
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                st.download_button(
                    label="Download Raw Database Snapshot (CSV)",
                    data=csv_buffer.getvalue(),
                    file_name=snap_csv.name,
                    mime="text/csv"
                )
            except FileNotFoundError:
                st.caption("Raw database snapshot file not found.")
            try:
                excel_bytes = load_excel_bytes(excel_name)
                st.download_button(
                    label="Download MEGA Excel Export for Entire Database",
                    data=excel_bytes,
                    file_name=excel_name.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except FileNotFoundError:
                st.caption("MEGA export file for entire database not found.")
        else:
            st.caption("No downloadable files available.")

def on_multiselect_change(col: str, widget_key: str, display_to_canonical: dict, dropdown_set: set):

    """
    Only code where multiselect writes to accepted_canonicals
    Use after Streamlit has committed widget's new value to session_state
    Using session_state[widget_key] gives up-to-date user selection
    """

    selected_labels = st.session_state.get(widget_key, [])
    ms_ids = {display_to_canonical[lbl] for lbl in selected_labels if lbl in display_to_canonical}

    current = st.session_state.accepted_canonicals[col]
    paste_only = {cid for cid in current if cid not in {display_to_canonical[l] for l in dropdown_set if l in display_to_canonical}}

    st.session_state.accepted_canonicals[col] = ms_ids | paste_only

def render_canonical_filter(column_picked: str) -> None:

    """
    Render multiselect and paste box for one canonical dimension selected by the user.

    Write directly to st.session_state.accepted_canonicals and st.session_state.pending suggestions.
    """

    all_aliases, alias_map, canonical_to_db, db_col, dropdown = helper_general.find_column_options(column_picked)

    dropdown_set                =   set(dropdown)
    display_to_canonical        =   {canonical_to_db[cid]: cid for cid in canonical_to_db}

    current_accepted = st.session_state.accepted_canonicals[column_picked]
    initial_labels = sorted(canonical_to_db[cid] for cid in current_accepted if cid in canonical_to_db and canonical_to_db[cid] in dropdown_set)

    widget_key = f"ms_{column_picked}"
    st.multiselect(f"{column_picked}(S)", options=sorted(dropdown_set), default=initial_labels, key=widget_key, on_change=on_multiselect_change, args=(column_picked, widget_key, display_to_canonical, dropdown_set), placeholder=f"All {column_picked.lower()}s",)

    #Paste box
    with st.expander("Paste a list of names"):
        paste_input = st.text_area("Comma or new-line separated", key=f"paste_{column_picked}", height=100,)
        if st.button("Parse pasted names", key=f"parse_btn_{column_picked}"):
            if paste_input.strip():
                newly_accepted, new_suggestions, unmatched = helper_general.parse_paste_input(paste_input, column_picked, FUZZY_THRESHOLD, FUZZY_SUGGEST_MIN)
                if newly_accepted:
                    st.session_state.accepted_canonicals[column_picked].update(newly_accepted)
                    labels = sorted(canonical_to_db.get(c, c) for c in newly_accepted)
                    st.success(f"Added {len(newly_accepted)} item(s) to filters: "
                            f"{', '.join(labels)}")
                if new_suggestions:
                    st.session_state.pending_suggestions[column_picked].update(new_suggestions)
                    st.info(f"{len(new_suggestions)} item(s) need review below")
                if not newly_accepted and not new_suggestions:
                    st.warning("No items could be matched.")
            else:
                st.info("Nothing to parse: text box is empty.")
    
    pending = st.session_state.pending_suggestions[column_picked]
    if pending:
        st.subheader("Review fuzzy matches")
        st.caption("These items were close but not certain matches. Please accept or reject each.")
        to_remove = []
        for raw_item, (canonical_id, display_label, score) in list(pending.items()):
            col1, col2, col3 = st.columns([4, 1, 1])
            col1.write(f'**"{raw_item}" → *{display_label}* (score: {score:.0f})')
            if col2.button("Accept", key=f"acc_{column_picked}_{canonical_id}"):
                st.session_state.accepted_canonicals[column_picked].add(canonical_id)
                to_remove.append(raw_item)
            if col3.button("Reject", key=f"rej_{column_picked}_{canonical_id}"):
                to_remove.append(raw_item)
        for k in to_remove:
            del st.session_state.pending_suggestions[column_picked][k]
        if to_remove:
            st.rerun()

def render_active_filter_summary() -> None:

    """
    Show compact read-only summary of active filters across every dimension, and allow user to clear all filters if desired.
    """
    
    has_any = any(st.session_state.accepted_canonicals[c] for c in FILTERABLE_COLUMNS)
    if not has_any:
        st.caption("No filters are active. Showing all data.")
        return
    st.markdown("**Active filters**")
    for col in FILTERABLE_COLUMNS:
        ids = st.session_state.accepted_canonicals[col]
        if not ids:
            continue
        try:
            _, _, c2db, _, _ = helper_general.find_column_options(col)
            labels = sorted(c2db.get(cid, cid) for cid in ids)
        except Exception:
            labels = sorted(str(x) for x in ids)
        
        #Truncate long lists
        display = ", ".join(labels[:5])
        if len(labels) > 5:
            display += f" +{len(labels)-5} more"
        st.caption(f"**{col}:** {display}")

        #Clear button
        if any(st.session_state.accepted_canonicals[c] for c in FILTERABLE_COLUMNS):
            if st.button(f"x Clear all {col} filters", width="stretch", key=f"clear_all_filters_btn_{col}"):
                for col in FILTERABLE_COLUMNS:
                    st.session_state.accepted_canonicals[col] = set()
                    st.session_state.pending_suggestions[col] = {}
                st.rerun()  
