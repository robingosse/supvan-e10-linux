from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppPreferences:
    queue: str = "gosse-e10"
    stock_width_mm: float = 15.0
    zoom_percent: int = 100
    copies: int = 1
    last_open_directory: str = ""
    last_export_directory: str = ""

    def validate(self) -> None:
        self.queue = str(self.queue).strip() or "gosse-e10"
        self.stock_width_mm = 12.0 if float(self.stock_width_mm) == 12.0 else 15.0
        self.zoom_percent = max(25, min(400, int(self.zoom_percent)))
        self.copies = max(1, min(999, int(self.copies)))


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "supvan-label-studio" / "preferences.json"


def load_preferences(path: Path | None = None) -> AppPreferences:
    path = path or config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        prefs = AppPreferences(**{k: v for k, v in data.items() if k in AppPreferences.__dataclass_fields__})
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        prefs = AppPreferences()
    prefs.validate()
    return prefs


def save_preferences(preferences: AppPreferences, path: Path | None = None) -> Path:
    path = path or config_path()
    preferences.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(preferences), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
