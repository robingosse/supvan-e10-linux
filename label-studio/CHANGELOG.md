# Changelog

## 0.3.4 — 2026-09-02

- Corrected the core mental model to **15 mm continuous tape with variable feed
  length**, rather than treating ordinary labels like fixed-length cards.
- New text now defaults to **90°**, the normal along-the-tape orientation, while
  preserving manual 0°/90°/180°/270° rotation.
- Renamed the default text mode to **Continuous tape · fill printable band**. In
  this mode two or three explicit lines share the active printer profile's usable
  across-tape band and the longest line determines label length. Long messages
  therefore consume more tape instead of shrinking to fit a fixed length.
- Made auto-length the explicit recommended workflow and use symmetric leading
  and trailing padding for newly added continuous content.
- Locked the built-in verified E10 profile to the currently used **15.0 mm tape**
  while retaining the physically verified **11.0 mm / 88-dot** printable raster.
- Workbench-created authoring sessions now default to continuous auto-length unless
  a request explicitly specifies fixed length.
- Updated print confirmation/status copy to distinguish physical tape width from
  variable label length.
- Added five regression tests for 90° full-band text, multiline band sharing,
  content-driven feed length, standard orientation persistence, and canonical E10
  15 mm media. Total automated coverage: **34 passing tests**.

## 0.3.3 — 2026-09-02

- Added a streamlined **Sizing** selector for text: **Fill printable band** (new
  default), **Fit within Height**, or **Manual Height**. Full-band mode uses the
  active printer profile's usable physical width and fits correctly across 0°,
  90°, 180°, and 270° while retaining measured multiline fitting.
- Parameterized document raster geometry (`printable_width_dots`, `dots_per_mm`,
  printer profile key) instead of assuming 88 dots globally.
- Added per-CUPS-queue printer/media profiles with explicit stock width, usable
  printable width, resolution, media option, verification state, and transport.
- Added CUPS capability inspection via `lpoptions` for advertised resolution and
  media choices without fabricating unprintable margins.
- Kept the validated E10 production profile at **88 dots / 8 dots per mm / 11.0
  mm usable width** and blocked silent expansion of that exact-raster transport.
- Added generic CUPS image submission using DPI-tagged PNG for configured
  non-E10 profiles while preserving the E10 exact-JPEG route.
- Replaced the old 12/15-only stock validator with profile-friendly numeric stock
  widths.
- Updated Workbench template normalization to use the active printer geometry.
- Expanded automated coverage from 23 to 29 tests.

## 0.3.2 — 2026-09-02

- Centralized the visual design system in `theme.py` so future colour, button,
  spacing, and control changes are made in one place.
- Deepened the blue-on-blue workstation theme, cream controls, rounded
  squircle-like buttons, and soft raised/drop-shadow states.
- Added **Autofit to height** for text. The requested height becomes the fixed
  multiline block height and the renderer chooses the largest font that fits;
  two, three, or more lines shrink automatically instead of growing the block.
- Kept old `.supvanlabel` files backward compatible: pre-v0.3.2 text remains in
  manual-height mode unless Autofit is explicitly enabled.
- Added the `WORKBENCH-SUPVAN-STUDIO-1` JSON handoff contract and a
  **Return to Workbench** action for Workbench//OS-launched authoring sessions.
- Added normalized `GOSSIE-LABEL-TEMPLATE-1` export for supported Studio text,
  QR, and line objects while explicitly reporting unsupported object types.
- Expanded automated coverage to 23 tests plus the exact-raster self-test.

## 0.3.0 — 2026-09-02

- Rebuilt the editor as a workstation-first three-panel interface.
- Added undo/redo, dirty state, save-before-discard protection, persistent
  preferences, and keyboard shortcuts.
- Added layers, paint-order changes, exact positioning, alignment, and direct
  rotation controls.
- Added CUPS queue discovery, queue preflight, copy counts, and print
  confirmation.
- Added desktop icon, file association, direct file opening, and clean upgrade
  packaging.
- Preserved document schema version 2 and the E10 88-dot exact-JPEG print path.
- Expanded automated coverage from 9 tests to 19.
