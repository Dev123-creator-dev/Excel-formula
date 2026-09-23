#!/usr/bin/env python

import pandas as pd
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from glob import glob
import numpy as np

import helper_orcl_db
import helper_general
from helper_general import DIVERSITY_PLUS

"""
Helper function for daily loading and pre-computation.
At 3AM, cron job calls `refresh_daily_snapshot()`:
    - Pulls from BioMAP database and writes raw snapshot parquet.
    - Immediately computes every aggregate for the UI and writes as separate small parquet files.

When MEGA starts up, tabs call the load_* functions that only return small pre-aggregated frames:
    data/snapshots/
        snapshot_YYYY_MM_DD.parquet:            rows (large file)
        agg_agent_summary_YYYY_MM_DD.parquet    one row per agent
        agg_readout_grid_YYYY_MM_DD.parquet     one row per agent x sys x marker
        agg_sys_marker_YYYY_MM_DD.parquet       one row per sys x marker
        agg_full_per_system_YYYY_MM_DD.parquet  
        agg_marker_agent_YYYY_MM_DD.parqut
"""

logger = logging.getLogger(__name__)

#######################################################
###                 NORMALIZATION                   ###
#######################################################

def _normalize_keys(df: pd.DataFrame) -> pd.DataFrame:

    for col in ["SYSTEM", "MARKER", "AGENT"]:
        if col in df.columns:
            df[col] = (df[col].astype(str).str.strip())

    return df

#######################################################
###                 CONFIGURATION                   ###
#######################################################

SNAPSHOT_DIR = Path("data/snapshots")
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

BASE_DIR = Path(__file__).resolve().parent
FALLBACK_CSV    = BASE_DIR / "data" / "snapshots" / "snapshot_2026_04_14.parquet"#"DIVPLUS_FILTERED_20260204_export.csv"
FALLBACK_DMSO   = BASE_DIR / "data" / "controls" / "dmso_ctrl_view_nonprod_utf8_20260312_Cleaned.csv"
FALLBACK_ENC    = "utf-8"
KEEP_DAYS       = 7
DENOM           = 148

PANEL_CSV       = BASE_DIR / "data" / "sys_marker_header.csv"

PANEL_PAIRS     = pd.DataFrame(
    [{"SYSTEM": sys, "MARKER": mrk} for sys, markers in DIVERSITY_PLUS.items() for mrk in markers]
)
PANEL_PAIRS["SYSTEM"] = PANEL_PAIRS["SYSTEM"].str.strip().str.upper()
PANEL_PAIRS["MARKER"] = PANEL_PAIRS["MARKER"].str.strip().str.upper()
PANEL_PAIRS	= _normalize_keys(PANEL_PAIRS)

def load_panel() -> pd.DataFrame:

    """
    Load autoritative System:Marker penl
    Return dataframe with columns System and Marker
    """

    if not PANEL_CSV.exists():
        raise FileNotFoundError(f"Panel file not found: {PANEL_CSV}")
    
    panel_file = pd.read_csv(PANEL_CSV)
    panel = (panel_file.rename(columns={"SYSTEM_SHORT": "SYSTEM", "MARKER_SHORT": "MARKER",})[["SYSTEM", "MARKER"]].drop_duplicates().reset_index(drop=True))
    logger.info("Loaded panel: %d rows from %s", len(panel), PANEL_CSV)

    return panel

#######################################################
###               FILENAME HELPERS                  ###
#######################################################

def _dated(stem: str, d: Optional[date] = None) -> Path:
    d = d or date.today()
    return SNAPSHOT_DIR / f"{stem}_{d.strftime('%Y_%m_%d')}.parquet"

def _snapshot_path(d: Optional[date] = None) -> Path:
    return _dated("snapshot", d)

def _dmso_snapshot_path(d: Optional[date] = None) -> Path:
    return _dated("snapshot_dmso", d)

#######################################################
###              BIOMAP DATABASE PULL               ###
#######################################################

def _pull_from_db() -> pd.DataFrame:

    try:
        df = helper_orcl_db.query_trusted_filtered_combined()
    except Exception as e:
        logger.error("_pull_from_db: Database retrieval failed", exc_info=True)

    try:
        dmso_df = helper_orcl_db.query_dmso_controls()
    except Exception as e:
        logger.error("_pull_from_db: DMSO control data retrieval failed")

    if (df is None or df.empty) and FALLBACK_CSV.exists():
        logger.error("_pull_from_db: using fallback CSV %s", FALLBACK_CSV)
        #df =  pd.read_csv(FALLBACK_CSV, encoding=FALLBACK_ENC)
        df = pd.read_parquet(FALLBACK_CSV)

    if df is None or df.empty:
        raise RuntimeError(f"No database query available and no fallback CSV found at {FALLBACK_CSV}")
    
    return _normalize_keys(df), _normalize_keys(dmso_df)
    
#######################################################
###                  AGGREGATION                    ###
#######################################################

def _compute_sys_marker_validity(panel: pd.DataFrame) -> pd.DataFrame:

    """
    Defines which Sys:Mrk combinations are relevant. Pair is valid if it appears at least once in raw data.
    """

    valid = panel[["SYSTEM", "MARKER"]].drop_duplicates().copy()
    valid["IS_VALID"] = True

    return valid

def _compute_readout_grid(df_og: pd.DataFrame,) -> pd.DataFrame:

    """
    Ensure one row per Agent x Sys x Mrk for valid pairs only.
    """

    # Restrict df to PANEL_PAIRS
    df = df_og.merge(PANEL_PAIRS, on=["SYSTEM", "MARKER"], how="inner")

    # All agents
    agents = df[["AGENT"]].drop_duplicates()

    # Full expected grid
    full_grid = agents.merge(PANEL_PAIRS, how="cross")

    # Observed presence
    present = (df.drop_duplicates(["AGENT", "SYSTEM", "MARKER"])
               .assign(Status="Present"))
    
    # Merge and mark missing
    merged = full_grid.merge(
        present,
        on=["AGENT", "SYSTEM", "MARKER"],
        how="left"
    )

    merged["Status"] = merged["Status"].fillna("Missing")

    return merged

def _compute_multi_agent_status(readout: pd.DataFrame) -> pd.DataFrame:

    """
    Aggregate agent-level presence into complete, partial, and missing
    Complete    =   All agents have Sys:Mrk readouts
    Partial     =   Some agents have Sys:Mrk readouts
    Missing     =   Agent has no readouts
    """

    all_agents = readout["AGENT"].nunique()

    agg = (readout.groupby(["SYSTEM", "MARKER"]).agg(
        n_agents=("AGENT", "nunique"),
        n_present=("Status", lambda s: (s == "Present").sum()),
        ).reset_index())
    
    conditions = [
        agg["n_present"] == 0,
        agg["n_present"] == all_agents
    ]
    choices = ["Missing", "Complete"]
    agg["Status"] = np.select(conditions, choices, default="Partial")
    agg["n_agents"] = all_agents

    return agg.sort_values(["SYSTEM", "MARKER"]).reset_index(drop=True)

def _compute_agent_summary(readout: pd.DataFrame) -> pd.DataFrame:

    """
    Per-agent summary with ObservedReadouts, MissingReadouts, PctComplete, and Status.
    """

    denom = len(PANEL_PAIRS)
    print("LEN PANEL PAIRS IS: ", denom)

    present_counts = (
        readout[readout["Status"] == "Present"]
        .drop_duplicates(["AGENT", "SYSTEM", "MARKER"])
        .groupby("AGENT")
        .size()
        .rename("ObservedReadouts")
        )

    counts = (readout[["AGENT"]]
              .drop_duplicates()
              .set_index("AGENT")
              .join(present_counts, how="left")
              .fillna(0)
              .astype({"ObservedReadouts": int})
              .reset_index())

    counts["MissingReadouts"]   = denom - counts["ObservedReadouts"]
    counts["PctComplete"]       = (100 * counts["ObservedReadouts"] / denom).round(1)

    counts["Status"] = np.where(
        counts["ObservedReadouts"] == denom, "Complete",
        np.where(counts["ObservedReadouts"] == 0, "Missing", "Partial")
    )

    return counts

def _compute_full_per_system(df: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:

    """
    Computes system-level full profile coverage.
    Full profile defined as observations for all expected markers defined in the system panel CSV.
    """

    # Expected marker count per system
    expected_per_system = (panel.groupby("SYSTEM")["MARKER"].nunique().rename("ExpectedMarkers").reset_index())

    # Observed markers per agent per system
    observed_per_agent_system = (
        df[["AGENT", "SYSTEM", "MARKER"]]
        .drop_duplicates()
        .merge(panel, on=["SYSTEM", "MARKER"], how="inner")
        .groupby(["AGENT", "SYSTEM"])["MARKER"]
        .nunique()
        .rename("ObservedMarkers")
        .reset_index()
    )

    # Compare observed versus expected to give full profile insights
    agent_system = (observed_per_agent_system.merge(expected_per_system, on="SYSTEM", how="left"))
    agent_system["FullForSystem"] = (agent_system["ObservedMarkers"] >= agent_system["ExpectedMarkers"])

    #System-level aggregation
    agents_tested = (df.groupby("SYSTEM")["AGENT"].nunique().rename("AgentsTested").reset_index())

    full_per_system = (agent_system
                       .groupby("SYSTEM", as_index=False)["FullForSystem"]
                       .sum()
                       .rename(columns={"FullForSystem": "AgentsWithFullProfile"})
                       .merge(agents_tested, on="SYSTEM", how="left")
                       .assign(
                           PctFull = lambda d: (100 * d["AgentsWithFullProfile"] / d["AgentsTested"].clip(lower=1)).round(1)
                       ).sort_values("PctFull", ascending=True)
                       .reset_index(drop=True))
    
    return full_per_system

def _compute_missing_pairs(readout: pd.DataFrame) -> pd.DataFrame:

    """
    Returns which System:Marker pairs are missing per agent
    """

    return readout[readout["Status"] == "Missing"].sort_values(["AGENT", "SYSTEM", "MARKER"])

def _compute_all_aggregates(df: pd.DataFrame, panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    
    sys_marker_valid    =   _compute_sys_marker_validity(panel)
    readout_grid        =   _compute_readout_grid(df)
    multi_agent         =   _compute_multi_agent_status(readout_grid)
    agent_summary       =   _compute_agent_summary(readout_grid)
    full_per_system     =   _compute_full_per_system(df, panel)
    missing_pairs       =   _compute_missing_pairs(readout_grid)

    print("AGENT SUMMARY:\n", agent_summary)
    print("AGENT SUMMARY STATUS VALUES: ", agent_summary["Status"].unique())

    # Sys_marker counts: observations per sys x mrk
    panel_pairs = panel[["SYSTEM", "MARKER"]].drop_duplicates()
    raw_counts = (df.merge(panel_pairs, on=["SYSTEM", "MARKER"], how="inner").groupby(["SYSTEM", "MARKER"]).size().reset_index(name="Count"))
    sys_marker_counts = (panel_pairs.merge(raw_counts, on=["SYSTEM", "MARKER"], how="left").fillna({"Count": 0}).astype({"Count": int}))

    # Marker_agent_counts: distinct agents per marker
    marker_agent = (df.merge(panel_pairs[["MARKER"]].drop_duplicates(), on="MARKER", how="inner")
                    .groupby("MARKER")["AGENT"]
                    .nunique()
                    .rename("AgentCount")
                    .reset_index()
                    .sort_values("AgentCount", ascending=True))

    # Dim_counts: value counts for System, Marker, Agent
    dim_rows = []
    for col in ["SYSTEM", "MARKER", "AGENT"]:
        counts = df[col].value_counts().reset_index()
        counts.columns = ["Value", "Count"]
        counts["Dimension"] = col
        dim_rows.append(counts)
    dim_counts_df = pd.concat(dim_rows, ignore_index=True)

    return {
        "agg_agent_summary":    agent_summary,
        "agg_readout_grid":     readout_grid,
        "agg_sys_marker":       sys_marker_valid,
        "agg_full_per_system":  full_per_system,
        "agg_marker_agent":     marker_agent,
        "agg_dim_counts":       dim_counts_df,
        "agg_multi_agent":      multi_agent,
        "agg_sys_mrk_count":    sys_marker_counts,
        "agg_missing_pairs":    missing_pairs,
    }

#######################################################
###                 WRITE / PRUNE                   ###
#######################################################

def _write_parquet(df: pd.DataFrame, path: Path) -> None:

    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    logger.info("Written: %s (%d rows, %d cols)", path.name, len(df), df.shape[1])

def _prune_old_files() -> None:
    cutoff = date.today().toordinal() - KEEP_DAYS
    for p in SNAPSHOT_DIR.glob("*.parquet"):
        try:
            parts       =   p.stem.rsplit("_", 3)
            file_date   =   date(int(parts[-3]), int(parts[-2]), int(parts[-1]))
            if file_date.toordinal() < cutoff:
                p.unlink()
                logger.info("Pruned: %s", p.name)
        except (ValueError, IndexError):
            pass

#######################################################
###                DAILY SNAPSHOT                   ###
#######################################################

def refresh_daily_snapshot(denom: int = DENOM) -> None:

    """
    Pull BioMAP data from database, write raw snapshot, then compute and write all aggregates.
    """

    logger.info("refresh_daily_snapshot: starting at %s", datetime.now())

    df      = None
    source  = None

    try:
        df, dmso_df      =   _pull_from_db()
        source           =   "database"
    except Exception as e:
        logger.warning("Database unavailable: %s", e)
        print("Database unavailable: %s", e)
        if FALLBACK_CSV.exists():
            logger.warning("Using fallback CSV: %s", FALLBACK_CSV)
            df = pd.read_csv(FALLBACK_CSV, encoding=FALLBACK_ENC)
            dmso_df = pd.read_csv(FALLBACK_DMSO, encoding=FALLBACK_ENC)
            source = "fallback_csv"

    if df is None or df.empty:
        raise RuntimeError(f"No data available from database and no fallback CSV found at {FALLBACK_CSV}")
    
    logger.info("refresh_daily_snapshot: loaded %d rows from %s", len(df), source)
    
    _write_parquet(df, _snapshot_path())
    _write_parquet(dmso_df, _dmso_snapshot_path())

    og_df = df

    panel = load_panel()
    df = helper_general.diversity_plus_filter(df)
    df = _normalize_keys(df)
    panel = _normalize_keys(panel)

    df_sys = df["SYSTEM"].unique().tolist()
    df_mrk = df["MARKER"].unique().tolist()
    pan_sys = panel["SYSTEM"].unique().tolist()
    pan_mrk = panel["MARKER"].unique().tolist()
    sys_ovr = np.intersect1d(df_sys, pan_sys)
    mrk_ovr = np.intersect1d(df_mrk, pan_mrk)
    #og_sys = og_df["SYSTEM"].unique().tolist()
    #og_mrk = og_df["MARKER"].unique().tolist()
    #og_sovr = np.intersect1d(og_sys, pan_sys)
    #og_movr = np.intersect1d(og_mrk, pan_mrk)

    print("df SYSTEM values: ", df_sys, len(df_sys))
    print("panel SYSTEM values: ", pan_sys, len(pan_sys))
    print("df MARKERS values: ", df_mrk, len(df_mrk))
    print("panel MARKER values: ", pan_mrk, len(pan_mrk))
    print("overlap between systems: ", sys_ovr, len(sys_ovr))
    print("overlap between markers: ", mrk_ovr, len(mrk_ovr))
    #print("ORIGINAL before filter sys: ", og_sys, len(og_sys))
    #print("ORIGINAL before filter mrk: ", og_mrk, len(og_mrk))
    #print("OG overlap sys: ", og_sovr, len(og_sovr))
    #print("OG overlap mrk: ", og_movr, len(og_movr))

    aggs    =   _compute_all_aggregates(df, panel)
    for stem, frame in aggs.items():
        _write_parquet(frame, _dated(stem))
    
    _prune_old_files()
    logger.info("refresh_daily_snapshot: complete")

def _load_agg(stem: str, allow_fallback: bool=True) -> pd.DataFrame:

    """
    Load today's pre-computed aggregate.
    If missing, trigger full refresh then retry.
    """

    today = _dated(stem)
    if today.exists():
        return pd.read_parquet(today)
    
    # If today's files are not found, try most resent existing file for this stem
    candidates = sorted(SNAPSHOT_DIR.glob(f"{stem}_*.parquet"), reverse=True)
    if candidates:
        logger.warning("_load_agg: today's %s missing, using %s", stem, candidates[0].name)
        return pd.read_parquet(candidates[0])
    
    if allow_fallback:
        # No aggregate at all: run full refresh to generate them
        logger.warning("_load_agg: no %s found, triggering full refresh", stem)
        refresh_daily_snapshot()
        if today.exists():
            return pd.read_parquet(today)
        if FALLBACK_CSV.exists():
            return pd.read_csv(FALLBACK_CSV, encoding=FALLBACK_ENC)
    
    raise FileNotFoundError(f"Aggregate '{stem}' not found and could not be generated. "
                            "Run refresh_daily_snapshot() manually or check database connection.")

#######################################################
###               PER-TAB LOADERS                   ###
#######################################################

def load_agent_summary() -> pd.DataFrame:
    return _load_agg("agg_agent_summary")

def load_readout_grid() -> pd.DataFrame:
    return _load_agg("agg_readout_grid")

def load_sys_marker_counts() -> pd.DataFrame:
    return _load_agg("agg_sys_marker")

def load_full_per_system() -> pd.DataFrame:
    return _load_agg("agg_full_per_system")

def load_marker_agent_counts() -> pd.DataFrame:
    return _load_agg("agg_marker_agent")

def load_dim_counts() -> pd.DataFrame:
    return _load_agg("agg_dim_counts")

def load_multi_grid() -> pd.DataFrame:
    return _load_agg("agg_multi_agent")

def load_sys_mrk_counts_real() -> pd.DataFrame:
    return _load_agg("agg_sys_mrk_count")

def load_missing_pairs() -> pd.DataFrame:
    return _load_agg("agg_missing_pairs")

def load_data(allow_fallback: bool = True) -> pd.DataFrame:

    """
    Load today's raw snapshot. Only needed for Exporter tab.
    """

    today = _snapshot_path()
    if today.exists():
        return pd.read_parquet(today)
    
    # If today's files are not found, try most resent existing file for this stem
    candidates = sorted(SNAPSHOT_DIR.glob("snapshot_*.parquet"), reverse=True)
    if candidates:
        logger.warning("load_data: using %s",  candidates[0].name)
        return pd.read_parquet(candidates[0])
    
    if allow_fallback:
        # No aggregate at all: run full refresh to generate them
        logger.warning("load_data: triggering full refresh")
        refresh_daily_snapshot()
        if today.exists():
            return pd.read_parquet(today)
        if FALLBACK_CSV.exists():
            return pd.read_csv(FALLBACK_CSV, encoding=FALLBACK_ENC)
    
    raise FileNotFoundError("No data available. Run refresh_daily_snapshot()")

def snapshot_info() -> dict:

    """
    Metadata about the current snapshot for the sidebar.
    """

    today = _snapshot_path()
    candidates = sorted(SNAPSHOT_DIR.glob("snapshot_*.parquet"), reverse=True)

    if today.exists():
        mtime = datetime.fromtimestamp(today.stat().st_mtime)
        return {"status": "current", "last_updated": mtime.strftime("%Y-%m-%d %H:%M"), "is_today": True}
    elif candidates:
        mtime = datetime.fromtimestamp(candidates[0].stat().st_mtime)
        return {"status": "stale", "last_updated": mtime.strftime("%Y-%m-%d %H:%M"), "is_today": False}
    return {"status": "none", "last_updated": "never", "is_today": False}


if __name__ == "__main__":
    refresh_daily_snapshot()
