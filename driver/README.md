# E10 printer driver component

This directory is the Rust printer-service component of the
[SUPVAN E10 Linux Suite](../README.md).

It is derived from the MIT-licensed `heeen/supvan-cups` project. See
[../ATTRIBUTION.md](../ATTRIBUTION.md).

## E10-specific behavior in this fork

The SUPVAN E10 (`T0010...`) does **not** use the T50 print flow. Reverse
engineering of the vendor Android application showed that it uses the T15
printing process.

The qualified E10 path uses:

- 8 dots/mm;
- 96-dot physical printhead;
- 88-dot printable content band;
- 12 bytes per feed column;
- 4000-byte T15 raw buffers with a 14-byte header;
- up to 332 feed columns per raw buffer;
- independent LZMA compression per buffer;
- `START_PRINT`, `PAPER_BACK`, compressed transfer and `BUF_FULL(0)`;
- natural completion without `STOP_PRINT` on success.

The printer application exposes the device through IPP/CUPS and also accepts
an **88-pixel-wide JPEG** as an exact E10 continuous-roll raster. In that mode,
the JPEG height is the requested feed length.

## Build and test

```bash
cargo fmt --check
cargo test --workspace
cargo check --all-targets
```

## User install

```bash
make deploy
```

The repository-root `install.sh` installs both the driver and Label Studio.
