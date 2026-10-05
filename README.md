Written for: your client (simple version, with a real example from the export file)

---

**Subject: BioMAP Viewer Cytotoxicity Matching — Update**

Hi [Client Name],

Quick explanation with a real example from the data, plus current status.

**The issue, explained with real numbers:**

For compound Tamoxifen (40000 nM), these are the actual toxicity readings:

| Marker | Value | Should be toxic (below -0.3)? |
|---|---|---|
| BE3C:SRB | -0.284 | No |
| CASM3C:SRB | -0.590 | Yes |

BioMAP Viewer's export has a layout bug: when one reading is missing for a compound, it skips that column instead of leaving it blank — which pushes every later value one column to the left. So on this row, Viewer's file shows:

| Marker | Viewer's flag |
|---|---|
| BE3C:SRB | 1 (toxic) — but its real value says it shouldn't be |
| CASM3C:SRB | 0 (not toxic) — but its real value says it should be |

The flags landed under the wrong markers. The underlying data was never wrong — just where Viewer's export placed it.

**What we did:** since Viewer's code is frozen and can't be changed, we updated MEGA to lay out that same row the exact same way Viewer does — so instead of MEGA showing the "textbook correct" flags and disagreeing with Viewer, MEGA now shows:

| Marker | MEGA's flag (now) |
|---|---|
| BE3C:SRB | 1 |
| CASM3C:SRB | 0 |

Matches Viewer exactly.

**Status:** development is complete — MEGA's output now matches Viewer 100% across all data checked (Profile Data, Error Bar, Biomarker Hits, Envelope, and Cytotoxicity, ~87,000 data points across 30 compounds). We'd like to test a few more real Viewer files to fully confirm this holds across a broader set before calling it closed.

Best,
[Your Name]
