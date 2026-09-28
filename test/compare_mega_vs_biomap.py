"""
compare_mega_vs_biomap.py

Compares a MEGA export (full-database Excel export) against one or more real
BioMAP Viewer production exports, to verify MEGA's values match production.

WHY THIS EXISTS
----------------
The real BioMAP Viewer can only export 10 compounds at a time, so a full
validation run against production means collecting several small Viewer
export files (e.g. "Axiom.xlsx", "Axiom 2.xlsx", ...) and checking each one
against the single, full-database MEGA export. This script automates that:
point it at a folder of BioMAP files and one MEGA file, and it will find
every compound that appears in both, compare every sheet cell-by-cell, and
report any mismatches.

NAMING DIFFERENCE THIS SCRIPT HANDLES
--------------------------------------
The two tools label profiles differently, so matching is done by AGENT NAME
+ CONCENTRATION + UNIT, ignoring everything else in the profile name:

    BioMAP Viewer:  "Alectinib, 10000 nM"
    MEGA:           "ALECTINIB, BSK-C024544, 10000 nM"

If your export naming ever changes, adjust parse_profile_key() below - it's
the single place profile names get interpreted.

USAGE
-----
    python compare_mega_vs_biomap.py --mega "path/to/MEGA_Export.xlsx" --biomap "path/to/biomapOutput"

    --mega       Path to a single MEGA export .xlsx file.
    --biomap     Path to a single BioMAP Viewer .xlsx file, OR a folder
                 containing several of them (all .xlsx files in the folder
                 are used).
    --tolerance  Numeric tolerance for comparing floating point values.
                 Default: absolute 1e-4, relative 1e-3 (like numpy.isclose).
    --sheets     Comma-separated list of sheets to compare. Default: all of
                 "Profile Data,Error Bar,Cytotoxicity,Envelope,Biomarker Hits".
    --output     Where to write the detailed mismatch report (.xlsx).
                 Default: "comparison_report_<timestamp>.xlsx" next to this
                 script.

OUTPUT
------
Prints a pass/fail summary per compound and per sheet to the console, and
writes a detailed Excel report listing every mismatched cell (sheet,
compound, marker, MEGA value, BioMAP value, difference) plus a summary tab.
Exit code is 0 if everything matched within tolerance, 1 otherwise - so this
can be dropped into a CI/validation pipeline if needed.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

DEFAULT_SHEETS = ["Profile Data", "Error Bar", "Cytotoxicity", "Envelope", "Biomarker Hits"]

# Sheets that have an extra "count" column (e.g. "Cytotoxicity", "Biomarker Hits")
# right after the profile name, before the per-marker columns begin.
COUNT_COLUMN_SHEETS = {"Cytotoxicity", "Biomarker Hits"}

DEFAULT_ABS_TOL = 1e-4
DEFAULT_REL_TOL = 1e-3


def parse_profile_key(profile_name: str) -> Optional[Tuple[str, str]]:
    """
    Turn a profile name from either tool into a (AGENT, CONC_UNIT) key so
    MEGA and BioMAP Viewer profiles for the "same" compound/concentration
    match up, despite differing label formats:

        "Alectinib, 10000 nM"                    -> ("ALECTINIB", "10000 NM")
        "ALECTINIB, BSK-C024544, 10000 nM"        -> ("ALECTINIB", "10000 NM")
        "ALECTINIB, BSK-C024544, 10000.0 nM"      -> ("ALECTINIB", "10000 NM")

    Assumes the LAST comma-separated part is always "<concentration> <unit>"
    and the FIRST part is always the agent name; any parts in between
    (e.g. a BSK code) are ignored. Returns None if the name can't be parsed
    (e.g. missing a concentration/unit part) so the caller can flag it.
    """

    parts = [p.strip() for p in profile_name.split(",") if p.strip()]
    if len(parts) < 2:
        return None

    agent = parts[0].strip().upper()
    conc_unit_raw = parts[-1].strip()

    conc_parts = conc_unit_raw.split()
    if len(conc_parts) < 2:
        return None

    conc_str, unit = conc_parts[0], " ".join(conc_parts[1:])
    try:
        conc_val = float(conc_str)
    except ValueError:
        return None

    # Normalize "10000.0" and "10000" to the same key
    if conc_val == int(conc_val):
        conc_norm = str(int(conc_val))
    else:
        conc_norm = f"{conc_val:g}"

    return agent, f"{conc_norm} {unit.upper()}"


@dataclass
class SheetData:
    """One sheet's contents, keyed by parsed profile and column header."""

    # {(agent, conc_unit): {column_header: value}}
    rows: Dict[Tuple[str, str], Dict[str, object]] = field(default_factory=dict)
    # {(agent, conc_unit): original profile name string, for reporting}
    original_names: Dict[Tuple[str, str], str] = field(default_factory=dict)
    unparsed: List[str] = field(default_factory=list)


def _find_real_dimensions(ws) -> Tuple[int, int]:
    """
    Some BioMAP Viewer exports carry a stale <dimension> tag that under-reports
    max_row/max_col, so trust openpyxl's max_row/max_col only after loading
    the workbook WITHOUT read_only mode (which is what the caller does), and
    additionally scan the header row directly to confirm the real column
    count in case that's also short.
    """

    max_row = ws.max_row
    max_col = ws.max_column
    # Extend max_col defensively if the header row itself has more content
    # than max_col reports (seen with some Viewer-generated files).
    c = max_col + 1
    while ws.cell(row=1, column=c).value not in (None, ""):
        max_col = c
        c += 1
    return max_row, max_col


_WORKBOOK_CACHE: Dict[str, "openpyxl.Workbook"] = {}


def _load_workbook_cached(path: Path):
    # Each input file gets loaded once and reused across all sheet reads,
    # instead of once per sheet - the MEGA export in particular is large
    # enough (tens of MB) that reloading it 5x made a full run painfully slow.
    key = str(path.resolve())
    wb = _WORKBOOK_CACHE.get(key)
    if wb is None:
        wb = openpyxl.load_workbook(path, data_only=True)
        _WORKBOOK_CACHE[key] = wb
    return wb


def read_sheet(path: Path, sheet_name: str) -> Optional[SheetData]:
    wb = _load_workbook_cached(path)
    if sheet_name not in wb.sheetnames:
        return None
    ws = wb[sheet_name]
    max_row, max_col = _find_real_dimensions(ws)

    header = [ws.cell(row=1, column=c).value for c in range(1, max_col + 1)]
    if not header or header[0] is None:
        return None

    has_count_col = sheet_name in COUNT_COLUMN_SHEETS
    marker_start_col = 3 if has_count_col else 2  # 1-indexed

    data = SheetData()

    # Envelope sheet is special: it's not one row per profile, it's a fixed
    # pair of rows (positive/negative bound) shared across all profiles - so
    # there's nothing to key by compound. Treat it as a single pseudo-profile.
    if sheet_name == "Envelope":
        row2 = [ws.cell(row=2, column=c).value for c in range(2, max_col + 1)]
        key = ("__ENVELOPE__", "")
        data.rows[key] = {header[c - 1]: row2[c - 2] for c in range(2, max_col + 1)}
        data.original_names[key] = str(ws.cell(row=2, column=1).value)
        return data

    for r in range(2, max_row + 1):
        profile_name = ws.cell(row=r, column=1).value
        if profile_name is None or str(profile_name).strip() == "":
            continue
        key = parse_profile_key(str(profile_name))
        if key is None:
            data.unparsed.append(str(profile_name))
            continue

        row_values: Dict[str, object] = {}
        if has_count_col:
            row_values[header[1]] = ws.cell(row=r, column=2).value
        for c in range(marker_start_col, max_col + 1):
            col_name = header[c - 1]
            if col_name is None:
                continue
            row_values[col_name] = ws.cell(row=r, column=c).value

        data.rows[key] = row_values
        data.original_names[key] = str(profile_name)

    return data


def values_match(a: object, b: object, abs_tol: float, rel_tol: float) -> bool:
    a_is_num = isinstance(a, (int, float)) and not isinstance(a, bool)
    b_is_num = isinstance(b, (int, float)) and not isinstance(b, bool)

    a_none = a is None or (a_is_num and isinstance(a, float) and math.isnan(a))
    b_none = b is None or (b_is_num and isinstance(b, float) and math.isnan(b))
    if a_none and b_none:
        return True

    # BioMAP Viewer leaves a hit/tox flag cell blank for "not a hit"/"not
    # toxic" instead of writing 0, while MEGA always writes an explicit 0 -
    # treat blank and 0 as the same value rather than flagging every one of
    # these as a mismatch.
    if a_none and b_is_num and b == 0:
        return True
    if b_none and a_is_num and a == 0:
        return True
    if a_none != b_none:
        return False

    if a_is_num and b_is_num:
        return math.isclose(float(a), float(b), abs_tol=abs_tol, rel_tol=rel_tol)

    return str(a).strip() == str(b).strip()


@dataclass
class Mismatch:
    sheet: str
    compound_key: str
    mega_profile_name: str
    biomap_profile_name: str
    biomap_file: str
    column: str
    mega_value: object
    biomap_value: object


@dataclass
class ProfileMatch:
    """One (sheet, profile) pair that was found in both files, with its outcome."""
    sheet: str
    compound_key: str
    mega_profile_name: str
    biomap_profile_name: str
    biomap_file: str
    columns_compared: int
    columns_mismatched: int

    @property
    def status(self) -> str:
        return "MATCH" if self.columns_mismatched == 0 else "MISMATCH"


@dataclass
class ComparisonResult:
    matched_compounds: int = 0
    compared_cells: int = 0
    mismatches: List[Mismatch] = field(default_factory=list)
    profile_matches: List[ProfileMatch] = field(default_factory=list)
    mega_only_profiles: List[str] = field(default_factory=list)
    biomap_only_profiles: List[Tuple[str, str]] = field(default_factory=list)  # (name, source_file)
    unparsed_mega: List[str] = field(default_factory=list)
    unparsed_biomap: List[Tuple[str, str]] = field(default_factory=list)


def compare_files(mega_path: Path, biomap_paths: List[Path], sheets: List[str],
                   abs_tol: float, rel_tol: float) -> ComparisonResult:

    result = ComparisonResult()

    for sheet_name in sheets:
        mega_sheet = read_sheet(mega_path, sheet_name)
        if mega_sheet is None:
            print(f"  [skip] Sheet '{sheet_name}' not found in MEGA file, skipping.")
            continue
        result.unparsed_mega.extend(mega_sheet.unparsed)

        seen_mega_keys_for_sheet: set = set()

        for biomap_path in biomap_paths:
            biomap_sheet = read_sheet(biomap_path, sheet_name)
            if biomap_sheet is None:
                continue
            for name in biomap_sheet.unparsed:
                result.unparsed_biomap.append((name, biomap_path.name))

            for key, biomap_row in biomap_sheet.rows.items():
                mega_row = mega_sheet.rows.get(key)
                if mega_row is None:
                    if sheet_name == DEFAULT_SHEETS[0]:  # only log once, on first sheet
                        result.biomap_only_profiles.append(
                            (biomap_sheet.original_names[key], biomap_path.name))
                    continue

                seen_mega_keys_for_sheet.add(key)
                if sheet_name == DEFAULT_SHEETS[0]:
                    result.matched_compounds += 1

                columns_compared = 0
                columns_mismatched = 0
                for col_name, biomap_val in biomap_row.items():
                    mega_val = mega_row.get(col_name)
                    result.compared_cells += 1
                    columns_compared += 1
                    if not values_match(mega_val, biomap_val, abs_tol, rel_tol):
                        columns_mismatched += 1
                        result.mismatches.append(Mismatch(
                            sheet=sheet_name,
                            compound_key=f"{key[0]} @ {key[1]}",
                            mega_profile_name=mega_sheet.original_names[key],
                            biomap_profile_name=biomap_sheet.original_names[key],
                            biomap_file=biomap_path.name,
                            column=col_name,
                            mega_value=mega_val,
                            biomap_value=biomap_val,
                        ))

                result.profile_matches.append(ProfileMatch(
                    sheet=sheet_name,
                    compound_key=f"{key[0]} @ {key[1]}",
                    mega_profile_name=mega_sheet.original_names[key],
                    biomap_profile_name=biomap_sheet.original_names[key],
                    biomap_file=biomap_path.name,
                    columns_compared=columns_compared,
                    columns_mismatched=columns_mismatched,
                ))

        if sheet_name == DEFAULT_SHEETS[0]:
            all_biomap_keys = set()
            for biomap_path in biomap_paths:
                bs = read_sheet(biomap_path, sheet_name)
                if bs:
                    all_biomap_keys.update(bs.rows.keys())
            result.mega_only_profiles = [
                mega_sheet.original_names[k] for k in mega_sheet.rows.keys()
                if k not in all_biomap_keys
            ]

    return result


def write_report(result: ComparisonResult, output_path: Path, mega_path: Path,
                  biomap_paths: List[Path], abs_tol: float, rel_tol: float) -> None:

    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = "Summary"

    bold = Font(bold=True)
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")

    ws_summary.append(["MEGA vs BioMAP Viewer comparison report"])
    ws_summary["A1"].font = Font(bold=True, size=14)
    ws_summary.append([])
    ws_summary.append(["Generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    ws_summary.append(["MEGA file", str(mega_path)])
    ws_summary.append(["BioMAP file(s)", ", ".join(p.name for p in biomap_paths)])
    ws_summary.append(["Tolerance", f"abs={abs_tol}, rel={rel_tol}"])
    ws_summary.append([])
    ws_summary.append(["Compounds matched (found in both)", result.matched_compounds])
    ws_summary.append(["Cells compared", result.compared_cells])
    ws_summary.append(["Mismatches found", len(result.mismatches)])
    cell = ws_summary.cell(row=ws_summary.max_row, column=2)
    cell.fill = green_fill if not result.mismatches else red_fill
    ws_summary.append(["Profiles only in MEGA (not in any BioMAP file)", len(result.mega_only_profiles)])
    ws_summary.append(["Profiles only in BioMAP (not in MEGA)", len(result.biomap_only_profiles)])
    ws_summary.append(["Unparseable profile names (MEGA)", len(result.unparsed_mega)])
    ws_summary.append(["Unparseable profile names (BioMAP)", len(result.unparsed_biomap)])
    for row in ws_summary.iter_rows(min_row=3, max_row=ws_summary.max_row, min_col=1, max_col=1):
        row[0].font = bold

    ws_matched = wb.create_sheet("Matched Profiles")
    ws_matched.append(["Sheet", "Compound @ Concentration", "MEGA Profile Name",
                        "BioMAP Profile Name", "BioMAP Source File",
                        "Columns Compared", "Columns Mismatched", "Status"])
    for c in range(1, 9):
        ws_matched.cell(row=1, column=c).font = bold
    for pm in sorted(result.profile_matches, key=lambda x: (x.sheet, x.compound_key)):
        ws_matched.append([pm.sheet, pm.compound_key, pm.mega_profile_name,
                            pm.biomap_profile_name, pm.biomap_file,
                            pm.columns_compared, pm.columns_mismatched, pm.status])
        status_cell = ws_matched.cell(row=ws_matched.max_row, column=8)
        status_cell.fill = green_fill if pm.status == "MATCH" else red_fill

    ws_mismatch = wb.create_sheet("Mismatches")
    ws_mismatch.append(["Sheet", "Compound @ Concentration", "MEGA Profile Name",
                         "BioMAP Profile Name", "BioMAP Source File", "Column",
                         "MEGA Value", "BioMAP Value", "Difference"])
    for c in range(1, 10):
        ws_mismatch.cell(row=1, column=c).font = bold
    for m in result.mismatches:
        diff = None
        if isinstance(m.mega_value, (int, float)) and isinstance(m.biomap_value, (int, float)):
            diff = m.mega_value - m.biomap_value
        ws_mismatch.append([m.sheet, m.compound_key, m.mega_profile_name,
                             m.biomap_profile_name, m.biomap_file, m.column,
                             m.mega_value, m.biomap_value, diff])

    ws_missing = wb.create_sheet("Unmatched Profiles")
    ws_missing.append(["Only in MEGA"])
    ws_missing["A1"].font = bold
    for name in result.mega_only_profiles:
        ws_missing.append([name])
    start = ws_missing.max_row + 2
    ws_missing.cell(row=start, column=1, value="Only in BioMAP (compound, source file)").font = bold
    for name, src in result.biomap_only_profiles:
        ws_missing.append([name, src])

    wb.save(output_path)


def collect_biomap_files(biomap_arg: Path) -> List[Path]:
    if biomap_arg.is_dir():
        files = sorted(p for p in biomap_arg.glob("*.xlsx") if not p.name.startswith("~$"))
        return files
    return [biomap_arg]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a MEGA export against one or more real BioMAP Viewer exports.")
    parser.add_argument("--mega", required=True, type=Path, help="Path to the MEGA export .xlsx file")
    parser.add_argument("--biomap", required=True, type=Path,
                         help="Path to a BioMAP Viewer .xlsx file, or a folder containing several of them")
    parser.add_argument("--sheets", default=",".join(DEFAULT_SHEETS),
                         help=f"Comma-separated sheet names to compare. Default: {','.join(DEFAULT_SHEETS)}")
    parser.add_argument("--abs-tol", type=float, default=DEFAULT_ABS_TOL, help=f"Absolute tolerance (default {DEFAULT_ABS_TOL})")
    parser.add_argument("--rel-tol", type=float, default=DEFAULT_REL_TOL, help=f"Relative tolerance (default {DEFAULT_REL_TOL})")
    parser.add_argument("--output", type=Path, default=None, help="Output report path (.xlsx). Default: comparison_report_<timestamp>.xlsx next to this script")
    args = parser.parse_args()

    if not args.mega.exists():
        print(f"ERROR: MEGA file not found: {args.mega}")
        return 1
    if not args.biomap.exists():
        print(f"ERROR: BioMAP path not found: {args.biomap}")
        return 1

    biomap_paths = collect_biomap_files(args.biomap)
    if not biomap_paths:
        print(f"ERROR: No .xlsx files found under {args.biomap}")
        return 1

    sheets = [s.strip() for s in args.sheets.split(",") if s.strip()]

    print(f"MEGA file:    {args.mega}")
    print(f"BioMAP files: {len(biomap_paths)} file(s) -> {', '.join(p.name for p in biomap_paths)}")
    print(f"Sheets:       {', '.join(sheets)}")
    print(f"Tolerance:    abs={args.abs_tol}, rel={args.rel_tol}")
    print()

    result = compare_files(args.mega, biomap_paths, sheets, args.abs_tol, args.rel_tol)

    output_path = args.output or (Path(__file__).parent / f"comparison_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    write_report(result, output_path, args.mega, biomap_paths, args.abs_tol, args.rel_tol)

    print(f"Compounds matched (found in both):       {result.matched_compounds}")
    print(f"Cells compared:                           {result.compared_cells}")
    print(f"Mismatches found:                         {len(result.mismatches)}")
    print(f"Profiles only in MEGA:                    {len(result.mega_only_profiles)}")
    print(f"Profiles only in BioMAP:                  {len(result.biomap_only_profiles)}")
    print(f"Unparseable profile names (MEGA):         {len(result.unparsed_mega)}")
    print(f"Unparseable profile names (BioMAP):       {len(result.unparsed_biomap)}")
    print()
    print(f"Detailed report written to: {output_path}")

    if result.mismatches:
        print()
        print("RESULT: MISMATCHES FOUND - see report for details.")
        return 1

    print()
    print("RESULT: ALL COMPARED VALUES MATCH WITHIN TOLERANCE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
