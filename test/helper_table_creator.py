from __future__ import annotations
import pandas as pd
import re
import os
import csv
import unicodedata
import numpy as np
import math
import helper_envelope
from helper_envelope import (EnvelopeModel, EnvelopeService, update_workbook_envelope, NAME_SCREENING,)
from pathlib import Path
from math import ceil
from itertools import groupby
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.cell import WriteOnlyCell
from collections import OrderedDict as OD
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, OrderedDict, Sequence, Mapping, Union

"""
Helper that reads Oracle export, computes envelopes, and writes Excel export matching Java writer from BioMAP Viewer source code.
"""

SHEET_CYTOX = "Cytotoxicity"
SHEET_HITS = "Biomarker Hits"
SHEET_ENVELOPE = "Envelope"
SHEET_DATA = "Profile Data"
SHEET_ERROR = "Error Bar"

DEFAULT_ENVELOPE_VALUE = 0.1

TOX_CONTAINS = ("SRB", "VISUAL", "PBMC CYTOTOXICITY")
TOX_ENDSWITH = ("PI",)

SRB_THRESHOLD = -0.3
VISUAL_THRESHOLD = -9.0
PBMC_THRESHOLD = -0.3

SYSTEM_MARKER_PATTERN = re.compile(r"^([^:]+):(.+)$")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CTRL_DIR = DATA_DIR / "controls"

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

@dataclass
class Profile:
    """
    Profile container for values and errors keyed by System:Marker
    """
    key: Tuple
    display_name: str
    project_display_name: str
    values: Dict[Tuple[str, str], float] = field(default_factory=dict)
    errors: Dict[Tuple[str, str], float] = field(default_factory=dict)


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

Number = Union[int, float]

def extract_system_markers(sys_mrk_csv: str) -> "OrderedDict[str, List[str]]":

    """
    Use CSV listing all systems and corresponding markers for headers
    """

    df = pd.read_csv(sys_mrk_csv, dtype=str, encoding="utf-8")

    df["SYSTEM_SHORT"] = df["SYSTEM_SHORT"].map(_norm)
    df["MARKER_SHORT"] = df["MARKER_SHORT"].map(_norm)

    sys_to_markers: "OrderedDict[str, List[str]]" = OD()
    for _, row in df.iterrows():
        sys = row["SYSTEM_SHORT"]
        mrk = row["MARKER_SHORT"]
        if sys not in sys_to_markers:
            sys_to_markers[sys] = []
        if mrk not in sys_to_markers[sys]:
            sys_to_markers[sys].append(mrk)

    sys_to_markers = dict(sys_to_markers)

    return sys_to_markers

def build_linear_pairs(canonical: "OrderedDict[str, List[str]]") -> List[Tuple[str,str]]:

    """
    Flatten the canonical mapping from Viewer example export into a list of system, marker.
    Put pairs in order of occurence.
    """

    pairs: List[Tuple[str, str]] = []
    for s, markers in canonical.items():
        for m in markers:
            pairs.append((s, m))
    return pairs
    
def load_mappings(system_map_csv: Optional[str], marker_map_csv: Optional[str]):

    """
    Map long names to short names to support database names aligning with Viewer export names.
    """

    sys_map: Dict[str, str] = {}
    mrk_map: Dict[str, str] = {}
    if system_map_csv:
        sm = pd.read_csv(system_map_csv, dtype=str, encoding="utf-8")
        sys_map = dict(zip(sm["long_system_name"].astype(str).map(_norm), sm["display_name"].astype(str).map(_norm)))
    if marker_map_csv:
        mm = pd.read_csv(marker_map_csv, dtype=str, encoding="utf-8")
        mrk_map = dict(zip(mm["long_marker_name"].astype(str).map(_norm), mm["short_marker_name"].astype(str).map(_norm)))
    
    return sys_map, mrk_map

def build_profiles(df: pd.DataFrame,
        canonical: OrderedDict[str, List[str]],
        system_map: Dict[str, str],
        marker_map: Dict[str, str],
        group_keys: List[str],
        name_template: str ) -> List[Profile]:
    
    """
    Create profile where short names are used for systems and long names are used for markers.
    Use canonical spreadsheet (export from Brogan)
    Select one row per profile,system,marker, align to the export from Viewer, and collect values and errors.
    """

    d = df.copy() #Working copy

    #Map long to short using CSV mapping files first > use MARKER_CODE > MARKER
    d["SYSTEM_NORM"] = d["SYSTEM"].astype(str).map(_norm)
    d["SYSTEM_SHORT"] = (d["SYSTEM_NORM"].map(system_map).fillna(d["SYSTEM_NORM"]))

    #Markers
    d["MARKER_SHORT"] = d["MARKER"].astype(str)
    d["MARKER_SHORT"] = d["MARKER_SHORT"].map(_norm)

    #Use merge to speed up for large datasets
    canonical_df = pd.DataFrame(build_linear_pairs(canonical), columns=["SYSTEM_SHORT", "MARKER_SHORT"])
    canonical_df["SYSTEM_SHORT"] = canonical_df["SYSTEM_SHORT"].map(_norm)
    canonical_df["MARKER_SHORT"] = canonical_df["MARKER_SHORT"].map(_norm)

    d["_sys_key"] = d["SYSTEM_SHORT"].str.upper()
    d["_mrk_key"] = d["MARKER_SHORT"].str.upper()
    canonical_df["_sys_key"] = canonical_df["SYSTEM_SHORT"].str.upper()
    canonical_df["_mrk_key"] = canonical_df["MARKER_SHORT"].str.upper()

    # Drop mixed-case columns from d before merge
    d = d.drop(columns=["SYSTEM_SHORT", "MARKER_SHORT"])

    print(f"Rows before merge: {len(df)}")
    d = d.merge(canonical_df, on=["_sys_key", "_mrk_key"], how="inner")
    d = d.drop(columns=["_sys_key", "_mrk_key"])
    print(f"Rows after merge: {len(d)}")

    if d.empty:
        return []

    #Build profile keys from group columns
    d["PROFILE_KEY"] = [tuple(row) for row in d[group_keys].itertuples(index=False, name=None)]

    #If there are multiple rows with the same profile, system, and marker, pick the representative
    #row: non-null result first, then highest count, then lowest error. Implemented as a sort +
    #drop_duplicates (keep first) rather than groupby().apply() - this avoids a pandas-version-dependent
    #ambiguity in whether the grouping columns are preserved as columns vs. moved into the result index
    #(observed to silently drop PROFILE_KEY under pandas 3.x), and is far faster on large datasets since
    #it's fully vectorized instead of calling a Python function once per group.
    d["_has_result"] = d["RESULT"].notna()
    d["_count"] = (pd.to_numeric(d["COUNT"], errors="coerce").fillna(-1) if "COUNT" in d.columns else -1)
    d["_err"] = (pd.to_numeric(d["RESULT_ERROR"], errors="coerce").fillna(np.inf) if "RESULT_ERROR" in d.columns else np.inf)

    chosen = (
        d.sort_values(["_has_result", "_count", "_err"], ascending=[False, False, True])
        .drop_duplicates(subset=["PROFILE_KEY", "SYSTEM_SHORT", "MARKER_SHORT"], keep="first")
        .reset_index(drop=True)
    )

    profiles_dict: Dict[Tuple, Profile] = {} #initialize + ensure only systems from canonical example
    has_result_error = "RESULT_ERROR" in chosen.columns

    for row in chosen.itertuples(index=False):
        prof_key = row.PROFILE_KEY
        if prof_key not in profiles_dict:
            ctx = {
                "CLIENT":           getattr(row, "CLIENT", ""),
                "MARKER_BSK_CODE":  getattr(row, "MARKER_BSK_CODE", ""),
                "EXPERIMENT_ID":    getattr(row, "EXPERIMENT_ID", ""),
                "AGENT":            getattr(row, "AGENT", ""),
                "AGENT_ID":         getattr(row, "AGENT_ID", ""),
                "AGENT_BSK_CODE":   getattr(row, "AGENT_BSK_CODE", ""),
                "CONCENTRATION":    getattr(row, "CONCENTRATION", ""),
                "UNIT":             getattr(row, "UNIT", "")
            }
            try:
                disp_name = name_template.format(**ctx)
            except (KeyError, ValueError):
                disp_name = str(getattr(row, "AGENT", ""))

            profiles_dict[prof_key] = Profile(key=prof_key, display_name=disp_name, project_display_name=getattr(row, "PROJECT", ""))

        profile = profiles_dict[prof_key]
        pair = (row.SYSTEM_SHORT, row.MARKER_SHORT)

        if pd.notna(row.RESULT):
            profile.values[pair] = float(row.RESULT)

        if has_result_error:
            err_val = getattr(row, "RESULT_ERROR", None)
            if err_val is not None and pd.notna(err_val):
                profile.errors[pair] = float(err_val)

    profiles = list(profiles_dict.values())
    profiles.sort(key=lambda p: (p.project_display_name or "", p.display_name or ""))

    return profiles

def precompute_marker_metadata(pairs: List[Tuple[str,str]]):
    
    """
    Return arrays aligned to pairs: names[], tox_cat[], tox_thr[]
    tox_cat codes: 0=non-toxic, 1=SRB, 2=Visual, 3=PBMC/PI
    """

    names = [f"{s}:{m}" for (s,m) in pairs]
    
    tox_cat = np.zeros(len(pairs), dtype=np.int8)
    tox_thr = np.zeros(len(pairs), dtype=float)

    for i, nm in enumerate(names):
        nm_upper = nm.upper()
        if any(tok in nm_upper for tok in TOX_CONTAINS):
            if "SRB" in nm_upper:
                tox_cat[i] = 1
                tox_thr[i] = SRB_THRESHOLD
            elif "VISUAL" in nm_upper:
                tox_cat[i] = 2
                tox_thr[i] = VISUAL_THRESHOLD
            elif "PBMC CYTOTOXICITY" in nm_upper:
                tox_cat[i] = 3
                tox_thr[i] = PBMC_THRESHOLD
        elif any(nm_upper.endswith(tok) for tok in TOX_ENDSWITH):
            tox_cat[i] = 3
            tox_thr[i]= PBMC_THRESHOLD
    
    return names, tox_cat, tox_thr

def profile_arrays(prof: Profile, pairs: List[Tuple[str, str]]) -> Tuple[np.ndarray, np.ndarray]:

    """
    Vectorized per-profile computation to return value and error arrays aligned to pairs.
    If missing, assign np.nan
    """

    vals = np.array([prof.values.get(p, np.nan) for p in pairs], dtype=float)
    errs = np.array([prof.errors.get(p, np.nan) for p in pairs], dtype=float)

    return vals, errs

def _compute_envelope_model_for_names(names: List[str], *, control_csv: Optional[str] = None, sigma_csv: Optional[str] = None, from_export: bool = True, control_export_csv: Optional[str] = None, assay_ids: Optional[Sequence[int]] = None,
                                      profile_type: str = NAME_SCREENING, confidence: float = 0.95, data_type: str = NAME_SCREENING, csv_sep: str = ",", concentration: float = 0.1, exclude_visual: bool = True) -> EnvelopeModel:
    
    """
    Build EnvelopeModel using EnvelopeService for Sys:Mrk
    """

    model = EnvelopeModel()
    model.set_data_type(data_type)
    model.confidence = confidence
    model.set_system_marker_list(names)

    svc = EnvelopeService()

    if from_export:
        if control_export_csv is None or assay_ids is None:
            raise ValueError("from_export=True requires control_export_csv and assay_ids")
        
        return svc.envelope_service_from_export(model, export_csv=control_export_csv, assay_ids=assay_ids, profile_type=profile_type, confidence=confidence, concentration=concentration, exclude_visual=exclude_visual, random_seed=4, system_marker_order=names)
    
    else:
        if control_csv is None or sigma_csv is None:
            raise ValueError("control_csv and sigma_csv are required when from_export=False")
        
        return svc.service(model, control_csv=control_csv, csv_sep=csv_sep, sigma_csv=sigma_csv)

def _envelope_vector_from_model(names: List[str], env_model: EnvelopeModel, *, use_hit_map: bool=True,
                                default_env: float = DEFAULT_ENVELOPE_VALUE) -> np.ndarray:
    
    """
    Build envelope vector aligned to names from model (hit or sig)
    """

    env_map = env_model.hit_envelope_map if use_hit_map else env_model.significance_envelope_map
    vec = np.empty(len(names), dtype=float)
    for i, n in enumerate(names):
        v = env_map.get(n, None)
        try:
            vf = float(v)
        except (TypeError, ValueError):
            vf = np.nan
        if np.isnan(vf):
            vf = default_env
        vec[i] = vf

    return vec

def compute_hits_and_tox(vals: np.ndarray, env_vec: np.ndarray, tox_cat: np.ndarray, 
                         tox_thr: np.ndarray) -> Tuple[np.ndarray, np.ndarray, int, int]:
    
    """
    Vectorized hit/tox evaluation. 
       - hits: |value| > |envelope| and envelope != 0
       - tox: value < threshold for toxic markers
    """

    valid = (~np.isnan(vals)) & (~np.isnan(env_vec))
    hits = np.zeros_like(valid, dtype=bool)
    hits[valid] = (env_vec[valid] != 0) & (np.abs(vals[valid]) > np.abs(env_vec[valid]))

    #Toxicity: if tox_cat != 0 (non-toxic), compare to threshold
    tox = np.zeros_like(hits)
    mask = (tox_cat != 0) & (~np.isnan(vals))
    if np.any(mask):
        tox[mask] = vals[mask] < tox_thr[mask]
    
    return hits, tox, int(hits.sum()), int(tox.sum())

def write_excel_chunk(output_xlsx: str, profiles: List[Profile], canonical: "OrderedDict[str, List[str]]", profile_type: str, control_csv: Optional[str], sigma_csv: Optional[str], *,
                      from_export: bool = True, control_export_csv: Optional[str] = None, assay_ids: Optional[Sequence[int]] = None, confidence: float = 0.95, data_type: str = NAME_SCREENING, csv_sep: str = ",",
                      concentration: float = 0.1, exclude_visual: bool = True, sig_table_csv: Optional[str] = None, sig_profile_type_id: Optional[int] = None):
    
    '''
    Write single Excel workbook for chunk of profiles - stay within Excel application's row/column limits
    Use helper_envelope to support envelope calculations
    '''

    wb = Workbook()
    ws_data = wb.create_sheet(SHEET_DATA)
    ws_error = wb.create_sheet(SHEET_ERROR)
    ws_tox = wb.create_sheet(SHEET_CYTOX)
    ws_env = wb.create_sheet(SHEET_ENVELOPE)
    ws_hits = wb.create_sheet(SHEET_HITS)

    blue_font = Font(color="0000FF")
    red_font = Font(color="FF0000")

    pairs = build_linear_pairs(canonical)
    names, tox_cat, tox_thr = precompute_marker_metadata(pairs)

    #Get envelope model
    env_model = _compute_envelope_model_for_names(names, control_csv=control_csv, sigma_csv=sigma_csv, from_export=from_export, control_export_csv=control_export_csv, assay_ids=assay_ids, profile_type=profile_type, confidence=confidence, data_type=data_type, csv_sep=csv_sep, concentration=concentration, exclude_visual=exclude_visual,)
    env_vec = _envelope_vector_from_model(names, env_model, use_hit_map=True, default_env=DEFAULT_ENVELOPE_VALUE)

    #Headers
    hdr = ["Profile"] + names
    ws_data.append(hdr)
    ws_error.append(hdr)
    ws_hits.append(["Profile", SHEET_HITS] + names)

    #Cytotox header only contains toxic markers present
    tox_indices = np.where(tox_cat != 0)[0]
    hdr_tox = ["Profile", SHEET_CYTOX] + [names[i] for i in tox_indices]
    ws_tox.append(hdr_tox)

    #Calculate and collect data
    processed_profiles = []

    for prof in profiles:
        vals, errs = profile_arrays(prof, pairs)
        hits, tox, hit_count, tox_count = compute_hits_and_tox(vals, env_vec, tox_cat, tox_thr)

        #Remove ".0" on concentrations in the "Profile" first column of the "Profile Data" sheet to match Viewer
        clean_name = re.sub(r'\.0+(?=\s|$)', '', prof.display_name)
        try:
            conc_starter = clean_name.split(", ")[2]
            conc_value = float(conc_starter.split(" ")[0])
        except Exception:
            conc_value = np.nan

        #Identify agent name with fallback of removing agent from standard format
        agent_name = getattr(prof, 'agent', None)
        if not agent_name:
            agent_name = clean_name.rsplit(',', 1)[0]
            print(agent_name)
        
        processed_profiles.append({
            "original_prof": prof,
            "clean_name": clean_name,
            "agent_name": agent_name,
            "conc_val": conc_value,
            "vals": vals,
            "errs": errs,
            "hits": hits,
            "tox": tox,
            "hit_count": hit_count,
            "tox_count": tox_count,
        })

    agent_order = []
    agent_groups = defaultdict(list)

    #Group by agent and sort by descending number of hits
    for data in processed_profiles:
        agent = data["agent_name"]
        if agent not in agent_order:
            agent_order.append(agent)
        agent_groups[agent].append(data)
    
    sorted_profiles = []
    for agent in agent_order:
        agent_groups[agent].sort(key=lambda x: x["conc_val"], reverse=True)
        sorted_profiles.extend(agent_groups[agent])

    #Write sorted rows to Excel sheets
    for data in sorted_profiles:
        clean_name = data["clean_name"]
        vals = data["vals"]
        errs = data["errs"]
        hits = data["hits"]
        tox = data["tox"]
        hit_count = data["hit_count"]
        tox_count = data["tox_count"]

        #Stylized cells in Profile Data Sheet
        row_cells = []
        name_cell = WriteOnlyCell(ws_data, value=clean_name)
        if tox_count > 0:
            name_cell.font = red_font #Output is red if toxic
        elif hit_count > 0:
            name_cell.font = blue_font #Output is blue if hit
        row_cells.append(name_cell)

        vnums = np.nan_to_num(vals, nan=0.0)
        for j in range(len(pairs)):
            cell = WriteOnlyCell(ws_data, value=(None if np.isnan(vals[j]) else round(vnums[j], 8)))
            if not np.isnan(vals[j]):
                if tox[j]:
                    cell.font = red_font
                elif hits[j]:
                    cell.font = blue_font
            row_cells.append(cell)
        ws_data.append(row_cells)

        #Error sheet
        err_list = [clean_name] + [None if np.isnan(e) else float(e) for e in errs]
        ws_error.append(err_list)

        #Biomarker hits sheet
        ws_hits.append([clean_name, hit_count] + hits.astype(int).tolist())

        #Cytotoxicity sheet
        tox_row = [clean_name, tox_count] + tox[tox_indices].astype(int).tolist()
        ws_tox.append(tox_row)

    #Envelope sheet
    # Significance Envelope, computed fresh via percentile directly from ScreenControls.csv,
    # confirmed to exactly reproduce the real Viewer's reference values (verified 2026-09-21).
    # (Path 0 table-lookup and Path 2 export-simulation are still available as fallbacks below.)
    if sig_table_csv is not None and sig_profile_type_id is not None and control_csv is None:
        helper_envelope.run_helper_envelope_from_table(table_csv=sig_table_csv, profile_type_id=sig_profile_type_id, readout_names_in_order=names, workbook_or_path=wb, confidence=confidence, data_type=data_type, envelope_type_label="Sig", save_path=None, envelope_source="significance")
    elif control_csv is not None:
        helper_envelope.run_helper_envelope(control_csv=control_csv, sigma_csv=sigma_csv, readout_names_in_order=names, workbook_or_path=wb, confidence=confidence, data_type=data_type, csv_sep=csv_sep, envelope_type_label="Sig", save_path=None, envelope_source="significance")
    elif from_export and not control_export_csv.empty and assay_ids is not None:
        helper_envelope.run_helper_envelope_from_export(control_export_csv=control_export_csv, assay_ids=assay_ids, readout_names_in_order=names, workbook_or_path=wb, profile_type=profile_type, confidence=confidence, data_type=data_type, envelope_type_label="Sig", save_path=None, envelope_source="hit", concentration=concentration, exclude_visual=exclude_visual)
        
    wb.remove(wb["Sheet"])

    wb.save(output_xlsx)

    return(output_xlsx)


def run_helper_table_creator(
        oracle_df, output_xlsx, profile_type="", group_by="AGENT, AGENT_BSK_CODE, CONCENTRATION, UNIT", canonical_csv=DATA_DIR / "sys_marker_header.csv", system_map_csv=DATA_DIR / "viewer_system_names.csv", marker_map_csv=DATA_DIR / "viewer_marker_names.csv",
        control_csv = CTRL_DIR / "ScreenControls.csv", sigma_csv = CTRL_DIR / "ScreenControls_sigma.csv", from_export: bool = False, assay_ids_csv= CTRL_DIR / "envelope_assay_list_20260520.csv",
        concentration: float = 0.1, exclude_visual: bool = True,
        sig_table_csv = None, sig_profile_type_id: int = 5,):
    
    """
    Execute the entire helper function to transform raw data from database query
    to the format that matches output from BioMAP Viewer, then write Excel and/or CSV outputs.
    """

    from helper_data_loader import _dmso_snapshot_path

    dmso_today = _dmso_snapshot_path()
    if dmso_today.exists():
        control_export_csv = pd.read_parquet(dmso_today)
    else:
        control_export_csv = pd.read_csv(CTRL_DIR / "dmso_ctrl_view_nonprod_utf8_20260312_Cleaned.csv")

    confidence = 0.95
    excel_max_rows = 900000
    excel_max_columns = 15000

    output_files = []

    assay_id_df = pd.read_csv(assay_ids_csv, encoding="utf-8")
    assay_ids = assay_id_df["ASSAY_ID"].to_list()

    canonical = extract_system_markers(canonical_csv)
    sys_map, mrk_map = load_mappings(system_map_csv, marker_map_csv)

    #Build profiles then build table
    group_keys = [s.strip() for s in group_by.split(',') if s.strip()]

    profiles = build_profiles(df=oracle_df, canonical=canonical, system_map=sys_map, marker_map=mrk_map, group_keys=group_keys, name_template="{AGENT}, {AGENT_BSK_CODE}, {CONCENTRATION} {UNIT}")

    pairs = build_linear_pairs(canonical)
    readouts_order = [f"{s}:{m}" for (s,m) in pairs]

    output_files: List[str] = []
    
    #Chunk Excel files for export
    total_rows = len(profiles)
    total_cols = len(pairs) #Make sure number of columns doesn't exceed Excel limits
    if total_cols > excel_max_columns:
        raise ValueError(f"Total readout columns ({total_cols}) exceeds Excel's limit. Please use csv.")
    
    pt = profile_type.capitalize() if profile_type else NAME_SCREENING
    
    if total_rows > excel_max_rows:
        n_parts = ceil(total_rows / excel_max_rows)
        for part in range(n_parts):
            start         = part * excel_max_rows
            end           = min((part+1) * excel_max_rows, total_rows)
            prof_slice    = profiles[start:end]
            base, ext     = os.path.splitext(output_xlsx)
            part_path     = f"{base}_part{part+1:03d}{ext}"
            out           = write_excel_chunk(part_path, prof_slice, canonical, pt, control_csv, sigma_csv, from_export=from_export, control_export_csv=control_export_csv, assay_ids=assay_ids, confidence=confidence, data_type=profile_type.capitalize(), csv_sep="\t", concentration=concentration, exclude_visual=exclude_visual, sig_table_csv=sig_table_csv, sig_profile_type_id=sig_profile_type_id)
            output_files.append(out)
    else:
        out = write_excel_chunk(output_xlsx, profiles, canonical, pt, control_csv, sigma_csv, from_export=from_export, control_export_csv=control_export_csv, assay_ids=assay_ids, confidence=confidence, data_type=profile_type.capitalize(), csv_sep="\t", concentration=concentration, exclude_visual=exclude_visual, sig_table_csv=sig_table_csv, sig_profile_type_id=sig_profile_type_id)
        output_files.append(out)
    
    return output_files