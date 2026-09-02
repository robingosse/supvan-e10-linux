import json
from pathlib import Path

from supvan_label_studio.core import LabelDocument, TextItem
from supvan_label_studio.workbench_bridge import (
    REQUEST_FORMAT,
    RESULT_FORMAT,
    TEMPLATE_FORMAT,
    document_to_workbench_template,
    load_workbench_session,
)


def test_workbench_template_export_contains_autofit():
    doc = LabelDocument(length_mm=50, auto_size=False)
    doc.add(TextItem(text="ONE\nTWO", size_mm=6, autofit_height=True, bold=True))
    layout, unsupported = document_to_workbench_template(doc)
    assert unsupported == []
    assert layout["format"] == TEMPLATE_FORMAT
    text = layout["elements"][0]
    assert text["kind"] == "text"
    assert text["source"] == "ONE\nTWO"
    assert text["max_lines"] == 2
    assert text["autofit_height"] is True
    assert text["fill_printable_band"] is False


def test_workbench_request_result_roundtrip(tmp_path: Path):
    result = tmp_path / "result.json"
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "format": REQUEST_FORMAT,
        "job_id": "job-42",
        "result_path": str(result),
        "length_mm": 50,
        "context": {"serial": "GC-00042"},
    }))
    session = load_workbench_session(request)
    session.document.add(TextItem(text="{{serial}}", autofit_height=True))
    session.write_result(session.document)
    payload = json.loads(result.read_text())
    assert payload["format"] == RESULT_FORMAT
    assert payload["job_id"] == "job-42"
    assert payload["context"]["serial"] == "GC-00042"
    assert payload["workbench_template"]["format"] == TEMPLATE_FORMAT
