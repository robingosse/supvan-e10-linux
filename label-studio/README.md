# SUPVAN Label Studio v0.3.4

Linux-native continuous-label editor built around Robin's SUPVAN E10, with a
printer-profile layer for adapting the same editor to other properly installed
CUPS printers.

## v0.3.4 — continuous tape model

The normal E10 workflow is now modeled correctly as **15 mm continuous tape**,
not a fixed-size 15×N card. The physical width stays fixed while the feed length
grows to fit the content.

### Standard text behaviour

New text defaults to **90°**, which is the normal along-the-tape reading
orientation in Studio's internal raster. Rotation remains editable at 0°, 90°,
180°, or 270° for exceptions.

The default text sizing mode is:

- **Continuous tape · fill printable band** — text uses the active printer
  profile's usable across-tape band. Two or three explicit lines share that
  vertical band, while the longest line determines how much tape is consumed.
  A longer message therefore makes a longer label instead of shrinking the font.
- **Fit within Height** — keeps a user-specified multiline block height.
- **Manual Height** — explicit manual sizing.

Use Enter in the text editor to create the normal two- or three-line labels.

For the validated E10 Linux path, physical media truth is currently:

- tape width: **15.0 mm**
- verified printable band: **88 dots / 8 dots per mm = 11.0 mm**
- length: **automatic from content** by default, up to the configured continuous
  roll limit
- normal text orientation: **90°**

The E10 manufacturer's larger nominal print-width claim is not silently treated
as verified raster width. If a wider E10 raster is physically proven later, it
can replace the printer profile without changing the editor model.

### Automatic length

Auto length is enabled by default. New content starts with the configured padding,
and the document feed length is recalculated from rendered object bounds plus end
padding. Editing a line from `BIN A` to a long description therefore increases
the tape length automatically.

Manual fixed length remains available for the uncommon cases where an exact label
length is required.

## Printer/media profiles + CUPS

Studio uses the Linux system print spooler rather than inventing a private printer
stack:

- queues are discovered through CUPS (`lpstat`);
- driver/media choices and advertised resolution are inspected with `lpoptions`
  when available;
- **Printer / Media Setup** stores stock width, usable printable width, resolution,
  optional CUPS media options, and physical verification state per queue;
- Studio never fabricates printable margins when CUPS does not report them;
- the validated E10 route uses the proven exact-width JPEG transport;
- configured non-E10 queues use a DPI-tagged PNG through CUPS.

The built-in verified E10 profile is now canonical **15 mm stock**. Generic/custom
printer profiles remain free to use different physical media widths.

User printer profiles are stored at:

```text
~/.config/supvan-label-studio/printer-profiles.json
```

## Workbench//OS

Workbench can launch Studio with:

```bash
supvan-label-studio --workbench-request /path/to/request.json
```

The `WORKBENCH-SUPVAN-STUDIO-1` / `WORKBENCH-SUPVAN-STUDIO-RESULT-1` handoff
remains intact. Workbench owns product/build/serial/QC truth and production print
records; Studio owns interactive label authoring. New Workbench authoring requests
default to continuous auto-length unless the request explicitly asks for fixed
length.

## Interface

The workstation UI retains the blue-on-blue / cream design system, rounded raised
buttons, three-panel editor, layers, undo/redo, direct positioning, printer
preflight, file association, preferences, and desktop launcher integration.

The centre canvas shows the 15 mm tape horizontally, with the verified printable
band centered inside it.

## Install on Linux Mint / Ubuntu

Install dependencies once:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo python3-pil python3-qrcode cups-client fonts-dejavu-core shared-mime-info
```

Then use the self-extracting `.run` installer, or from the source folder:

```bash
./install.sh
```

The installer writes only to the current user's `~/.local` directories and
preserves saved labels/preferences across upgrades.

## Tests

```bash
PYTHONPATH=. python3 -m pytest -q
PYTHONPATH=. python3 scripts/self-test.py
```

v0.3.4 contains **34 automated tests**, including explicit coverage that 90°
continuous text keeps the same physical print-band width while longer messages
produce longer feed rasters.

## Uninstall

```bash
./uninstall.sh
```

Preferences, printer profiles, and `.supvanlabel` documents are retained.
