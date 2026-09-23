import pandas as pd
import re
import numpy as np
import streamlit as st
from rapidfuzz import process, fuzz
from datetime import datetime
import zipfile
import io
from io import BytesIO, StringIO
import os
import unicodedata
from pathlib import Path
from glob import glob
from typing import Optional, Tuple, List, Dict


"""
Helper function for shared data utilities:
    - Applying sidebar filters
    - Normalizing concentrations
    - Inferring expected experimental space
    - Calculating gap status and severity
    - Export helpers
"""

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

#######################################################
###         NORMALIZATION FUNCTIONS                 ###
#######################################################


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

# Unit normalization
_UNIT_MAP: dict[str, str] = {
    "nm": "nM", "nanomolar": "nM", "nano": "nM", "nano m": "nM",
    "um": "µM", "µm": "µM", "μm": "µM", "micromolar": "µM", "micro": "µM", "micro m": "µM",
    "mm": "mM", "millimolar": "mM", "milli": "mM", "milli m": "mM",
    "m": "M", "molar": "M",
    "ng": "ng", "ug": "µg", "µg": "µg", "mg": "mg",
}
_TO_uM: dict[str, float] = {"nM": 1e-3, "µM": 1.0, "mM": 1e3, "M": 1e6}


REQUIRED_COLUMNS: list[str] = ["SYSTEM", "MARKER", "AGENT", "CONCENTRATION", "UNITS"]
FILTERABLE_COLUMNS: list[str] = ["SYSTEM", "MARKER", "AGENT"]

_STATUS_DOMAIN: list[str] = ["Complete", "Partial", "Missing"]
_STATUS_RANGE: list[str] = ["#22c55e", "#f59e0b", "#ef4444"]

STATUS_COLOR_SCALE = {"domain": _STATUS_DOMAIN, "range": _STATUS_RANGE}

buffer = BytesIO()

import re
import unicodedata

DIVERSITY_PLUS = {'3C': ['CCL2/MCP-1', 'CD106/VCAM-1', 'CD141/Thrombomodulin', 'CD142/Tissue Factor', 'CD54/ICAM-1', 'CD62E/E-Selectin', 'CD87/uPAR', 'CXCL8/IL-8', 'CXCL9/MIG', 'HLA-DR', 'Proliferation', 'SRB'],
                  '4H': ['CCL2/MCP-1', 'CCL26/Eotaxin-3', 'CD106/VCAM-1', 'CD62P/P-selectin', 'CD87/uPAR', 'SRB', 'VEGFR2'],
                  'BE3C': ['CD54/ICAM-1', 'CD87/uPAR', 'CXCL10/IP-10', 'CXCL11/I-TAC', 'CXCL8/IL-8', 'CXCL9/MIG', 'EGFR', 'HLA-DR', 'IL-1alpha', 'Keratin 8/18', 'MMP-1', 'MMP-9', 'PAI-I', 'SRB', 'tPA', 'uPA'],
                  'BF4T': ['CCL2/MCP-1', 'CCL26/Eotaxin-3', 'CD106/VCAM-1', 'CD54/ICAM-1', 'CD90', 'CXCL8/IL-8', 'IL-1alpha', 'Keratin 8/18', 'MMP-1', 'MMP-3', 'MMP-9', 'PAI-I', 'SRB', 'tPA', 'uPA'],
                  'BT': ['B cell Proliferation', 'PBMC Cytotoxicity', 'Secreted IgG', 'sIL-17A', 'sIL-17F', 'sIL-2', 'sIL-6', 'sTNF-alpha'],
                  'CASM3C': ['CCL2/MCP-1', 'CD106/VCAM-1', 'CD141/Thrombomodulin', 'CD142/Tissue Factor', 'CD87/uPAR', 'CXCL8/IL-8', 'CXCL9/MIG', 'HLA-DR', 'IL-6', 'LDLR', 'M-CSF', 'PAI-I', 'Proliferation', 'SRB', 'Serum Amyloid A'],
                  'HDF3CGF': ['CCL2/MCP-1', 'CD106/VCAM-1', 'CD54/ICAM-1', 'CXCL10/IP-10', 'CXCL11/I-TAC', 'CXCL8/IL-8', 'CXCL9/MIG', 'Collagen I', 'Collagen III', 'EGFR', 'M-CSF', 'MMP-1', 'PAI-I', 'Proliferation_72hr', 'SRB', 'TIMP-1', 'TIMP-2'],
                  'KF3CT': ['CCL2/MCP-1', 'CD54/ICAM-1', 'CXCL10/IP-10', 'CXCL8/IL-8', 'CXCL9/MIG', 'IL-1alpha', 'MMP-9', 'PAI-I', 'SRB', 'TIMP-2', 'uPA'],
                  'LPS': ['CCL2/MCP-1', 'CD106/VCAM-1', 'CD141/Thrombomodulin', 'CD142/Tissue Factor', 'CD40', 'CD62E/E-Selectin', 'CD69', 'CXCL8/IL-8', 'IL-1alpha', 'M-CSF', 'SRB', 'sPGE2', 'sTNF-alpha'],
                  'MyoF': ['CD106/VCAM-1', 'CXCL8/IL-8', 'Collagen I', 'Collagen III', 'Collagen IV', 'Decorin', 'MMP-1', 'PAI-I', 'SRB', 'TIMP-1', 'alpha-SM Actin', 'bFGF'],
                  'SAg': ['CCL2/MCP-1', 'CD38', 'CD40', 'CD62E/E-Selectin', 'CD69', 'CXCL8/IL-8', 'CXCL9/MIG', 'PBMC Cytotoxicity', 'Proliferation', 'SRB'],
                  'lMphg': ['CCL2/MCP-1', 'CCL3/MIP-1alpha', 'CD106/VCAM-1', 'CD40', 'CD62E/E-Selectin', 'CD69', 'CXCL8/IL-8', 'IL-1alpha', 'M-CSF', 'SRB', 'SRB-Mphg', 'sIL-10']}

SYS_DICT_DP = {'HUVEC_IL-1b/TNF-a/IFN-g_24':                '3C',
               'HUVEC_IL-4/Histamine_24':                   '4H',
               'BrEPI_IL-1b/TNF-a/IFN-g_24':                'BE3C',
               'BrEPI/HDFn_IL-4/TNF-a_24':                  'BF4T',
               'B cell/PBMC_anti-IgM/SEBlo/TSSTlo_84':      'BT',
               'CASMC_HCL_IL-1b/TNF-a/IFN-g_24':            'CASM3C',
               'HDFn_IL-1b/TNF-a/IFN-g/EGF/FGF/PDGFbb_24':  'HDF3CGF',
               'HEK/HDFn_IL-1b/TNF-a/IFN-g/TGF-b_24':       'KF3CT',
               'HUVEC/PBMC_LPS_24':                         'LPS',
               'HLFa_TNF-a/TGF-b_48':                       'MyoF',
               'HUVEC/PBMC_SEB/TSST_24':                    'SAg',
               'HUVEC/Mphg_HCL_Zymosan_24':                 'lMphg',
              }

DIVPLUS_SYSTEMS = ["3C", "4H", "BE3C", "BF4T", "BT", "CASM3C", "HDR3CGF", "HDF3CGF", "KF3CT", "LPS", "MYOF", "SAG", "LMPHG"]
DIVPLUS_LONG = ['HUVEC_IL-1b/TNF-a/IFN-g_24', 'HUVEC_IL-4/Histamine_24', 'BrEPI_IL-1b/TNF-a/IFN-g_24', 'BrEPI/HDFn_IL-4/TNF-a_24',
                'B cell/PBMC_anti-IgM/SEBlo/TSSTlo_84', 'CASMC_HCL_IL-1b/TNF-a/IFN-g_24', 'HDFn_IL-1b/TNF-a/IFN-g/EGF/FGF/PDGFbb_24',
                'HDFn_IL-1b/TNF-a/IFN-g/EGF/FGF/PDGFbb_24', 'HEK/HDFn_IL-1b/TNF-a/IFN-g/TGF-b_24', 'HUVEC/PBMC_LPS_24', 'HLFa_TNF-a/TGF-b_48',
                'HUVEC/PBMC_SEB/TSST_24', 'HUVEC/Mphg_HCL_Zymosan_24']


def _norm(s: object) -> str:

    """
    Normalize text for reliable joining:
      - Unicode normalization (NFKC)
      - Map dash/minus and slash variants to '-' and '/'
      - Strip surrounding whitespace
      - Uppercase strings
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

    s = re.sub(r'[\s\u00A0\u200B\u200C\u200D\uFEFF]+', ' ', s).strip()

    s = s.strip()
    
    return s.upper()

def _norm_str(s: str) -> str:

    """
    Scalar normalization for dictionary keys
        - Strip leading and trailing whitespace
        - Replace underscores with a single space
        - Collapse runs of whitespace to one space.
        - Uppercase everything
    """

    s = s.strip()
    s = re.sub(r"_+", " ", s)
    s = re.sub(r"\s+", " ", s)

    return s.upper()

def _norm_series(series: pd.Series) -> pd.Series:

    """
    Vectorized string normalization:
        - Strip leading and trailing whitespace
        - Replace underscores and hypens with a single space
        - Collapse multiple spaces into one
        - Uppercase for case-insensitive matching

    Reutnrs new series: original series never mutated.
    """

    return (
        series.str.strip()
        .str.replace(r"_+", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.upper()
    )


def normalize(x: str) -> str:

    """
    Lowercase and collapse whitespace
    Used by all alias key lookups.
    """

    return re.sub(r"\s+", " ", x.strip().lower())

def _parse_numeric(x) -> float:
    if pd.isna(x):
        return np.nan
    try:
        return float(str(x).strip().replace(",", ""))
    except Exception:
        return np.nan
    
def _normalize_unit(u) -> Optional[str]:
    if pd.isna(u):
        return None
    key = str(u).strip().lower().replace("μ", "μ").replace("µ", "μ")

    return _UNIT_MAP.get(key, str(u).strip())

@st.cache_data(show_spinner=False)
def normalize_concentration(df: pd.DataFrame, conc_col: str = "CONCENTRATION", unit_col: str = "UNIT") -> pd.DataFrame:

    """
    Add four columns to df copy:
        - ConcValue: parsed numeric
        - Unit: normalized unit string
        - Conc_uM: value in uM; NaN if unknown or mass-based
        - ConcLabel: human-readable level like 10 uM
    """

    for col in (conc_col, unit_col):
        if col not in df.columns:
            raise ValueError(f"Column '{col} not found")
    
    out = df.copy()
    val = out[conc_col].map(_parse_numeric)
    unit = out[unit_col].map(_normalize_unit)

    conc_um = pd.array([v * _TO_uM[u] if (not pd.isna(v) and u in _TO_uM) else np.nan for v, u in zip(val, unit)], dtype=float,)

    def _label(v, u, um) -> str:
        if not pd.isna(v) and u is not None:
            return f"{v:g} {u}"
        if not pd.isna(um):
            return f"{um:g} µM" if um >= 1 else f"{um:.3g} µM"
        return "NA"
    
    label = [_label(v, u, um) for v, u, um in zip(val, unit, conc_um)]

    return out.assign(ConcValue=val, Unit=unit, Conc_uM=pd.Series(conc_um, index=out.index), ConcLabel=label)


#######################################################
###        DIMENSION FILTERING FUNCTIONS            ###
#######################################################


def resolve_canonicals_to_df(raw_df: pd.DataFrame) -> pd.DataFrame:

    """
    Read accepted_canonicals from st.session_state and return filtered copy of raw_df

    NOTE: diversity_plus_filter() runs FIRST (not last) because it's what converts the
    SYSTEM column from raw long names (e.g. "HUVEC_IL-1b/TNF-a/IFN-g_24") to the short
    codes (e.g. "3C") that the sidebar's canonical filters below compare against. Filtering
    by short code before that conversion happened would never match anything, since real
    snapshot/DB data never contains short codes in the raw SYSTEM column - only a
    pre-cleaned placeholder file happened to already have them, which is why this only
    showed up once real data was used.
    """

    filtered = diversity_plus_filter(raw_df)

    for col_key in FILTERABLE_COLUMNS:
        canonicals: set = st.session_state.get("accepted_canonicals", {}).get(col_key, set())
        if not canonicals:
            continue

        try:
            _, _, canonical_to_db, db_col, _ = find_column_options(col_key)
        except Exception:
            continue

        db_values = {canonical_to_db[c] for c in canonicals if c in canonical_to_db}
        if db_values and db_col in filtered.columns:
            filtered = filtered[filtered[db_col].isin(db_values)]

    return filtered

def load_mappings(system_map_csv = DATA_DIR / "viewer_system_names.csv", marker_map_csv= DATA_DIR / "viewer_marker_names.csv"):

    sys_map = {}
    mrk_map = {}
    if system_map_csv:
        sm = pd.read_csv(system_map_csv)
        sys_map = dict(zip(sm["long_system_name"].astype(str).map(_norm), sm["display_name"].astype(str).map(_norm)))
    if marker_map_csv:
        mm = pd.read_csv(marker_map_csv)
        mrk_map = dict(zip(mm["long_marker_name"].astype(str).map(_norm), mm["short_marker_name"].astype(str).map(_norm)))
    
    return sys_map, mrk_map

SYS_MAP, MRK_MAP = load_mappings()

def diversity_plus_filter(full_df: pd.DataFrame) -> pd.DataFrame:

    """
    MEGA only handles DiversityPlus, so filter to only the systems and readouts relevant for DivPlus.
    """

    print("This is the dataframe that is passed to helper_general.diversity_plus_filter:\n")
    print(full_df.head(10))

    # Filter to only CLIENT == BioSeek
    df = full_df[full_df["CLIENT"].str.strip().str.upper() == "BIOSEEK"]
    
    # Normalize  long -> short system name lookup
    norm_sys_map: dict = {}
    for long_name, short in SYS_DICT_DP.items():
        short_str = short[0] if isinstance(short, list) else short
        norm_sys_map[_norm_str(long_name)] = short_str

    valid_short_names = {_norm_str(v[0] if isinstance(v, list) else v) for v in SYS_DICT_DP.values()}
    norm_system = _norm_series(df["SYSTEM"])

    mapped_system = norm_system.map(norm_sys_map)

    df = df.copy()
    df["SYSTEM"] = norm_system.where(norm_system.isin(valid_short_names), mapped_system)
    print("df after system normalization: ", df)
    df = df.dropna(subset=["SYSTEM"])

    # Build flat set of system_UPPER, marker_UPPER valid pairs from DIVERSITY_PLUS for 0(1) membership testing
    valid_pairs: set[tuple[str, str]] = {
        (_norm_str(sys_short), _norm_str(marker))
        for sys_short, markers in DIVERSITY_PLUS.items()
        for marker in markers
    }

    # Re-normalize short system names and marker column for matching 
    norm_short_system = _norm_series(df["SYSTEM"])
    norm_marker = _norm_series(df["MARKER"])

    # Build combined key Series -> tuple and check membership against valid_pairs set
    pair_mask = pd.Series(
        list(zip(norm_short_system, norm_marker)),
        index=df.index,
        dtype=object,
    ).isin(valid_pairs)

    df = df.loc[pair_mask]

    print("This is the DiversityPLUS filtered dataframe after helper_general.diversity_plus_filter:\n")
    print(df)

    return df.reset_index(drop=True)

def build_lookup(df: pd.DataFrame, prefix: str, db_column: str):

    """
    Build alias lookup structures from an example CSV.
    Every column in CSV is treated as synonym for the same entry.
    db_column provides authoritative value stored by databse.
    """

    alias_to_canonical:     dict = {}
    canonical_to_db:        dict = {}
    dropdown_options:       list = []

    for idx, row in df.iterrows():
        canonical_id = f"{prefix}_{idx}"
        db_value = str(row[db_column]).strip()

        canonical_to_db[canonical_id] = db_value
        dropdown_options.append(db_value)

        #Collect all synonyms from row
        for col in df.columns:
            raw = str(row[col]).strip()
            if not raw or raw.lower() == "nan":
                continue

            #Register both raw lowercased version and whitespace-normalized version
            alias_to_canonical.setdefault(raw.lower(), canonical_id)
            alias_to_canonical.setdefault(normalize(raw), canonical_id)

    return alias_to_canonical, canonical_to_db, dropdown_options

@st.cache_data(show_spinner=False)
def find_column_options(column_picked: str):

    """
    With the column selected by the user, identify the potential options the user could want to select for an output.
    If SYSTEM selected, load viewer_system_names.csv to pull both long and short system names.
    If MARKER selected, load viewer_marker_names.csv to pull both long and short marker names.
    If AGENT selected, load unique_AGENT.csv to pull options of agents.
    """

    if column_picked == "SYSTEM":
        df = pd.read_csv(DATA_DIR / "diversity_plus_viewer_system_names.csv")
        alias_map, canonical_to_db, dropdown = build_lookup(df, "SYS", "display_name")
        db_col = "SYSTEM"

    elif column_picked == "MARKER":
        df = pd.read_csv(DATA_DIR / "diversity_plus_viewer_marker_names.csv")
        alias_map, canonical_to_db, dropdown = build_lookup(df, "MRK", "long_marker_name")
        db_col = "MARKER"
       
    elif column_picked == "AGENT":
        df = pd.read_csv(DATA_DIR / "unique_AGENT.csv")
        alias_map, canonical_to_db, dropdown = build_lookup(df, "AGT", "AGENT")
        db_col = "AGENT"

    else:
        raise ValueError(f"Unknown column_picked value: {column_picked!r}")

    all_aliases = sorted(alias_map.keys())

    return all_aliases, alias_map, canonical_to_db, db_col, dropdown

def parse_paste_input(paste_text: str, column_picked: str, fuzzy_threshold: int, fuzzy_suggest_min: int) -> tuple[set, dict]:

    """
    Splits paste_text on commas and newlines, then for each token:
       1. Exact normalized match → immediately accepted into canonicals.
       2. Fuzzy match score >= FUZZY_THRESHOLD → auto-accepted into canonicals.
       3. Fuzzy match score >= FUZZY_SUGGEST_MIN → added to pending_suggestions for user review.
       4. No match → reported to user.
    """

    _, alias_map, canonical_to_db, _, _ = find_column_options(column_picked)

    raw_items = [t.strip() for t in re.split(r"[,\n]+", paste_text) if t.strip()]
    newly_accepted:     set = set()
    new_suggestions:    dict = {} # raw item → (canonical_id, display_label, score)
    unmatched:          list = []

    alias_keys = list(alias_map.keys())

    for item in raw_items:
        key = normalize(item)

        #1. Exact match → immediately accepted into canonicals
        if key in alias_map:
            newly_accepted.add(alias_map[key])
            continue

        #2. and 3. Fuzzy matching
        result = process.extractOne(key, alias_keys, scorer=fuzz.WRatio)
        if result:
            matched_alias, score, _ = result
            canonical_id = alias_map[matched_alias]
            display_label = canonical_to_db[canonical_id]
            if score >= fuzzy_threshold:
                newly_accepted.add(canonical_id)
            elif score >= fuzzy_suggest_min:
                new_suggestions[item] = (canonical_id, display_label, score)
            else:
                unmatched.append(item)
        else:
            unmatched.append(item)

    return newly_accepted, new_suggestions, unmatched


#######################################################
###             GAP ANALYSIS HELPERS                ###
#######################################################


@st.cache_data(show_spinner=False)
def infer_expectations(df: pd.DataFrame, conc_mode: str="global", conc_col: str = "CONCENTRATION", unit_col: str = "UNIT",) -> Tuple[pd.DataFrame, pd.DataFrame]:

    """
    Returns
        1) expected_sm: DataFrame[System, Marker]
        2) expected_conc:
            - if global: Dataframe[Conc_uM]
            - if per_agent: DataFrame[Agent, Conc_uM]
    """
        
    #Build normalized columns
    ndf = normalize_concentration(df, conc_col=conc_col, unit_col=unit_col)

    expected_sm = ndf[["SYSTEM", "MARKER"]].drop_duplicates().reset_index(drop=True)

    if conc_mode == "per_agent":
        expected_conc = (ndf[["AGENT", "Conc_uM"]].dropna().drop_duplicates().sort_values(["AGENT", "Conc_uM"], kind="mergesort").reset_index(drop=True))
    else:
        expected_conc  = (ndf[["Conc_uM"]].dropna().drop_duplicates().sort_values(["Conc_uM"], kind="mergesort").reset_index(drop=True))

    return expected_sm, expected_conc

def _build_expected_grid(agents: List[str], expected_sm: pd.DataFrame, expected_conc: pd.DataFrame, conc_mode: str,) -> pd.DataFrame:

    agents_df = pd.DataFrame({"AGENT": agents})
    base = (agents_df.assign(_k=1).merge(expected_sm.assign(_k=1), on="_k").drop(columns="_k"))
    if "AGENT" in expected_conc.columns and conc_mode == "per_agent":
        return base.merge(expected_conc.rename(columns={"Conc_uM": "Expected_Conc_uM"}), on="AGENT", how="left")
    else:
        return base.assign(_k=1).merge(expected_conc.assign(_k=1).rename(columns={"Conc_uM": "Expected_Conc_uM"}), on="_k").drop(columns="_k")

@st.cache_data(show_spinner=False)
def compute_gaps(df: pd.DataFrame, conc_mode: str = "global", conc_col: str = "CONCENTRATION", unit_col: str = "UNIT", agents: Optional[Tuple[str, ...]] = None, ) -> Tuple[pd.DataFrame, pd.DataFrame]:

    """
    Core gap engine that returns:
        - gap_table: AGENT, SYSTEM, MARKER, ObservedConc, ExpectedConc, Status, GapSeverity, PctComplete
        - conc_table: AGENT, SYSTEM, MARKER, Conc_uM_Expected, ExpectedConcLabel, Conc_uM, ConcLabel, Present
    """

    expected_sm, expected_conc = infer_expectations(df, conc_mode=conc_mode, conc_col=conc_col, unit_col=unit_col)

    agent_list = list(agents) if agents else sorted(df["AGENT"].dropna().unique().tolist())
    ndf = normalize_concentration(df, conc_col=conc_col, unit_col=unit_col)

    observed = (ndf[["AGENT", "SYSTEM", "MARKER", "Conc_uM", "ConcLabel"]].dropna(subset=["Conc_uM"]).drop_duplicates())

    grid = _build_expected_grid(agent_list, expected_sm, expected_conc, conc_mode)

    conc_table = grid.merge(observed.assign(Present=True), left_on=["AGENT", "SYSTEM", "MARKER", "Expected_Conc_uM"], right_on=["AGENT", "SYSTEM", "MARKER", "Conc_uM"], how="left",)
    conc_table["Present"] = conc_table["Present"].fillna(False)

    def _label_uM(um) -> str:
        if pd.isna(um):
            return "NA"
        return f"{um:g} µM" if um >= 1 else f"{um:.3g} µM"
    
    conc_table["ExpectedConcLabel"] = conc_table["Expected_Conc_uM"].map(_label_uM)

    agg = (conc_table.groupby(["AGENT", "SYSTEM", "MARKER"], as_index=False).agg(ObservedConc=("Present", "sum"), ExpectedConc=("Present", "size")))

    def _classify(row) -> str:
        if row["ObservedConc"] == 0:
            return "Missing"
        if row["ObservedConc"] < row["ExpectedConc"]:
            return "Partial"
        return "Complete"
    
    agg["Status"] = agg.apply(_classify, axis=1)

    agg["GapSeverity"] = ((agg["Status"] == "Missing").astype(int) * 2 + (agg["Status"] == "Partial").astype(int)) * agg["ExpectedConc"]
    agg["PctComplete"] = (100 * agg["ObservedConc"] / agg["ExpectedConc"].clip(lower=1)).round(1)

    conc_out = (conc_table[["AGENT", "SYSTEM", "MARKER", "Expected_Conc_uM", "ExpectedConcLabel", "Conc_uM", "ConcLabel", "Present"]].rename(columns={"Expected_Conc_uM": "Conc_uM_Expected"}).copy())

    return agg, conc_out

st.cache_data(show_spinner=False)
def compute_readout_gaps(df: pd.DataFrame, agents: Optional[Tuple[str, ...]] = None, denom: int=148) -> Tuple[pd.DataFrame, pd.DataFrame]:

    """
    Compute per-agent x system x marker readout prescense against the expected panel of 'denom' Sys:Marker pairs, 148 for DiversityPlus
    """

    filtered = diversity_plus_filter(df)
    all_agents = sorted(filtered["AGENT"].dropna().unique().tolist())
    agent_list = list(agents) if agents else all_agents

    # Canonical panel: all 148 DiversityPlus Sys:Mrk readouts
    panel = filtered[["SYSTEM", "MARKER"]].drop_duplicates().reset_index(drop=True)

    # Observed Agent x System x Marker triples
    observed = (filtered[["AGENT", "SYSTEM", "MARKER"]].drop_duplicates().assign(Observed=True))

    # Full expected grid: every agent x every Sys:Mrk pair
    agents_df = pd.DataFrame({"AGENT": agent_list})
    expected = (agents_df.assign(_k=1).merge(panel.assign(_k=1), on="_k").drop(columns="_k"))

    # Left join to find which expected readouts are absent
    readout_table = expected.merge(observed, on=["AGENT", "SYSTEM", "MARKER"], how="left")
    readout_table["Observed"] = readout_table["Observed"].fillna(False)
    readout_table["Status"] = readout_table["Observed"].map({True: "Present", False: "Missing"})

    # Agent-level summary
    agent_summary = (readout_table.groupby("AGENT", as_index=False)
                     .agg(ObservedReadouts=("Observed", "sum"))
                     .assign(ExpectedReadouts=denom)
                     .assign(MissingReadouts=lambda d: d["ExpectedReadouts"] - d["ObservedReadouts"])
                     .assign(PctComplete=lambda d: ( 100 * d["ObservedReadouts"] / d["ExpectedReadouts"]).round(1)))
    
    def _agent_status(row) -> str:
        if row["ObservedReadouts"] == 0:
            return "Missing"
        if row["ObservedReadouts"] < row["ExpectedReadouts"]:
            return "Partial"
        return "Present"
    
    agent_summary["Status"] = agent_summary.apply(_agent_status, axis=1)

    return readout_table.reset_index(drop=True), agent_summary.reset_index(drop=True)


def build_export_df(gap_table: pd.DataFrame, conc_table: pd.DataFrame, status_filter: str = "Missing or Parital", include_conc_detail: bool=True, system_marker_pairs: Optional[List[Dict]] = None, ) -> pd.DataFrame:

    _filter_map = {
        "Missing only":          ["Missing"],
        "Partial only":          ["Partial"],
        "Missing or partial":    ["Missing", "Partial"],
        "All statuses":          _STATUS_DOMAIN,
    }

    g = gap_table[gap_table["Status"].isin(_filter_map.get(status_filter, _STATUS_DOMAIN))].copy()

    if system_marker_pairs:
        sel_df = pd.DataFrame(system_marker_pairs).drop_duplicates()
        if not sel_df.empty:
            g = g.merge(sel_df, on=["SYSTEM", "MARKER"], how="inner")
    
    if include_conc_detail:
        c = conc_table.copy()
        miss = (c[~c["Present"]].groupby(["AGENT", "SYSTEM", "MARKER"], as_index=False).agg(MissingConcentrations=("ExpectedConcLabel", lambda s: ", ".join(sorted(s.dropna())))))
        pres = (c[c["Present"]].groupby(["AGENT", "SYSTEM", "MARKER"], as_index=False).agg(PresentConcentrations=("ConcLabel", lambda s: ", ".join(sorted(s.dropna())))))
        g = g.merge(miss, on=["AGENT", "SYSTEM", "MARKER"], how="left")
        g = g.merge(pres, on=["AGENT", "SYSTEM", "MARKER"], how="left")
    
    priority = ["AGENT", "SYSTEM", "MARKER", "Status", "PctComplete", "ObservedConc", "ExpectedConc", "GapSeverity", "MissingConcentrations", "PresentConcentrations"]
    ordered = [c for c in priority if c in g.columns]
    extra = [c for c in g.columns if c not in ordered]

    return (g[ordered + extra].sort_values(["GapSeverity", "AGENT", "SYSTEM", "MARKER"], ascending=[False, True, True, True]).reset_index(drop=True))


#######################################################
###               GENERAL UTILITIES                 ###
#######################################################


def df_to_csv_download(df: pd.DataFrame, filename: str):
    # Exports df to csv and adds a "Download" button to Streamlit app
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=f"Download Table", data=csv,
        file_name=filename, mime="text/csv"
    )


def zip_files(file_paths: list, zip_name_prefix: str = "Export_BioMAP") -> tuple:

    """
    Bundle a list of file paths into an in-memory zip
    """
    ts              = datetime.now().strftime("%Y%m%d_%H%M")
    zip_filename    = f"{zip_name_prefix}_{ts}.zip"

    buf = BytesIO()
    seen: dict = {} 
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in file_paths:
            arcname = os.path.basename(p)
            if arcname in seen:
                seen[arcname] += 1
                base, ext = os.path.splitext(arcname)
                arcname =   f"{base}_{seen[arcname]}{ext}"
            else:
                seen[arcname] = 0
            zf.write(p, arcname=arcname)
    buf.seek(0)

    return buf.getvalue(), zip_filename

def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Data") -> bytes:

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buf.getvalue()

def get_export_files(exports_dir="exports"):

    """
    Read existing export files for further functions
    """

    exports_path = Path(exports_dir)

    if not exports_path.exists():
        return []
    
    return sorted(exports_path.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)