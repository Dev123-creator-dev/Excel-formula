Subject: MEGA Export Validation — Biomarker Hits Fixed & Matched with Production; Cytotoxicity Finding

Hi [Client Name],

Sharing an update on validating MEGA's export against real BioMAP Viewer output.

1. Biomarker Hits mismatch — found and fixed

Testing a few compounds today, I found MEGA's Biomarker Hits values didn't match the real BioMAP Viewer output. Root cause: MEGA was calculating the "hit" cutoff with a different formula than the one shown in its own Envelope sheet, while production BioMAP Viewer uses the same number for both. I corrected MEGA to match production's approach and re-tested — Biomarker Hits now match exactly (e.g., Alectinib at 10000 nM: 53 hits in both MEGA and the real BioMAP Viewer export).

2. Full validation against 3 real BioMAP Viewer exports (30 compounds)

With the fix applied, I compared MEGA's export against 3 real BioMAP Viewer files (production caps exports at 10 compounds each):

Sheet	Profiles Compared	Matched	Mismatched
Profile Data	188	188	0
Error Bar	188	188	0
Biomarker Hits	188	188	0
Envelope	3	3	0
Cytotoxicity	188	183	5
Total cells	86,924	86,906	18
99.98% match rate. Profile Data, Error Bar, Biomarker Hits, and Envelope matched 100%. The only discrepancy — 18 cells across 5 of 188 profiles — was in Cytotoxicity.

3. Cytotoxicity discrepancy — confirmed as a bug in BioMAP Viewer's own export, not MEGA

I verified this isn't a MEGA calculation error by checking the raw underlying values, which are identical in both tools. Example — Tamoxifen, 40000 nM, column CASM3C:SRB:

Both MEGA and BioMAP Viewer show the same reading: -0.590
The toxicity rule (same in both): a value below -0.3 must be flagged toxic (1)
MEGA's flag: 1 — correctly follows the rule on its own number
BioMAP Viewer's flag: 0 — contradicts its own number and its own rule
This isn't MEGA disagreeing with BioMAP Viewer — it's BioMAP Viewer disagreeing with itself. I traced this to how BioMAP Viewer's export code builds that one sheet: when a compound is missing a reading for one toxicity marker, the code skips that column instead of leaving it blank, which shifts every following value one column to the left in that row — landing values under the wrong marker's header. This only affects the Cytotoxicity sheet, only for profiles with a missing toxicity reading, and only in BioMAP Viewer's own export code. MEGA doesn't have this issue because it always writes every column in a fixed position, using blank for missing data instead of skipping it.

Summary: Biomarker Hits is fixed and confirmed matching production. Profile Data, Error Bar, and Envelope match 100%. The remaining 18-cell Cytotoxicity discrepancy is a pre-existing alignment issue in BioMAP Viewer's own export code — not something to fix in MEGA.

Happy to walk through the detailed comparison report if useful.
