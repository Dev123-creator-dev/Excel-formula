

Following up on your latest findings — all issues are now fixed and verified against the comparison data you sent. I've attached the latest MEGA export file, along with a side-by-side comparison file showing Viewer and MEGA data together so you can review directly.

**1. BSK-###### codes removed from export (all tabs)**
Profile names across every sheet now show just "Agent, Concentration Unit" — the internal BSK reference code is no longer included.

**2. Profile Data precision — now matches Viewer exactly**
Traced this to Viewer's own source code: every readout value is stored internally as a 32-bit number format with less precision than what MEGA was using. MEGA now applies that same rounding behavior before writing each value, matching Viewer's actual output digit-for-digit — including cases where Viewer shows 7 decimal places instead of 8, which needed a second pass to get fully correct.

**3. Envelope tab label corrected**
Now reads "Sig, 0.95%, Screening" — matching Viewer, instead of the incorrect "Trusted" label.

**4. Biomarker Hits — blank for untested readouts**
Readouts with no underlying data now correctly show blank instead of 0, so it's clear which readouts were actually tested versus not.

**5. Cytotoxicity shifting error**
As you confirmed already — no issues, corrected within MEGA.

**Verification:** I ran a full comparison between the latest MEGA export and your Viewer data using exact matching (no rounding tolerance) — every value, every column, across all 54 compounds. Result: **zero mismatches** across Profile Data, Biomarker Hits, and Envelope.

Attached:
- Latest MEGA export file
- Comparison file with Viewer and MEGA data side by side, confirming all values now match

Let me know if you'd like to review anything further or test against additional compound batches.

Thanks,
