from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .core import LabelDocument, PRINTABLE_WIDTH_DOTS


class PrintError(RuntimeError):
    pass


@dataclass(frozen=True)
class PrinterQueue:
    name: str
    enabled: bool = True
    status: str = ""
    is_default: bool = False


@dataclass(frozen=True)
class PrinterPreflight:
    ready: bool
    queue: str
    summary: str
    details: tuple[str, ...] = ()


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
    img.save(path, format="JPEG", quality=100, optimize=False)
    return path


def list_printer_queues() -> list[PrinterQueue]:
    """Return local CUPS queues without assuming a hard-coded E10 name."""
    if shutil.which("lpstat") is None:
        return []
    default = ""
    default_proc = subprocess.run(["lpstat", "-d"], text=True, capture_output=True)
    if default_proc.returncode == 0:
        match = re.search(r"(?:destination|printer):\s*(\S+)", default_proc.stdout, re.I)
        if match:
            default = match.group(1)

    proc = subprocess.run(["lpstat", "-p"], text=True, capture_output=True)
    if proc.returncode != 0:
        return []
    queues: list[PrinterQueue] = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        match = re.match(r"printer\s+(\S+)\s+(.+)$", line, re.I)
        if not match:
            continue
        name, status = match.groups()
        enabled = "disabled" not in status.lower()
        queues.append(PrinterQueue(name, enabled, status, name == default))
    return queues


def choose_preferred_queue(queues: list[PrinterQueue], preferred: str = "") -> str:
    names = {queue.name for queue in queues}
    if preferred and preferred in names:
        return preferred
    for queue in queues:
        if queue.is_default and queue.enabled:
            return queue.name
    for queue in queues:
        lowered = queue.name.lower()
        if queue.enabled and any(token in lowered for token in ("gosse-e10", "supvan", "e10")):
            return queue.name
    for queue in queues:
        if queue.enabled:
            return queue.name
    return queues[0].name if queues else (preferred.strip() or "gosse-e10")


def preflight_printer(queue: str) -> PrinterPreflight:
    queue = queue.strip()
    problems: list[str] = []
    if shutil.which("lp") is None:
        problems.append("CUPS command 'lp' is not installed.")
    if shutil.which("lpstat") is None:
        problems.append("CUPS command 'lpstat' is not installed.")
        return PrinterPreflight(False, queue, "CUPS client tools are unavailable", tuple(problems))
    queues = list_printer_queues()
    selected = next((candidate for candidate in queues if candidate.name == queue), None)
    if not queue:
        problems.append("No printer queue is selected.")
    elif selected is None:
        problems.append(f"CUPS queue '{queue}' does not exist.")
    elif not selected.enabled:
        problems.append(f"CUPS queue '{queue}' is disabled: {selected.status}")
    if problems:
        return PrinterPreflight(False, queue, "Printer needs attention", tuple(problems))
    return PrinterPreflight(True, queue, f"Queue '{queue}' is available", (selected.status,))


def _queue_exists(queue: str) -> bool:
    return any(candidate.name == queue for candidate in list_printer_queues())


def print_document(
    doc: LabelDocument,
    queue: str | None = None,
    copies: int = 1,
    job_name: str = "SUPVAN Label Studio",
) -> str:
    """Submit Label Studio's exact raster through the proven JPEG pass-through."""
    if shutil.which("lp") is None:
        raise PrintError("CUPS command 'lp' was not found")
    queue = (queue or doc.queue or "gosse-e10").strip()
    if not queue:
        raise PrintError("Printer queue is empty")
    if not _queue_exists(queue):
        raise PrintError(f"CUPS queue '{queue}' does not exist")
    copies = max(1, min(999, int(copies)))

    with tempfile.TemporaryDirectory(prefix="supvan-label-") as td:
        jpeg = Path(td) / "label-studio-exact.jpg"
        export_jpeg_exact(doc, jpeg)
        cmd = ["lp", "-d", queue, "-n", str(copies), "-t", job_name, str(jpeg)]
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
        if copies != 1:
            suffix += f"\nCopies requested: {copies}"
        return out + suffix
