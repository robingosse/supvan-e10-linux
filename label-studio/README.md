# SUPVAN Label Studio v0.3.2

Linux-native workstation editor for designing and printing continuous labels on
Robin's SUPVAN E10.

Version 0.3.2 is a workstation-polish, multiline-text, and Workbench//OS integration release. It preserves the physically proven E10 print architecture while making the editor easier on the eyes and easier to extend.

## What changed in v0.3.2

### Gentler workstation theme

- Soft blue-on-blue panels and chrome.
- Clearly raised buttons with hover, pressed, and disabled states.
- Cream input fields, text editors, tape stock, and printable canvas.
- Warm off-white text on the darker header and action buttons.
- Softer layer selection, scrollbars, separators, and status bar.

### Calmer three-part workspace

- Label tools and stock/printer controls live on the left.
- The horizontal tape canvas remains the centre of the editor.
- Precise object properties and layer controls live on the right.
- The header contains only document history and the primary print action.

### Safer editing

- Undo and redo with a 100-edit history.
- Unsaved-change prompts before New, Open, or Exit.
- Dirty-document indicator in the window title.
- Persistent workstation preferences for queue, stock width, zoom, copies, and recent working directories.
- Unique object IDs even after objects are deleted and added again.
- Existing v0.1/v0.2 `.supvanlabel` documents remain readable.

### Better design controls

- Layer list with send-back and bring-forward controls.
- Exact Across and Along position controls in millimetres.
- 0°, 90°, 180°, and 270° rotation.
- Top, centre, and bottom alignment within the verified printable band.
- Editable box/line thickness.
- Double-click an object to edit it.
- Keyboard nudging remains exact: Arrow = one 0.125 mm printer dot; Shift+Arrow = 1 mm.
- Long-label preview is capped to a safe GTK canvas width while the exported and printed raster retains its full resolution.

### Text autofit

- **Autofit to height** is available in Add Text and Edit Text.
- The Height value becomes the total multiline text-block height when Autofit is enabled.
- One line uses the available height; two lines shrink to roughly half-height each; three lines to roughly one-third, with actual font metrics used to prevent clipping.
- Existing documents remain manual-height by default for compatibility.

### Workbench//OS handoff

Workbench can launch Studio with:

```bash
supvan-label-studio --workbench-request /path/to/request.json
```

The request uses format `WORKBENCH-SUPVAN-STUDIO-1` and may contain a native document snapshot, document path, job/context identifiers, and a result path. Studio shows **Return to Workbench** for such sessions and writes a `WORKBENCH-SUPVAN-STUDIO-RESULT-1` result containing the native document plus a normalized `GOSSIE-LABEL-TEMPLATE-1` export for supported text, QR, and line objects. Unsupported object types are reported explicitly rather than silently discarded.

The bridge is intentionally file/CLI based so Workbench remains the owner of product/order/build/serial/QC identity and Studio remains the owner of interactive label authoring.

### Printer workflow

- Detects local CUPS queues instead of relying only on `gosse-e10`.
- Prefers the saved queue, then the system default, then an E10/SUPVAN-like queue.
- Printer Check explains missing, disabled, or unavailable queues.
- Print confirmation shows queue, copy count, physical label size, and exact raster dimensions.
- Multiple copies are submitted through CUPS.

### Desktop integration

- Application icon and Applications-menu launcher.
- `.supvanlabel` file association.
- Opening a label file from the file manager launches it in Studio.
- Uninstall keeps preferences and saved labels.

## Print architecture — intentionally unchanged

Label Studio contains no Bluetooth/T15 protocol code. It renders the exact device raster and submits it to CUPS as a grayscale JPEG.

- Printable raster: **88 dots across × N feed dots**
- Resolution: **8 dots/mm**
- Printable width: **11 mm**
- Supported stock visualization: **12 mm or 15 mm**
- Supported document length: **5 mm to 6000 mm**

The companion Rust E10 service owns Bluetooth discovery/recovery, material checks, job locking, and the two-buffer T15 transfer. The service recognizes an exactly 88-pixel-wide JPEG as a Label Studio continuous-length raster.

Use the preserved `supvan-cups-e10-public-r17` backend or a later compatible build. Do not replace it with the upstream generic driver unless that build also contains the 88-pixel exact-raster convention.

## Install on Linux Mint / Ubuntu

Install dependencies once:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo python3-pil python3-qrcode cups-client fonts-dejavu-core shared-mime-info
```

From the extracted release folder:

```bash
./install.sh
```

Then launch **SUPVAN Label Studio** from the Applications menu.

The installer writes only to the current user's `~/.local` directories. It does not need sudo and does not remove saved labels or preferences.

## Tests

```bash
PYTHONPATH=. python3 -m pytest -q
python3 scripts/self-test.py
```

The v0.3.2 source release contains 23 tests covering exact raster geometry, continuous lengths, QR sizing, template round-trips, auto-size behaviour, unique IDs, alignment, layer ordering, undo/redo, preferences, queue discovery, JPEG export, CUPS copy submission, text Autofit, and Workbench handoff.

## Uninstall

```bash
./uninstall.sh
```

This removes the application, launcher, icon, and MIME registration. Preferences and `.supvanlabel` documents remain.
