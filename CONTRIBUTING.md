# Contributing

Thanks for helping make the E10 less mysterious on Linux.

## Before opening a bug

Please include:

- Linux distribution/version;
- printer model and the Bluetooth name prefix shown by BlueZ;
- whether the printer works in the vendor mobile app;
- whether the issue is in the Rust driver or Label Studio;
- relevant CUPS output (`lpstat -p -d`); and
- the relevant service log:

  ```bash
  journalctl --user -u supvan-printer-app --no-pager -n 150
  ```

Please remove private label contents, URLs, serial numbers or other sensitive
information from screenshots/logs before posting them publicly.

## Driver changes

```bash
cd driver
cargo fmt --check
cargo test --workspace
cargo check --all-targets
```

Changes to the E10 T15 wire protocol should include tests and should clearly
state whether they were validated on physical hardware.

## Label Studio changes

```bash
cd label-studio
PYTHONPATH=. python3 -m pytest -q
```

Keep printer protocol logic out of Label Studio. The GUI should render a
deterministic raster and let the Rust service own discovery, transport,
recovery and the T15 protocol.
