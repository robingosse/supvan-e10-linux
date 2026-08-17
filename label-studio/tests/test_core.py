from pathlib import Path
import tempfile

from supvan_label_studio.core import (
    LabelDocument, TextItem, QRItem, BoxItem, PRINTABLE_WIDTH_DOTS,
    PRINTABLE_WIDTH_MM, qr_safe_module_scale
)


def test_blank_geometry():
    d = LabelDocument(length_mm=50)
    img = d.render()
    assert img.size == (88, 400)


def test_arbitrary_length_1m():
    d = LabelDocument(length_mm=1000)
    assert d.render().size == (88, 8000)


def test_max_roll_length():
    d = LabelDocument(length_mm=6000)
    assert d.render().size == (88, 48000)


def test_qr_full_width_tile():
    d = LabelDocument(length_mm=50)
    q = d.add(QRItem(data="https://gosseco.ca", full_width=True))
    x, y, w, h = d.item_bounds_mm(q)
    assert round(w, 3) == 11.0
    assert round(h, 3) == 11.0
    img = d.render()
    assert img.getextrema()[0] == 0


def test_qr_safe_scale():
    modules, scale = qr_safe_module_scale("HELLO")
    assert modules > 0
    assert scale >= 1


def test_roundtrip_json():
    d = LabelDocument(length_mm=73.125, queue="SUPVAN_E10")
    d.add(TextItem(text="BIN A-17", y_mm=2))
    d.add(BoxItem(width_mm=5, height_mm=3, y_mm=10))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.supvanlabel"
        d.save(p)
        r = LabelDocument.load(p)
        assert r.length_mm == d.length_mm
        assert len(r.items) == 2
        assert r.items[0].kind == "text"


def test_auto_size_tracks_content_and_margin():
    d = LabelDocument(length_mm=50, auto_size=True, auto_margin_mm=3)
    q = QRItem(data="HELLO", y_mm=20)
    d.add(q)
    # Full-width QR is 11 mm long in feed direction, plus 3 mm end margin.
    assert d.length_mm == 34.0


def test_manual_length_does_not_auto_shrink():
    d = LabelDocument(length_mm=80, auto_size=False)
    d.add(TextItem(text="X", y_mm=2))
    assert d.length_mm == 80
