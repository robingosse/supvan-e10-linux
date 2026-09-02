from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

E10_PROFILE_KEY = "supvan-e10-linux-validated"
E10_PRINTABLE_WIDTH_DOTS = 88
E10_DOTS_PER_MM = 8.0
E10_NOMINAL_DPI = 203


@dataclass
class PrinterProfile:
    key: str
    name: str
    queue: str
    printable_width_dots: int
    dots_per_mm: float
    nominal_stock_width_mm: float = 15.0
    nominal_dpi: int = 203
    transport: str = "cups-image"
    media: str = ""
    cups_options: list[str] = field(default_factory=list)
    verified: bool = False
    built_in: bool = False

    def validate(self) -> None:
        self.key = str(self.key or "custom").strip()
        self.name = str(self.name or self.key).strip()
        self.queue = str(self.queue or "").strip()
        self.printable_width_dots = max(8, int(self.printable_width_dots))
        self.dots_per_mm = max(1.0, float(self.dots_per_mm))
        self.nominal_stock_width_mm = max(1.0, min(500.0, float(self.nominal_stock_width_mm)))
        self.nominal_dpi = max(25, min(4800, int(self.nominal_dpi)))
        self.transport = str(self.transport or "cups-image")
        self.media = str(self.media or "").strip()
        self.cups_options = [str(v).strip() for v in self.cups_options if str(v).strip()]
        self.verified = bool(self.verified)
        self.built_in = bool(self.built_in)

    @property
    def printable_width_mm(self) -> float:
        return self.printable_width_dots / self.dots_per_mm

    @property
    def summary(self) -> str:
        truth = "validated" if self.verified else "unverified"
        return (
            f"{self.name} · {self.printable_width_mm:.3f} mm usable · "
            f"{self.printable_width_dots} dots · {self.nominal_dpi} dpi · {truth}"
        )


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "supvan-label-studio" / "printer-profiles.json"


def _looks_like_e10(queue: str) -> bool:
    q = str(queue or "").strip().lower()
    return bool(re.search(r"(^|[-_.])e10($|[-_.])", q)) or q in {"gosse-e10", "supvan-e10"}


def e10_profile(queue: str = "gosse-e10", stock_width_mm: float = 15.0) -> PrinterProfile:
    return PrinterProfile(
        key=E10_PROFILE_KEY,
        name="SUPVAN E10 · validated Linux raster",
        queue=queue or "gosse-e10",
        printable_width_dots=E10_PRINTABLE_WIDTH_DOTS,
        dots_per_mm=E10_DOTS_PER_MM,
        nominal_stock_width_mm=15.0,
        nominal_dpi=E10_NOMINAL_DPI,
        transport="e10-exact-jpeg",
        verified=True,
        built_in=True,
    )


def load_profiles(path: Path | None = None) -> dict[str, PrinterProfile]:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    profiles: dict[str, PrinterProfile] = {}
    for queue, data in (raw.get("queues", {}) if isinstance(raw, dict) else {}).items():
        if not isinstance(data, dict):
            continue
        try:
            profile = PrinterProfile(**{k: v for k, v in data.items() if k in PrinterProfile.__dataclass_fields__})
            profile.queue = str(queue)
            profile.validate()
        except (TypeError, ValueError):
            continue
        profiles[profile.queue] = profile
    return profiles


def save_profile(profile: PrinterProfile, path: Path | None = None) -> Path:
    path = path or config_path()
    profile.validate()
    profiles = load_profiles(path)
    profiles[profile.queue] = profile
    payload = {"version": 1, "queues": {}}
    for queue, item in sorted(profiles.items()):
        data = asdict(item)
        data.pop("built_in", None)
        payload["queues"][queue] = data
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def profile_for_queue(queue: str, stock_width_mm: float = 15.0, path: Path | None = None) -> PrinterProfile | None:
    queue = str(queue or "").strip()
    configured = load_profiles(path).get(queue)
    if configured:
        return configured
    if _looks_like_e10(queue):
        return e10_profile(queue)
    return None


def apply_profile_to_document(doc, profile: PrinterProfile) -> None:
    profile.validate()
    doc.printable_width_dots = profile.printable_width_dots
    doc.dots_per_mm = profile.dots_per_mm
    doc.printer_profile_key = profile.key
    if profile.nominal_stock_width_mm > 0:
        doc.stock_width_mm = profile.nominal_stock_width_mm
    doc.validate()
    for item in doc.items:
        doc.clamp_item(item, allow_length_extend=doc.auto_size)


def list_cups_options(queue: str) -> dict[str, dict]:
    """Parse `lpoptions -p QUEUE -l` into a small capability dictionary.

    CUPS/PPD option lists are advisory. They commonly expose resolution and
    media choices, but they do not reliably expose physical unprintable margins,
    so Studio never fabricates printable width from these values.
    """
    if not queue or shutil.which("lpoptions") is None:
        return {}
    proc = subprocess.run(["lpoptions", "-p", queue, "-l"], text=True, capture_output=True)
    if proc.returncode != 0:
        return {}
    options: dict[str, dict] = {}
    for raw in proc.stdout.splitlines():
        match = re.match(r"([^/\s]+)/([^:]+):\s*(.*)$", raw.strip())
        if not match:
            continue
        key, description, choices_text = match.groups()
        choices = []
        default = ""
        for choice in choices_text.split():
            if choice.startswith("*"):
                choice = choice[1:]
                default = choice
            choices.append(choice)
        options[key] = {"description": description.strip(), "choices": choices, "default": default}
    return options


def detected_resolution_dpi(queue: str) -> int | None:
    options = list_cups_options(queue)
    for key in ("Resolution", "printer-resolution", "PrintQuality"):
        data = options.get(key)
        if not data:
            continue
        values = [data.get("default", "")] + list(data.get("choices") or [])
        for value in values:
            match = re.search(r"(\d{2,4})(?:x\d{2,4})?\s*dpi", str(value), re.I)
            if match:
                return int(match.group(1))
    return None


def detected_media_choices(queue: str) -> tuple[list[str], str]:
    options = list_cups_options(queue)
    for key in ("PageSize", "media", "MediaSize"):
        data = options.get(key)
        if data:
            return list(data.get("choices") or []), str(data.get("default") or "")
    return [], ""
