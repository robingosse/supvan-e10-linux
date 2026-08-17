# Attribution

This project contains a modified copy of the open-source `supvan-cups` Rust
printer stack originally published by **heeen** at
`https://github.com/heeen/supvan-cups` and distributed under the MIT license.

The E10 work in this repository began from upstream commit:

`89228892e0680946e330771a6625264913c3a399`

The public fork adds, among other changes:

- reverse-engineered SUPVAN E10 / `T0010...` T15 printing support;
- E10-specific 96-dot physical head / 88-dot printable-band handling;
- independent T15/LZMA print-buffer construction and multi-buffer transfer;
- E10 status semantics and live-material handling;
- per-printer print-job serialization;
- BlueZ stale-link recovery after physical power loss;
- persisted paired-device transport recovery across cold starts;
- an exact 88-pixel continuous-roll JPEG path for Label Studio; and
- the separate Python/GTK **SUPVAN E10 Label Studio** application.

SUPVAN is a trademark of its respective owner. This repository is an
independent, unofficial community project and is not affiliated with or
endorsed by SUPVAN.
