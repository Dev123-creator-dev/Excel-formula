import pandas as pd
import unicodedata

# Map common dash/minus look-alikes to ASCII hyphen-minus
_DASH_EQUIVS = {
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non-breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2212": "-",  # minus sign
}

# Map common slash look-alikes to ASCII slash
_SLASH_EQUIVS = {
    "\u2215": "/",  # division slash
    "\u2044": "/",  # fraction slash
    "\uFF0F": "/",  # full-width slash
}

def _norm(s: object) -> str:

    """
    Normalize text for reliable joining:
      - Unicode normalization (NFKC)
      - Map dash/minus and slash variants to '-' and '/'
      - Strip surrounding whitespace
      - Optional lowercase for case-insensitive joins
    """

    if s is None:
        return ""
    s = str(s)

    # Unicode canonical/compatibility normalization
    s = unicodedata.normalize("NFKC", s)

    # Replace dash/minus look-alikes
    for k, v in _DASH_EQUIVS.items():
        s = s.replace(k, v)

    # Replace slash look-alikes
    for k, v in _SLASH_EQUIVS.items():
        s = s.replace(k, v)

    s = s.strip()
    return s

def load_mappings(system_map_csv = "data\\viewer_system_names.csv", marker_map_csv="data\\viewer_marker_names.csv"):

    sys_map = {}
    mrk_map = {}
    if system_map_csv:
        sm = pd.read_csv(system_map_csv)
        sys_map = dict(zip(sm["long_system_name"].astype(str), sm["display_name"].astype(str)))
    if marker_map_csv:
        mm = pd.read_csv(marker_map_csv)
        mrk_map = dict(zip(mm["long_marker_name"].astype(str), mm["short_marker_name"].astype(str)))
    
    return sys_map, mrk_map

SYS_MAP, MRK_MAP = load_mappings()

def convert_header(col):
    if ":" not in col:
        return col
    
    col = _norm(col)
    system_long, marker_long = col.split(":", 1)

    system_short = SYS_MAP.get(system_long, system_long)
    marker_short = MRK_MAP.get(marker_long, marker_long)

    return f"{system_short}:{marker_long}"

def diversity_plus_filter(df: pd.DataFrame) -> pd.DataFrame:

    """
    MEGA only handles DiversityPlus, so filter to only the systems and readouts relevant for DivPlus.
    """

    divplus_df = pd.read_csv("data\\sys_marker_header.csv")
    divplus_systems = divplus_df["SYSTEM_SHORT"].unique().tolist()
    divplus_markers = divplus_df["MARKER_SHORT"].unique().tolist()

    def _convert_sys(col):
        system_long = _norm(col)

        system_short = SYS_MAP.get(system_long, system_long)

        return system_short
    
    df["SYSTEM"] = df["SYSTEM"].map(_convert_sys)

    filtered_to_dp = df[df["SYSTEM"].isin(divplus_systems) & df["MARKER"].isin(divplus_markers)]
    filtered_to_bioseek = filtered_to_dp[filtered_to_dp["CLIENT"] == "BioSeek"]
    print(filtered_to_bioseek)

    return filtered_to_bioseek

def diversity_plus_filter_SYS(df: pd.DataFrame) -> pd.DataFrame:

    """
    MEGA only handles DiversityPlus, so filter to only the systems and readouts relevant for DivPlus.
    """

    divplus_df = pd.read_csv("data\\sys_marker_header.csv")
    divplus_systems = divplus_df["SYSTEM_SHORT"].unique().tolist()
    def _convert_sys(col):
        system_long = _norm(col)

        system_short = SYS_MAP.get(system_long, system_long)

        return system_short
    
    df["SYSTEM"] = df["SYSTEM"].map(_convert_sys)

    filtered_to_dp = df[df["SYSTEM"].isin(divplus_systems)]
    filtered_to_bioseek = filtered_to_dp[filtered_to_dp["CLIENT"] == "BioSeek"]
    print(filtered_to_bioseek)

    return filtered_to_bioseek

def diversity_plus_filter_MRK(df: pd.DataFrame) -> pd.DataFrame:

    """
    MEGA only handles DiversityPlus, so filter to only the systems and readouts relevant for DivPlus.
    """

    divplus_df = pd.read_csv("data\\sys_marker_header.csv")
    divplus_markers = divplus_df["MARKER_SHORT"].unique().tolist()

    filtered_to_dp = df[df["MARKER"].isin(divplus_markers)]

    return filtered_to_dp

def panel_filter(df: pd.DataFrame) -> pd.DataFrame:

    """
    Filter to Fibrosis, T Cell, CRC, and NSCLC panels
    """

    from giga.helper_general import FIBROSIS, T_CELL, CRC, NSCLC, FIBROSIS_SYS, T_CELL_SYS, CRC_SYS, NSCLC_SYS

    panels_dict     = FIBROSIS | T_CELL | CRC | NSCLC
    panels_sys_map  = FIBROSIS_SYS | T_CELL_SYS | CRC_SYS | NSCLC_SYS
    
    panel_systems = []
    panel_markers = []
    for sys, marker in panels_dict.items():
        sys     = _norm(sys)
        if sys not in panel_systems:
            panel_systems.append(sys)
        for mrk in marker:
            mrk = _norm(mrk)
            if mrk not in panel_markers:
                panel_markers.append(mrk)

    print("Combined panels dictionary: ", panels_dict)
    print("Panels system name map: ", panels_sys_map)
    print("Panel systems list: ", panel_systems)
    print("Panel marker list: ", panel_markers)

    df = df[df["CLIENT"] == "BioSeek"]

    def _convert_sys(col):
        system_long = _norm(col)

        system_short = panels_sys_map.get(system_long, system_long)

        return system_short
    
    df["SYSTEM"] = df["SYSTEM"].map(_convert_sys)
    print("df after system mapping: ", df)

    filtered_to_panel = df[df["SYSTEM"].isin(panel_systems) & df["MARKER"].isin(panel_markers)]
    print("df after filtering to systems and markers in the panel: ", filtered_to_panel)

    return filtered_to_panel

"""
sigma_df = pd.read_csv("data\\controls\\NONPROD_SingleRepeatControls_sigma.csv", delimiter="\t")
ctrl_df = pd.read_csv("data\\controls\\NONPROD_SingleRepeatControls.csv", delimiter="\t")

sigma_df.rename(columns={col: convert_header(col) for col in sigma_df.columns}, inplace=True)
ctrl_df.rename(columns={col: convert_header(col) for col in ctrl_df.columns}, inplace=True)

ctrl_df.to_csv("data\\controls\\NONPROD_SingleRepeatControls_Cleaned.csv")
sigma_df.to_csv("data\\controls\\NONPROD_SingleRepeatControls_sigma_Cleaned.csv")


db_sig_env = pd.read_csv("data\\controls\\vw_significane_envelope_nonprod_20260303.csv")
db_sig_env["SYS_READ"] = db_sig_env["SYS_READ"].map(convert_header)

db_sig_env.to_csv("data\\controls\\vw_significane_envelope_nonprod_20260303_Cleaned.csv", index=False)

db_export = pd.read_csv("data/20260204_export.csv", encoding="ISO-8859-1")
filtered_export = diversity_plus_filter(db_export)
filtered_export.to_csv("data\\DIVPLUS_FILTERED_20260204_export.csv", encoding="utf-8")

sys_names = pd.read_csv("data\\viewer_system_names.csv")
mrk_names = pd.read_csv("data\\viewer_marker_names.csv")

sys_names_fix = sys_names.rename(columns={'display_name': 'SYSTEM'})
mrk_names_fix = mrk_names.rename(columns={'long_marker_name': 'MARKER'})

sys_names_out = diversity_plus_filter_SYS(sys_names_fix)
mrk_names_out = diversity_plus_filter_MRK(mrk_names_fix)

sys_names_out = sys_names_out.rename(columns={"SYSTEM": 'display_name'})
mrk_names_out = mrk_names_out.rename(columns={"MARKER": 'long_marker_name'})

sys_names_out.to_csv("data/diversity_plus_viewer_system_names.csv")
mrk_names_out.to_csv("data/diversity_plus_viewer_marker_names.csv")
"""

db_export = pd.read_csv("data/vw_trusted_filtered_profiles_2026MAY06.csv", encoding="utf-8")
filtered_export = panel_filter(db_export)
filtered_export.to_csv("giga\\data\\giga_panel_filtered_2026MAY06.csv", encoding="utf-8", index=False)