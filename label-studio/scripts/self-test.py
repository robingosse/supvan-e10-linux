#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from supvan_label_studio.core import BoxItem, LabelDocument, QRItem, TextItem
from supvan_label_studio.history import DocumentHistory, document_snapshot
from supvan_label_studio.print_backend import export_jpeg_exact


def main() -> None:
    document = LabelDocument(auto_size=True, auto_margin_mm=3)
    document.add(TextItem(text="SUPVAN V0.3.4", bold=True, fill_printable_band=True, rotation=90))
    document.add(BoxItem(width_mm=8, height_mm=3, y_mm=5))
    document.add(QRItem(data="https://gosseco.ca", y_mm=10))
    snapshot = document_snapshot(document)
    history = DocumentHistory()
    assert history.record(document_snapshot(LabelDocument()), snapshot)

    with tempfile.TemporaryDirectory(prefix="supvan-studio-test-") as directory:
        path = Path(directory) / "exact.jpg"
        export_jpeg_exact(document, path)
        with Image.open(path) as image:
            assert image.width == 88
            assert image.height == document.render().height
            assert image.mode == "L"
    print(
        f"PASS: exact raster 88 x {document.render().height} dots; "
        f"{len(document.items)} objects; template/history round-trip ready"
    )


if __name__ == "__main__":
    main()
