Thank you for reviewing it. I have made the two updates you requested for Report Only Study, and the updated file is attached.

What was changed (Report Only Study only):

1. CT/CST Check table – now set to N/A automatically. When Report Only Study is selected, the CT/CST Check block auto-marks as N/A (shows a tick and dims), so those compound/assay checks no longer need to be completed. The rest of the AX Processing Checklist (Order Confirmed, AX Header Setup) stays active as before.

2. Study Details Check – #3 status reverted. Item #3 "Special Instructions Section Completed" and its sub-lines (CMT instructions, lab ops instructions, ICO instructions) now revert to active/"Not Ready" instead of N/A, so they are still completed. Items #1 and #2 remain N/A as before.

Nothing else was changed:
- No change to the layout, colours, checkboxes, or any section.
- All other study types (ADME, Ion Channel, BioMAP, Biomarker, Oncopanel, Biotherapeutics, and the combinations) behave exactly as before.
- The earlier freezing issue remains fixed.

You can verify quickly: select "Report Only Study" and confirm the CT/CST Check block shows N/A while Study Details #3 shows "Not Ready"; then select "ADME" and confirm both are active again.

For future reference, these two areas are now controlled individually in the Configuration tab (CT/CST Check set to No, Special Instructions set to Yes for Report Only), so any similar adjustment later is a single-cell change with no rebuild.

Please review and let me know if this matches what you had in mind, or if any further changes are needed.
