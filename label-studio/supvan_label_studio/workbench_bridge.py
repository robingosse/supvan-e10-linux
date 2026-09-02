from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import (
    BoxItem,
    LabelDocument,
    LineItem,
    QRItem,
    TextItem,
)

REQUEST_FORMAT = "WORKBENCH-SUPVAN-STUDIO-1"
RESULT_FORMAT = "WORKBENCH-SUPVAN-STUDIO-RESULT-1"
TEMPLATE_FORMAT = "GOSSIE-LABEL-TEMPLATE-1"


def _norm(value: float, total: float) -> int:
    if total <= 0:
        return 0
    return max(0, min(1000, int(round(value * 1000.0 / total))))


def document_to_workbench_template(document: LabelDocument) -> tuple[dict[str, Any], list[str]]:
    """Export Studio geometry into Workbench's normalized template contract.

    Studio keeps the selected printer profile's native raster axis internally and displays it rotated.
    Workbench stores design coordinates left-to-right along the label and top-to-bottom
    across the printable band. The conversion here keeps that transformation in one
    integration module rather than leaking it into either application's business logic.
    """
    elements: list[dict[str, Any]] = []
    unsupported: list[str] = []
    for item in document.items:
        x_mm, y_mm, width_mm, height_mm = document.item_bounds_mm(item)
        element = {
            "x": _norm(y_mm, document.length_mm),
            "y": _norm(document.printable_width_mm - (x_mm + width_mm), document.printable_width_mm),
            "w": max(1, _norm(height_mm, document.length_mm)),
            "h": max(1, _norm(width_mm, document.printable_width_mm)),
        }
        if isinstance(item, TextItem):
            lines = max(1, (item.text or "").count("\n") + 1)
            element.update(
                {
                    "kind": "text",
                    "source": item.text,
                    "font_permille": max(25, min(500, _norm(item.size_mm, document.printable_width_mm))),
                    "bold": bool(item.bold),
                    "italic": False,
                    "underline": False,
                    "uppercase": False,
                    "align": "left",
                    "max_lines": lines,
                    "autofit_height": bool(item.autofit_height),
                    "fill_printable_band": bool(item.fill_printable_band),
                }
            )
        elif isinstance(item, QRItem):
            element.update(
                {
                    "kind": "qr",
                    "source": item.data,
                    "ecc": item.ecc,
                    "border_modules": item.border_modules,
                }
            )
        elif isinstance(item, LineItem):
            element.update({"kind": "line"})
        elif isinstance(item, BoxItem):
            unsupported.append(f"{item.id or 'box'}: Workbench template v1 has no box element")
            continue
        else:
            unsupported.append(f"{item.id or item.kind}: {item.kind} is not supported by Workbench template v1")
            continue
        elements.append(element)
    return {"format": TEMPLATE_FORMAT, "elements": elements}, unsupported


@dataclass
class WorkbenchSession:
    request_path: Path
    result_path: Path
    document: LabelDocument
    document_path: Path | None = None
    job_id: str = ""
    context: dict[str, Any] | None = None

    def write_result(self, document: LabelDocument, *, current_path: Path | None = None) -> Path:
        layout, unsupported = document_to_workbench_template(document)
        payload = {
            "format": RESULT_FORMAT,
            "job_id": self.job_id,
            "status": "completed",
            "document": document.to_dict(),
            "document_path": str(current_path) if current_path else None,
            "workbench_template": layout,
            "unsupported_items": unsupported,
            "context": self.context or {},
        }
        self.result_path.parent.mkdir(parents=True, exist_ok=True)
        self.result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return self.result_path


def load_workbench_session(path: str | Path) -> WorkbenchSession:
    request_path = Path(path).expanduser().resolve()
    data = json.loads(request_path.read_text())
    if data.get("format") != REQUEST_FORMAT:
        raise ValueError(f"Unsupported Workbench request format: {data.get('format')!r}")

    raw_document = data.get("document")
    document_path = data.get("document_path")
    if isinstance(raw_document, dict):
        document = LabelDocument.from_dict(raw_document)
    elif document_path:
        document = LabelDocument.load(Path(document_path).expanduser())
    else:
        document = LabelDocument(
            length_mm=float(data.get("length_mm", 50.0)),
            stock_width_mm=float(data.get("stock_width_mm", 15.0)),
            queue=str(data.get("queue") or "gosse-e10"),
            auto_size=bool(data.get("auto_size", True)),
        )

    result_value = data.get("result_path") or request_path.with_suffix(".result.json")
    result_path = Path(result_value)
    if not result_path.is_absolute():
        result_path = request_path.parent / result_path

    return WorkbenchSession(
        request_path=request_path,
        result_path=result_path.expanduser().resolve(),
        document=document,
        document_path=Path(document_path).expanduser().resolve() if document_path else None,
        job_id=str(data.get("job_id") or ""),
        context=data.get("context") if isinstance(data.get("context"), dict) else {},
    )
