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

"""
sigma_df = pd.read_csv("data\\controls\\NONPROD_SingleRepeatControls_sigma.csv", delimiter="\t")
ctrl_df = pd.read_csv("data\\controls\\NONPROD_SingleRepeatControls.csv", delimiter="\t")

sigma_df.rename(columns={col: convert_header(col) for col in sigma_df.columns}, inplace=True)
ctrl_df.rename(columns={col: convert_header(col) for col in ctrl_df.columns}, inplace=True)

ctrl_df.to_csv("data\\controls\\NONPROD_SingleRepeatControls_Cleaned.csv")
sigma_df.to_csv("data\\controls\\NONPROD_SingleRepeatControls_sigma_Cleaned.csv")
"""

db_sig_env = pd.read_csv("data\\controls\\vw_significane_envelope_nonprod_20260303.csv")
db_sig_env["SYS_READ"] = db_sig_env["SYS_READ"].map(convert_header)

db_sig_env.to_csv("data\\controls\\vw_significane_envelope_nonprod_20260303_Cleaned.csv", index=False)