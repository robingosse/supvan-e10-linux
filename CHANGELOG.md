# Changelog

## 0.1.0 - 2026-08-17

First public-candidate package of the unofficial SUPVAN E10 Linux suite.

### Driver

- Adds physically qualified E10/T15 printing over Bluetooth Classic RFCOMM.
- Uses the E10's 96-dot physical head and verified 88-dot printable band.
- Supports independent compressed T15 buffers for continuous multi-buffer jobs.
- Uses live material information and refuses unsafe E10 geometry fallback.
- Serializes complete jobs per physical printer.
- Recovers held CUPS jobs after application outages and printer power cycles.
- Repairs stale BlueZ `Connected=true` state on observed RFCOMM `EHOSTDOWN`.
- Restores persisted paired-device transport information after cold start.
- Accepts exact 88-pixel-wide JPEG rasters as continuous-roll E10 jobs.

### Label Studio

- Left-to-right continuous tape canvas.
- Auto-size or manual label length.
- Full-width movable QR-code generation.
- Text, images, boxes and lines.
- Exact 88-dot raster export.
- Direct JPEG submission through CUPS, avoiding custom-PDF `filter failed` jobs.
- Automatic CUPS queue detection with manual override and refresh.
- 5 mm to 6000 mm editor length range.
