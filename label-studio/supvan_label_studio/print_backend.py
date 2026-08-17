from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .core import LabelDocument, PRINTABLE_WIDTH_DOTS


class PrintError(RuntimeError):
    pass


def export_png(doc: LabelDocument, path: str | Path) -> Path:
    """Export the exact device raster: 88 dots across by N feed dots."""
    path = Path(path)
    img = doc.render()
    img.save(path, format="PNG", optimize=True)
    return path


def export_jpeg_exact(doc: LabelDocument, path: str | Path) -> Path:
    """Export the exact-width grayscale JPEG used for CUPS pass-through.

    The Rust E10 service recognizes an 88-pixel-wide JPEG as an exact Label
    Studio raster.  Its pixel height is therefore the requested continuous-roll
    length in 8-dot/mm feed columns, instead of the nominal RFID media height.
    """
    path = Path(path)
    img = doc.render().convert("L")
    if img.width != PRINTABLE_WIDTH_DOTS:
        raise PrintError(f"internal raster width is {img.width}, expected {PRINTABLE_WIDTH_DOTS}")
    # Grayscale JPEG has no chroma subsampling.  Quality 100 keeps the already
    # pixel-aligned QR/text artwork effectively lossless for the driver's final
    # 1-bit dithering stage while preserving the proven image/jpeg CUPS path.
    img.save(path, format="JPEG", quality=100, optimize=False)
    return path


def list_cups_queues() -> list[str]:
    """Return configured CUPS printer queues in display order."""
    if shutil.which("lpstat") is None:
        return []
    proc = subprocess.run(["lpstat", "-p"], text=True, capture_output=True)
    if proc.returncode not in (0, 1):
        return []
    queues: list[str] = []
    for line in proc.stdout.splitlines():
        m = re.match(r"^printer\s+(\S+)", line.strip())
        if m:
            queues.append(m.group(1))
    return queues


def choose_default_queue(queues: list[str], preferred: str | None = None) -> str:
    """Pick the most likely SUPVAN/E10 queue without hard-coding a machine name."""
    if preferred and preferred in queues:
        return preferred
    if not queues:
        return preferred or ""
    for tokens in (("supvan", "e10"), ("t0010",), ("supvan",)):
        for q in queues:
            low = q.lower()
            if all(token in low for token in tokens):
                return q
    return queues[0]


def detect_default_queue(preferred: str | None = None) -> str:
    return choose_default_queue(list_cups_queues(), preferred)


def _queue_exists(queue: str) -> bool:
    if shutil.which("lpstat") is None:
        return True
    proc = subprocess.run(["lpstat", "-p", queue], text=True, capture_output=True)
    return proc.returncode == 0


def print_document(doc: LabelDocument, queue: str | None = None) -> str:
    """Submit Label Studio's exact raster through the proven JPEG pass-through.

    v0.1 used an exact-size PDF plus Custom.11xNmm media.  CUPS tried to filter
    that custom page and could end in `filter failed`.  The E10 printer app
    already advertises and accepts image/jpeg directly, which is the same path
    used by the release-gate hardware tests, so v0.2 submits that format without
    any custom-media filter options.
    """
    if shutil.which("lp") is None:
        raise PrintError("CUPS command 'lp' was not found")
    queue = detect_default_queue((queue or doc.queue or "").strip() or None)
    if not queue:
        raise PrintError("No CUPS printer queue was found. Pair/start the E10 driver, then refresh printers in Label Studio.")
    if not _queue_exists(queue):
        raise PrintError(f"CUPS queue '{queue}' does not exist")

    with tempfile.TemporaryDirectory(prefix="supvan-label-") as td:
        jpeg = Path(td) / "label-studio-exact.jpg"
        export_jpeg_exact(doc, jpeg)
        cmd = ["lp", "-d", queue, str(jpeg)]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            details = (proc.stderr or proc.stdout or "unknown CUPS error").strip()
            raise PrintError(f"CUPS rejected the JPEG job.\n\n{details}")

        out = (proc.stdout or "Print job submitted.").strip()
        m = re.search(r"request id is\s+(\S+)", out, flags=re.IGNORECASE)
        job_id = m.group(1) if m else None
        length_dots = doc.render().height
        length_mm = length_dots / 8.0
        suffix = (
            f"\nExact E10 raster: {PRINTABLE_WIDTH_DOTS} × {length_dots} dots "
            f"({length_mm:g} mm long)."
        )
        if job_id:
            suffix += f"\nCUPS job: {job_id}"
        return out + suffix
