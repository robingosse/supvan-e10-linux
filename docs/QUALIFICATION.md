# E10 hardware qualification

The E10/T15 path was not accepted on the basis of unit tests alone. It was
qualified with a real SUPVAN E10 on Linux Mint using 15 mm stock.

## Gate 1 — protocol and multi-buffer output

- Exact 88 × 400 raster.
- 96-dot physical head / 88-dot printable content band.
- Two independent T15 raw buffers and two independent LZMA streams.
- `START_PRINT` → `PAPER_BACK` → buffer transfer → `BUF_FULL(0)` per buffer.
- Natural print completion without `STOP_PRINT` on success.
- Physical far-end second-buffer marker verified.

## Gate 2 — queue lifecycle and serialization

- Whole print jobs serialized per physical device.
- Live 15 × 50 material geometry re-read after preceding jobs.
- Unsafe E10 geometry fallback refused.
- Immediate back-to-back jobs each completed a full two-buffer transaction.
- Both jobs retired from CUPS and the printer returned idle.

## Gate 3 — service outage, cancellation and reconnect

- CUPS retained a job while the printer application was stopped.
- The retained job printed exactly once after service restart.
- A second queued job canceled while offline never reached the hardware.
- Explicit BlueZ disconnect followed by a successful fresh print.
- Final hardware status returned idle.

## Gate 4 — physical power loss and cold start

- A job queued while the physical printer was off survived and recovered.
- A real RFCOMM `EHOSTDOWN` condition with stale BlueZ `Connected=true` was
  reproduced.
- The driver cleared the stale BlueZ link with `Device1.Disconnect`, preserved
  pairing/trust, retried RFCOMM and completed the job.
- The printer service was also started while the E10 was physically off. A job
  remained held, then printed after the printer was powered on without a
  service restart.
- Final hardware state returned idle and physical output was visually accepted.

## What this qualification does not claim

- It does not qualify every model retained from the upstream SUPVAN driver.
- It does not yet qualify multi-metre continuous output.
- It does not establish an optimal density value for every stock type.
