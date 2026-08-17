# SUPVAN E10 Label Studio

GTK label editor for the E10 driver in this repository.

## Features

- left-to-right continuous tape canvas;
- auto-size or manual length;
- full-width movable QR generation from arbitrary text/URLs/data;
- text, images, boxes and lines;
- one-dot keyboard movement;
- exact 88-dot raster preview/export;
- automatic CUPS queue detection with manual override;
- direct JPEG submission through the companion E10 driver.

The editor deliberately contains **no Bluetooth or T15 protocol code**. It
renders a deterministic device raster and hands that raster to CUPS. The Rust
driver remains the single owner of Bluetooth, recovery, material checks and
printer protocol.

## Run from source

```bash
PYTHONPATH=. python3 run.py
```

## Tests

```bash
PYTHONPATH=. python3 -m pytest -q
```
