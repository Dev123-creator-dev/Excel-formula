import streamlit as st
from rapidfuzz import process, fuzz
import pandas as pd
import warnings
import sys
import re
import os
from datetime import datetime
import zipfile
from io import BytesIO, StringIO

import helper_general
from helper_general import FILTERABLE_COLUMNS
import helper_data_loader
import helper_ui_components
import helper_exporter
import helper_plot_profiles
import helper_dataset_information
import helper_gap_analyzer
import helper_experiment_planner

os.environ["HR_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
warnings.filterwarnings("ignore")

FILTERABLE_COLUMNS      = ["System", "Marker", "Agent"]

st.set_page_config(
    page_title="MEGA",
    layout="wide",
    initial_sidebar_state="expanded",
)

#@st.cache_data(ttl=300)
def load_dummy_data() -> pd.DataFrame:
    # Loads flat export from database while waiting on port opening to BioMap database
    #return pd.read_excel("TRUSTED_FILTERED_COMBINED_PROFILE.xlsx")
    #return pd.read_excel("Test Data for Sarah.xlsx")
    #return pd.read_csv("data/20260204_export.csv", encoding="ISO-8859-1")
    return pd.read_csv("data/DIVPLUS_FILTERED_20260204_export.csv", encoding="utf-8")

def main():

    helper_ui_components.init_session_state()

    st.title("MEGA")

   # df = load_dummy_data()
    df = helper_data_loader.load_data()

    helper_ui_components.render_sidebar(df)
    filtered_df = helper_general.resolve_canonicals_to_df(df)

    tab_exp, tab_plot_profiles, tab_data_info, tab_gap_analyzer, tab_plan = st.tabs([
        "Exporter",
        "BioMAP Profile Viewer",
        "Dataset Information",
        "Gap Analyzer",
        "Experiment Planner",
    ])

    with tab_exp:
        helper_exporter.render(filtered_df)

    with tab_plot_profiles:
        #st.caption("Coming soon!")
        helper_plot_profiles.render(filtered_df)

    with tab_data_info:
        #st.caption("Coming soon!")
        helper_dataset_information.render(df)

    with tab_gap_analyzer:
        #st.caption("Coming soon!")
        helper_gap_analyzer.render(df)

    with tab_plan:
        #st.caption("Coming soon!")
        helper_experiment_planner.render(df)

if __name__ == "__main__":
    main()