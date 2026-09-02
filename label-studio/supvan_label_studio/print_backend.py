from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .core import LabelDocument
from .printer_profiles import PrinterProfile, profile_for_queue


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
    """Export the document raster with physical DPI metadata for CUPS."""
    path = Path(path)
    img = doc.render()
    dpi = max(25, int(round(doc.dots_per_mm * 25.4)))
    img.save(path, format="PNG", optimize=True, dpi=(dpi, dpi))
    return path


def export_jpeg_exact(doc: LabelDocument, path: str | Path) -> Path:
    """Export the exact-width grayscale JPEG used for CUPS pass-through.

    The Rust E10 service recognizes an 88-pixel-wide JPEG as an exact Label
    Studio raster.  Its pixel height is therefore the requested continuous-roll
    length in 8-dot/mm feed columns, instead of the nominal RFID media height.
    """
    path = Path(path)
    img = doc.render().convert("L")
    if img.width != doc.printable_width_dots:
        raise PrintError(f"internal raster width is {img.width}, expected {doc.printable_width_dots}")
    # Grayscale JPEG has no chroma subsampling.  Quality 100 keeps the already
    # pixel-aligned QR/text artwork effectively lossless for the driver's final
    # 1-bit dithering stage while preserving the proven image/jpeg CUPS path.
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
    profile: PrinterProfile | None = None,
) -> str:
    """Submit a label through the system CUPS spooler.

    The E10 validated profile keeps the proven exact-width JPEG pass-through.
    Other configured printers use a DPI-tagged PNG and optional CUPS media/options
    from their printer profile. Geometry remains explicit profile truth.
    """
    if shutil.which("lp") is None:
        raise PrintError("CUPS command 'lp' was not found")
    queue = (queue or doc.queue or "gosse-e10").strip()
    if not queue:
        raise PrintError("Printer queue is empty")
    if not _queue_exists(queue):
        raise PrintError(f"CUPS queue '{queue}' does not exist")
    copies = max(1, min(999, int(copies)))
    profile = profile or profile_for_queue(queue, doc.stock_width_mm)

    with tempfile.TemporaryDirectory(prefix="supvan-label-") as td:
        td_path = Path(td)
        if profile and profile.transport == "e10-exact-jpeg":
            artifact = td_path / "label-studio-exact.jpg"
            export_jpeg_exact(doc, artifact)
        else:
            artifact = td_path / "label-studio-raster.png"
            export_png(doc, artifact)

        cmd = ["lp", "-d", queue, "-n", str(copies), "-t", job_name]
        if profile:
            if profile.media:
                cmd.extend(["-o", f"media={profile.media}"])
            for option in profile.cups_options:
                cmd.extend(["-o", option])
        cmd.append(str(artifact))
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            details = (proc.stderr or proc.stdout or "unknown CUPS error").strip()
            raise PrintError(f"CUPS rejected the print job.\n\n{details}")

        out = (proc.stdout or "Print job submitted.").strip()
        m = re.search(r"request id is\s+(\S+)", out, flags=re.IGNORECASE)
        job_id = m.group(1) if m else None
        length_dots = doc.render().height
        length_mm = length_dots / doc.dots_per_mm
        profile_note = profile.name if profile else "unconfigured CUPS profile"
        suffix = (
            f"\nRaster: {doc.printable_width_dots} × {length_dots} dots "
            f"({doc.printable_width_mm:.3f} mm usable × {length_mm:g} mm long)."
            f"\nProfile: {profile_note}"
        )
        if profile and not profile.verified:
            suffix += " · GEOMETRY UNVERIFIED"
        if job_id:
            suffix += f"\nCUPS job: {job_id}"
        if copies != 1:
            suffix += f"\nCopies requested: {copies}"
        return out + suffix
