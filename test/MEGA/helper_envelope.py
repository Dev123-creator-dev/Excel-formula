from __future__ import annotations
import numpy as np
import pandas as pd
import math
import random
import unicodedata
import helper_general
from pathlib import Path
from scipy.stats import norm as _norm
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Iterable, Union, Sequence, Optional


# ---------------------------------------------------------------------------
# Constants — copied verbatim from UpdateControlDataService.java fields
# ---------------------------------------------------------------------------
ENVELOPE_NONE           = "No Envelope"
ENVELOPE_HITS           = "Hits Envelope"
ENVELOPE_SIGNIFICANCE   = "Significance Envelope"

NAME_PROFILE            = "Profile"
NAME_SCREENING          = "Screening"
NAME_TRUSTED            = "Trusted"

DEFAULT_CONFIDENCE      = 0.95

MIN_WELL_NO             = 7     # Java: private int MIN_WELL_NO = 7
SCREEN_WELL_NO          = 1     # Java: private int SCREEN_WELL_NO = 1
PROFILE_WELL_NO         = 3     # Java: private int PROFILE_WELL_NO = 3
DMSO_WELL_NO            = 8     # Java: private int DMSO_WELL_NO = 8
SCREEN_MAX_NUMRATIO     = SCREEN_WELL_NO + DMSO_WELL_NO   # = 9
PROFILE_MAX_NUMRATIO    = 150   # Java: private int PROFILE_MAX_NUMRATIO = 150
MAX_SCREENPROFILE_NUM   = 3000  # Java: private int MAX_SCREENPROFILE_NUM = 3000
# Screening control matrix: MAX_SCREENPROFILE_NUM rows
# Profile  control matrix: 3 * MAX_SCREENPROFILE_NUM rows  (= 9000)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CTRL_DIR = DATA_DIR / "controls"

def _normalize_sysmrk(name: object) -> str:
    if name is None:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).strip()
    for k in ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212"]:
        s = s.replace(k, "-")
    for k in ["\u2215", "\u2044", "\uFF0F"]:
        s = s.replace(k, "/")
    return s


def load_mappings(
    system_map_csv=DATA_DIR / "viewer_system_names.csv",
    marker_map_csv=DATA_DIR / "viewer_marker_names.csv",
):
    sys_map, mrk_map = {}, {}
    if system_map_csv:
        sm = pd.read_csv(system_map_csv, dtype="str", encoding="utf-8")
        sm["long_system_name"] = sm["long_system_name"].map(_normalize_sysmrk)
        sm["display_name"]     = sm["display_name"].map(_normalize_sysmrk)
        sys_map = dict(zip(sm["long_system_name"].astype(str), sm["display_name"].astype(str)))
    if marker_map_csv:
        mm = pd.read_csv(marker_map_csv, dtype="str", encoding="utf-8")
        mm["long_marker_name"]  = mm["long_marker_name"].map(_normalize_sysmrk)
        mm["short_marker_name"] = mm["short_marker_name"].map(_normalize_sysmrk)
        mrk_map = dict(zip(mm["long_marker_name"].astype(str), mm["short_marker_name"].astype(str)))
    return sys_map, mrk_map


SYS_MAP, MRK_MAP = load_mappings()


def sys_converter(name: str) -> str:
    norm = _normalize_sysmrk(name)
    return SYS_MAP.get(norm, norm)


def mrk_converter(name: str) -> str:
    return _normalize_sysmrk(name)


# ---------------------------------------------------------------------------
# EnvelopeModel
# ---------------------------------------------------------------------------

@dataclass
class EnvelopeModel:
    data_type: str      = NAME_SCREENING
    envelope_type: str  = ENVELOPE_NONE
    confidence: float   = DEFAULT_CONFIDENCE

    system_marker_list: List[str]               = field(default_factory=list)
    hit_envelope_map: Dict[str, float]          = field(default_factory=dict)
    significance_envelope_map: Dict[str, float] = field(default_factory=dict)
    system_marker_map: Dict[str, List[str]]     = field(default_factory=dict)

    def is_type_hits(self)         -> bool: return self.envelope_type == ENVELOPE_HITS
    def is_type_significance(self) -> bool: return self.envelope_type == ENVELOPE_SIGNIFICANCE
    def is_type_none(self)         -> bool: return self.envelope_type == ENVELOPE_NONE

    def envelope_as_array(self, envelope_type: str, system_markers: List[str]) -> List[float]:
        m = self.hit_envelope_map if envelope_type == ENVELOPE_HITS else self.significance_envelope_map
        return [float(m[sm]) if sm in m else float("nan") for sm in system_markers]

    def set_data_type(self, data_type: str) -> None:
        self.data_type = (NAME_PROFILE   if data_type == NAME_PROFILE
                    else  NAME_SCREENING if data_type == NAME_SCREENING
                    else  NAME_TRUSTED)

    def set_system_marker_list(self, markers: List[str]) -> None:
        self.system_marker_list = list(markers)

    def reset_data(self) -> None:
        self.hit_envelope_map.clear()
        self.significance_envelope_map.clear()
        self.system_marker_map.clear()

    def envelope_data_type_name(self) -> str:
        return self.data_type


def stddev(values: Iterable[float]) -> float:
    # Java BSKStatistics.stddev uses sample std (ddof=1)
    arr = np.asarray(list(values), dtype=float)
    return float(arr.std(ddof=1)) if arr.size >= 2 else 0.0


def _java_percentile_sorted(sorted_arr: np.ndarray, p: float) -> float:
    """
    Direct translation of BSKStatistics.percentile(double[], double).

    Java formula (1-based indexing):
        n_p    = p * (n - 1) + 1
        i      = floor(n_p)
        d      = n_p - i
        result = arr[i-1] + d * (arr[i] - arr[i-1])
    Edge cases: clamp to first element if i<=1, last element if i>=n.

    NOTE: numpy's np.percentile uses a different convention — do NOT use it.
    """
    n = sorted_arr.size
    if n == 0:
        return float("nan")
    n_p = float(p) * (n - 1) + 1.0
    i   = int(math.floor(n_p))
    d   = n_p - i
    if i <= 1: return float(sorted_arr[0])
    if i >= n: return float(sorted_arr[-1])
    return float(sorted_arr[i - 1] + d * (sorted_arr[i] - sorted_arr[i - 1]))


def java_percentile(values: Iterable[float], p: float) -> float:
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]   # drop NaN/Inf before sorting, matching Java behaviour
    if arr.size == 0:
        return float("nan")
    arr.sort()
    return _java_percentile_sorted(arr, p)

def _fill_by_norm_dist(
    source_values: List[float],
    mean_val: float,
    stddev_val: float,
    max_size: int,
    rng: random.Random,
) -> np.ndarray:
    """
    Java fillByNormDist:
        Permutation p = new Permutation(od_list.size());
        int[] indexes = p.next();                          // random shuffle
        double[] filledArray = new double[maxWellNum];
        for (int i = 0; i < filledArray.length; i++) {
            if (i < od_list.size())
                filledArray[i] = od_list.get(indexes[i]); // real value (shuffled)
            else
                filledArray[i] = rand.nextGaussian() * stddev + mean; // synthetic
        }

    *** CRITICAL — mean_val is DIFFERENT depending on where this is called: ***

    CALL SITE 1 — Phase 1 (makeRatioList, per-plate, filling raw OD wells):
        Java: mean = BSKStatistics.mean(od_list)   <-- per-plate mean of OD values
        Python: pass plate_mean = float(np.mean(od_list))

    CALL SITE 2 — Phase 2 (service() loop, per-SR, filling ratio matrix):
        Java: double mean = 0;                     <-- HARDCODED 0
        Python: pass mean_val=0.0
        Rationale: log-ratios are assumed symmetric around 0, so N(0, sigma)
        is the correct null distribution.  Using the ratio-list mean here
        would be wrong and was a bug in earlier Python versions.
    """

    arr = np.asarray(source_values, dtype=float)
    idx = list(range(len(source_values)))
    rng.shuffle(idx)   # equivalent to Java's Permutation(od_list.size()).next()
    out = np.empty(max_size, dtype=float)
    for i in range(max_size):
        if i < len(source_values):
            out[i] = arr[idx[i]]
        else:
            out[i] = rng.gauss(mean_val, stddev_val) if stddev_val > 0 else mean_val
    return out

def _make_ratio(
    filled: np.ndarray,
    numer_count: int,
    denom_count: int,
    max_ratios: int,
    rng: random.Random,
) -> List[float]:
    """
    Java makeRatio:
        Permutation p = new Permutation(filledArray.length);
        for (int i = 0; i < maxNoRatio; i++) {
            int[] indexes = p.next();          // fresh full permutation each iteration
            numer = filledArray[indexes[0..numerCount-1]]
            denom = filledArray[indexes[numerCount..numerCount+denomCount-1]]
            ratio = Math.log(mean(numer) / mean(denom)) / Math.log(10)
            if (!Double.isNaN(ratio)) ratioList.add(ratio)  // NOTE: only NaN filtered
        }

    *** IMPORTANT — Java only checks !isNaN, NOT !isInfinite ***
    If mean(denom)==0 and mean(numer)>0, Java gets log(+Inf)/log(10) = +Inf,
    which is NOT NaN, so it IS added to the list.
    However, in practice OD values are positive floats so mean(denom) is
    essentially never exactly 0.0.  Instead, use math.isfinite() as the guard
    (filters both NaN and Inf) because letting Inf into sigma blows up the
    bisection.  This is the safe practical equivalent.

    For sampling: Java's Permutation cycles through all n! orderings.
    rng.sample (without replacement) is the correct equivalent when
    pool >= total; rng.choices (with replacement) is used when pool < total,
    matching Java's Permutation behaviour on small arrays.
    """
    ratios: List[float] = []
    L     = filled.size
    total = numer_count + denom_count
    for _ in range(max_ratios):
        # Java: p.next() always returns a full permutation of [0..L-1]
        # and only uses the first numer+denom elements
        picks = rng.choices(range(L), k=total) if total > L else rng.sample(range(L), k=total)
        m_num = float(np.mean(filled[picks[:numer_count]]))
        m_den = float(np.mean(filled[picks[numer_count:total]]))
        if m_den == 0.0:
            continue   # avoid divide-by-zero; in practice near-impossible with OD data
        raw = m_num / m_den
        if raw <= 0:
            continue   # log of zero/negative → NaN in Java → skipped
        ratio = math.log10(raw)
        if math.isfinite(ratio):   # filters both NaN and Inf for numerical safety
            ratios.append(ratio)
    return ratios


def _build_system_marker_map(readouts: List[str]) -> Dict[str, List[str]]:
    # Translates EnvelopeService.buildCommonSystemMarkerMap
    sm: Dict[str, List[str]] = {}
    for sr in readouts:
        sys, mrk = sr.split(":", 1) if ":" in sr else ("default", sr)
        sm.setdefault(sys, []).append(mrk)
    return sm

class EnvelopeService:

    # ------------------------------------------------------------------
    # Path 1: pre-built control/sigma CSV files
    # Translates: EnvelopeService.service(Object) using pre-built files
    # ------------------------------------------------------------------

    def service(self, model: EnvelopeModel, control_csv: str, sigma_csv: str,
                csv_sep: str = ",") -> EnvelopeModel:
        df_ctrl, common_readouts = self._read_control_data(
            control_csv, model.system_marker_list, csv_sep)
        if not common_readouts or df_ctrl.empty:
            model.significance_envelope_map = {}
            model.hit_envelope_map          = {}
            model.system_marker_map         = {}
            return model

        # makeControlDataMatrix: pivot df into matrix, compute sig env per column
        sig_map, ctrl_matrix = self._make_control_matrix_and_sig_map(
            df_ctrl, common_readouts, model.confidence)
        model.significance_envelope_map = sig_map

        # readSigmasFromFile: sigma values aligned to common_readouts order
        sigmas = self._read_sigmas(sigma_csv, common_readouts, sep=csv_sep)

        # Global bisection over all valid readouts → single M
        valid  = np.isfinite(sigmas) & (sigmas > 0)
        if not np.any(valid):
            model.hit_envelope_map = {r: float("nan") for r in common_readouts}
        else:
            M = _bisect_multiplier(sigmas[valid], ctrl_matrix[:, valid], model.confidence)
            model.hit_envelope_map = {
                r: float(M * sigmas[j]) if valid[j] else float("nan")
                for j, r in enumerate(common_readouts)
            }

        model.system_marker_map = _build_system_marker_map(common_readouts)
        return model

    # ------------------------------------------------------------------
    # Path 2: raw DB export CSV
    # Translates: UpdateControlDataService.service() + EnvelopeService.service()
    # ------------------------------------------------------------------

    def envelope_service_from_export(
        self,
        model: EnvelopeModel,
        export_csv: pd.DataFrame,
        assay_ids: Sequence[int],
        profile_type: str          = NAME_SCREENING,
        confidence: float          = DEFAULT_CONFIDENCE,
        concentration: float       = 0.1,
        exclude_visual: bool       = True,
        random_seed: Optional[int] = 4,
        system_marker_order: Optional[List[str]] = None,
    ) -> EnvelopeModel:
        """
        Three-phase pipeline matching Java exactly:

        PHASE 1 — UpdateControlDataService.makeRatioList  (per plate per SR)
            Java: mean = BSKStatistics.mean(od_list)   ← per-plate OD mean
                  filled = fillByNormDist(od_list, mean, stddev, maxWellNum)
                  ratios += makeRatio(filled, numer, denom, maxNumRatio)

        PHASE 2 — UpdateControlDataService.service() loop  (per SR, global)
            Java: sigma = BSKStatistics.stddev(all_ratios)
                  double mean = 0;                     ← HARDCODED 0, not ratio mean
                  filled = fillByNormDist(all_ratios, 0, sigma, MATRIX_ROWS)
                  calSigEnv(filled) → sig_env value
                  fillMatrix(ctrl_matrix, filled, col) → |filled| into column

        PHASE 3 — EnvelopeService.calculateHitEnvelope  (one global bisection)
            Java: M = bisect over ALL common_readouts columns together
                  hit_envelope[sr] = sigma[sr] * M   for every sr


        *** 24March2026: Removed Phases 2 & 3 and set multiplier based on z-scole a la Java code ***
        """

        rng          = random.Random(random_seed)
        is_screening = profile_type.strip().upper() == "SCREENING"

        # ---- Load and filter the DB export ----
        # Matches the SQL in UpdateControlDataService.buildSQL:
        #   WHERE n450neg650_result IS NOT NULL
        #   AND concentration = 0.1
        #   AND readout_name NOT LIKE '%Visual%'
        #   AND assay_id IN (...)
        df = export_csv
        #df = df.rename(columns={c: c.upper() for c in df.columns})
        df["SYSTEM_NAME"]  = df["SYSTEM_NAME"].map(sys_converter)
        df["READOUT_NAME"] = df["READOUT_NAME"].map(mrk_converter)
        df = df.rename(columns={"N450NEG650_RESULT": "RESULT"})
        df = df[df["RESULT"].notna()]

        for threshold in [10, 100, 1000]:
            n = (df["RESULT"] > threshold).sum()
            print(f"RESULT > {threshold}: {n} rows ({100*n/len(df):.1f}%)")

        if "CONCENTRATION" in df.columns:
            df = df[df["CONCENTRATION"] == concentration]
        if exclude_visual:
            df = df[~df["READOUT_NAME"].astype(str).str.contains(
                "Visual", case=False, na=False)]
        df = df[df["ASSAY_ID"].isin(assay_ids)]

        # Java: sr = system_name || ':' || readout_name
        #       at = assay_name  || ':' || plate_barcode
        df["SR"] = (df["SYSTEM_NAME"].astype(str) + ":" + df["READOUT_NAME"].astype(str))
        df["AT"] = df["ASSAY_NAME"].astype(str)  + ":" + df["PLATE_BARCODE"].astype(str)
        ##print(f"[DEBUG] unique_SR={df['SR'].nunique()}")

        # Java parseDB: build sr_at_ods HashMap<SR, HashMap<AT, ArrayList<Double>>>
        sr_at_groups: Dict[str, Dict[str, List[float]]] = {}
        for (sr, at), g in df.groupby(["SR", "AT"]):
            sr_at_groups.setdefault(sr, {})[at] = g["RESULT"].astype(float).dropna().tolist()

        # ---- PHASE 1: generate ratio lists ----
        # numer_count: 1 for screening, 3 for profile (Java SCREEN_WELL_NO / PROFILE_WELL_NO)
        numer_count = SCREEN_WELL_NO if is_screening else PROFILE_WELL_NO
        sr_ratiolist: Dict[str, List[float]] = {}
        skipped = 0

        for sr, at_map in sr_at_groups.items():
            all_ratios: List[float] = []
            n_plates = len(at_map)

            for at, od_list in at_map.items():
                # Java: if (od_list.size() < MIN_WELL_NO) continue;
                if len(od_list) < MIN_WELL_NO:
                    skipped += 1
                    continue

                # Java PHASE-1 fill: mean = BSKStatistics.mean(od_list)  ← per-plate mean
                plate_mean   = float(np.mean(od_list))
                plate_stddev = float(np.std(od_list, ddof=1)) if len(od_list) >= 2 else 0.0

                # Java: maxWellNum = Math.max(od_list.size(), numer + denom)
                max_well_num = max(len(od_list), numer_count + DMSO_WELL_NO)
                filled = _fill_by_norm_dist(od_list, plate_mean, plate_stddev,
                                            max_well_num, rng)

                # Java: maxNumRatio logic (screening and profile differ)
                if is_screening:
                    # Java: maxNumRatio = SCREEN_MAX_NUMRATIO (=9)
                    #       if (at_ods.size() < 6) maxNumRatio = 2 * filledArray.length
                    max_num_ratio = SCREEN_MAX_NUMRATIO
                    if n_plates < 6:
                        max_num_ratio = 2 * filled.size
                else:
                    # Java: maxNumRatio = PROFILE_MAX_NUMRATIO (=150)
                    #       if (3*MAX/n_plates < PROFILE_MAX) maxNumRatio = 3*MAX/n_plates + 1
                    #       (no separate <6 override for profile in Java)
                    max_num_ratio = PROFILE_MAX_NUMRATIO
                    adaptive = 3 * MAX_SCREENPROFILE_NUM // n_plates + 1
                    if adaptive < PROFILE_MAX_NUMRATIO:
                        max_num_ratio = adaptive

                all_ratios.extend(_make_ratio(filled, numer_count, DMSO_WELL_NO,
                                              max_num_ratio, rng))

            if all_ratios:
                sr_ratiolist[sr] = all_ratios

        ##print(f"[DEBUG] Plates skipped MIN_WELL_NO: {skipped}")
        ##print(f"[DEBUG] SRs with ratio data: {len(sr_ratiolist)}")
        if not sr_ratiolist:
            print("[DEBUG] EARLY EXIT: no ratio lists built")
            model.significance_envelope_map = {}
            model.hit_envelope_map          = {}
            model.system_marker_map         = {}
            return model

        # ---- Resolve which SRs from system_marker_order have ratio data ----
        # sr_ratiolist keys are converted names (via sys_converter/mrk_converter).
        # system_marker_order strings come from the workbook and may differ in
        # capitalisation.  Match via lower-cased normalised form.
        # order_keys[i] = sr_ratiolist key for system_marker_order[i], or None if no data.
        ratios_norm: Dict[str, str] = {
            _normalize_sysmrk(k): k for k in sr_ratiolist
        }
        if system_marker_order is not None:
            system_marker_order = [_normalize_sysmrk(x) for x in system_marker_order]
            order_keys: List[Optional[str]] = [
                ratios_norm.get(_normalize_sysmrk(r), None)
                for r in system_marker_order
            ]
            common_readouts = [k for k in order_keys if k is not None]
            #print(f"[DEBUG] system_marker_order={len(system_marker_order)}, "
            #      f"matched={len(common_readouts)}, "
            #      f"unmatched={sum(1 for k in order_keys if k is None)}")
        else:
            common_readouts = list(sr_ratiolist.keys())
            order_keys      = common_readouts  # type: ignore

        #### PHASE 2 + 3: Sigma * z-score
        # Use z score for confidence to designate multiplier. 
        # Viewer code works out where value is roughly 1.95-2.00 * sigma

        z_score = _norm.ppf((1.0 + confidence) / 2.0)
        #print(f"[DEBUG] z_score for confidence={confidence}: {z_score:.6f}")

        sigma_arr = np.empty(len(common_readouts), dtype=float)
        sig_env_map: Dict[str, float] = {}
        hit_map_inner: Dict[str, float] = {}

        for j, sr in enumerate(common_readouts):
            all_ratios   = sr_ratiolist[sr]
            sigma_j      = stddev(all_ratios)
            sigma_arr[j] = sigma_j

            val = float(sigma_j * z_score) if sigma_j > 0 else float("nan")
            sig_env_map[sr]     = val
            hit_map_inner[sr]       = val

        ##print(f"[DEBUG] hit_map_inner entries={len(hit_map_inner)}, "
        #      f"sigma range[{sigma_arr.min():.5f}, {sigma_arr.max():.5f}]")

        # ---- Re-key output maps by system_marker_order strings ----
        # hit_map_inner is keyed by converted SR strings (from sr_ratiolist).
        # The Excel writer looks up by system_marker_order strings.
        # Map back using order_keys which aligns the two.
        # SRs with no data remain absent → blank cells in Excel (matches Java).
        if system_marker_order is not None:
            hit_map_out:     Dict[str, float] = {}
            sig_env_map_out: Dict[str, float] = {}
            for orig_sr, ratio_key in zip(system_marker_order, order_keys):
                if ratio_key is None:
                    continue   # no data for this SR
                if ratio_key in hit_map_inner:
                    hit_map_out[orig_sr]     = hit_map_inner[ratio_key]
                if ratio_key in sig_env_map:
                    sig_env_map_out[orig_sr] = sig_env_map[ratio_key]
        else:
            hit_map_out     = hit_map_inner
            sig_env_map_out = sig_env_map

        model.hit_envelope_map          = hit_map_out
        model.significance_envelope_map = sig_env_map_out
        model.system_marker_map         = _build_system_marker_map(list(hit_map_out.keys()))

        ##print(f"[DEBUG] Final hit_map keys={len(model.hit_envelope_map)}, "
        #      f"sig_env keys={len(model.significance_envelope_map)}")

        print(f"[DEBUG] envelope keys: {len(model.hit_envelope_map)}")
        print(f"[DEBUG] requested readouts: {len(system_marker_order) if system_marker_order else 'N/A'}")

        return model

    def _read_control_data(self, control_csv: str, requested: List[str],
                           sep: str) -> Tuple[pd.DataFrame, List[str]]:
        df         = pd.read_csv(control_csv, sep=sep, encoding="utf-8")
        req_norm   = [_normalize_sysmrk(x) for x in requested]
        req_set    = set(req_norm)
        hdr_norm   = {c: _normalize_sysmrk(c) for c in df.columns}
        keep_pairs = [(co, cn) for co, cn in hdr_norm.items() if cn in req_set]
        if not keep_pairs:
            return pd.DataFrame(columns=[]), []
        out_cols = [next(co for co, cn in keep_pairs if cn == nm)
                    for nm in req_norm if any(cn == nm for _, cn in keep_pairs)]
        df = (df[out_cols]
              .apply(pd.to_numeric, errors="coerce")
              .dropna(how="all")
              .reset_index(drop=True))
        common = [nm for nm in requested
                  if _normalize_sysmrk(nm) in {cn for _, cn in keep_pairs}]
        df.columns = common
        return df, common

    def _make_control_matrix_and_sig_map(
        self, df_ctrl: pd.DataFrame, readouts: List[str], confidence: float
    ) -> Tuple[Dict[str, float], np.ndarray]:
        ctrl = df_ctrl[readouts].to_numpy(dtype=float)
        sig  = {}
        for j, r in enumerate(readouts):
            col = ctrl[:, j]
            col = col[np.isfinite(col)]
            sig[r] = float(java_percentile(col, confidence)) if col.size else float("nan")
        return sig, ctrl

    def _read_sigmas(self, sigma_csv: str, readouts: List[str],
                     sep: str) -> np.ndarray:
        df = pd.read_csv(sigma_csv, sep=sep, encoding="utf-8")
        if df.shape[0] < 1:
            raise ValueError("Sigma CSV has no data rows")
        cols_norm = {c: _normalize_sysmrk(c) for c in df.columns}
        row       = df.iloc[0]
        by_name: Dict[str, float] = {}
        for co, cn in cols_norm.items():
            try:
                by_name[cn] = float(row[co])
            except Exception:
                pass
        req = [_normalize_sysmrk(x) for x in readouts]
        sig = np.array([by_name.get(nm, np.nan) for nm in req], dtype=float)
        ##print(f"[DEBUG] sigma NaN count: {int(np.sum(~np.isfinite(sig)))}")
        return sig

ENVELOPE_SHEET_NAME = "Envelope"


def write_envelope_sheet_xlsx(
    ws: Worksheet,
    readout_names_in_order: List[str],
    envelope_model: EnvelopeModel,
    envelope_type: str       = "Sig",
    profile_column_name: str = "Profile",
    envelope_source: str     = "hit",
) -> None:
    ws.cell(row=1, column=1, value=profile_column_name)
    for idx, r in enumerate(readout_names_in_order, start=2):
        ws.cell(row=1, column=idx, value=r)
    env_map = (envelope_model.hit_envelope_map
               if envelope_source.lower().startswith("hit")
               else envelope_model.significance_envelope_map)
    label = (f"{envelope_type},{envelope_model.confidence}%,"
             f"{envelope_model.envelope_data_type_name()}")
    ws.cell(row=2, column=1, value=label)
    for idx, r in enumerate(readout_names_in_order, start=2):
        val = env_map.get(r)
        if val is None:
            continue
        try:
            ws.cell(row=2, column=idx, value=float(val))
            ws.cell(row=3, column=idx, value=-float(val))
        except (TypeError, ValueError):
            pass


def update_workbook_envelope(
    workbook_or_path: Union[str, Workbook],
    readout_names_in_order: List[str],
    envelope_model: EnvelopeModel,
    sheet_name: str          = ENVELOPE_SHEET_NAME,
    envelope_type: str       = "Sig",
    profile_column_name: str = "Profile",
    save_path: Union[str, None] = None,
    envelope_source: str     = "hit",
) -> Workbook:
    wb = load_workbook(workbook_or_path) if isinstance(workbook_or_path, str) else workbook_or_path
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.create_sheet(sheet_name)
    write_envelope_sheet_xlsx(ws, readout_names_in_order, envelope_model,
                               envelope_type, profile_column_name, envelope_source)
    if save_path:
        wb.save(save_path)
    return wb

def run_helper_envelope(
    control_csv: str,
    sigma_csv: str,
    readout_names_in_order: List[str],
    workbook_or_path: Union[str, Workbook],
    confidence: float           = 0.95,
    data_type: str              = NAME_SCREENING,
    csv_sep: str                = ",",
    envelope_type_label: str    = "Sig",
    save_path: Union[str, None] = None,
    envelope_source: str        = "hit",
) -> Workbook:
    model = EnvelopeModel()
    model.set_data_type(data_type)
    model.envelope_type = ENVELOPE_SIGNIFICANCE
    model.confidence    = confidence
    model.set_system_marker_list(readout_names_in_order)
    model = EnvelopeService().service(model, control_csv, sigma_csv, csv_sep)
    return update_workbook_envelope(workbook_or_path, readout_names_in_order, model,
                                    ENVELOPE_SHEET_NAME, envelope_type_label,
                                    "Profile", save_path, envelope_source)


def run_helper_envelope_from_export(
    control_export_csv: pd.DataFrame,
    assay_ids: Sequence[int],
    readout_names_in_order: List[str],
    workbook_or_path: Union[str, Workbook],
    profile_type: str           = NAME_SCREENING,
    confidence: float           = 0.95,
    data_type: str              = NAME_SCREENING,
    envelope_type_label: str    = "Sig",
    save_path: Union[str, None] = None,
    envelope_source: str        = "hit",
    concentration: float        = 0.1,
    exclude_visual: bool        = True,
    random_seed: Optional[int]  = 4,
) -> Workbook:
    model = EnvelopeModel()
    model.set_data_type(data_type)
    model.envelope_type = ENVELOPE_SIGNIFICANCE
    model.confidence    = confidence
    model.set_system_marker_list(readout_names_in_order)
    model = EnvelopeService().envelope_service_from_export(
        model, control_export_csv, assay_ids, profile_type, confidence,
        concentration, exclude_visual, random_seed, readout_names_in_order)
    return update_workbook_envelope(workbook_or_path, readout_names_in_order, model,
                                    ENVELOPE_SHEET_NAME, envelope_type_label,
                                    "Profile", save_path, envelope_source)