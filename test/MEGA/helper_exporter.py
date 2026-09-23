import pandas as pd
import streamlit as st

import helper_general
import helper_table_creator
import helper_ui_components
#import helper_orcl_db
from helper_general import FILTERABLE_COLUMNS

from datetime import datetime
from io import BytesIO

buffer = BytesIO()

def run_export_with_progress(filtered_df: pd.DataFrame) -> list:

    """
    Wrap export pipeline in st.status block so user can see live step-by-step progress rather than a frozen screen.
    """

    date_str        = datetime.now().strftime("%Y%m%d_%H%M")
    xlsx_out        = f"exports/{date_str}_MEGA_Export.xlsx"

    with st.status("Running export pipeline...", expanded=True) as status:

        st.write(f" ▶ Rows examining for export: **{len(filtered_df):,}**")

        st.write("① Loading canonical reference and name mappings...") #Done by helper_table_creator.run_helper_table_creator
        st.write("② Building profiles from filtered dataset...")
        st.write("③ Computing significance envelope and hit bounds from control data...")
        st.write("④ Writing Excel output...")

        try:
            output_files = helper_table_creator.run_helper_table_creator(filtered_df, xlsx_out)
        except Exception as e:
            status.update(label="Export failed", state="error", expanded=True)
            st.error(f"Export error: {e}")
            return []
        
        if not output_files:
            status.update(label="Export produced no files", state="error")
            return []
        
        status.update(label="Export complete", state="complete", expanded=False)

    return output_files

def render(df: pd.DataFrame):

    st.title("Exporter")
    st.markdown("Export data from the BioMAP Oracle database.\n\nPlease use the sidebar to set System, Marker, and/or Agent filters.")

    has_any_filter = any(st.session_state.accepted_canonicals[col] for col in FILTERABLE_COLUMNS)
    if has_any_filter:
        st.subheader("Active filters")
        for col in FILTERABLE_COLUMNS:
            ids = st.session_state.accepted_canonicals[col]
            if ids:
                _, _, c2db, _, _ = helper_general.find_column_options(col)
                labels = sorted(c2db.get(cid, cid) for cid in ids)
                st.write(f"**{col}:** {', '.join(labels)}")
    else:
        st.info("No filters applied. Export will include all data.")

    df_for_export = helper_general.resolve_canonicals_to_df(df)
    selected_export = None

    #Export button
    st.divider()
    if st.button("Export BioMAP data", type="primary", use_container_width=True):
        st.session_state.export_ready       = False

        #orcl_df = helper_orcl_db.query_trusted_filtered_combined()
        #df_for_export = helper_general.resolve_canonicals_to_df(orcl_df)
        output_files = run_export_with_progress(df_for_export)
        if output_files:
            selected_export = output_files[0]
            for i in range(len(output_files)):
                try:
                    with open(output_files[i], "rb") as fh:
                        file_bytes = fh.read()
                except FileNotFoundError:
                    st.warning(f"Output file not found on disk: `{output_files[i]}`")
                    continue
                st.download_button(label="Download Excel workbook", data=file_bytes,
                                   file_name=output_files[i], mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                                   key=f"dl_{output_files[i]}", use_container_width=True)
            
            return selected_export, df_for_export
