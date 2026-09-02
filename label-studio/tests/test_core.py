from pathlib import Path
import tempfile

from supvan_label_studio.core import (
    LabelDocument, TextItem, QRItem, BoxItem, LineItem, PRINTABLE_WIDTH_DOTS,
    PRINTABLE_WIDTH_MM, qr_safe_module_scale, render_item_tile, mm_to_dots
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
    d = LabelDocument(length_mm=73.125, queue="gosse-e10")
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
    assert d.length_mm == 34.0


def test_manual_length_does_not_auto_shrink():
    d = LabelDocument(length_mm=80, auto_size=False)
    d.add(TextItem(text="X", y_mm=2))
    assert d.length_mm == 80


def test_item_ids_remain_unique_after_delete_and_add():
    d = LabelDocument(auto_size=False)
    first = d.add(LineItem())
    second = d.add(LineItem())
    d.remove(first)
    third = d.add(LineItem())
    assert second.id != third.id
    assert len({item.id for item in d.items}) == len(d.items)


def test_layer_order_can_move_without_recreating_items():
    d = LabelDocument(auto_size=False)
    back = d.add(LineItem())
    front = d.add(BoxItem())
    assert d.move_layer(back, 1) == 1
    assert d.items == [front, back]
    assert d.move_layer(back, 99) == 1


def test_align_across_printable_band():
    d = LabelDocument(auto_size=False)
    item = d.add(BoxItem(width_mm=5.0, height_mm=3.0))
    assert d.align_across(item, "start") == 0.0
    assert d.align_across(item, "center") == 3.0
    assert d.align_across(item, "end") == 6.0


def test_content_bounds_reports_combined_extent():
    d = LabelDocument(auto_size=False)
    d.add(BoxItem(x_mm=1, y_mm=2, width_mm=4, height_mm=3))
    d.add(BoxItem(x_mm=2, y_mm=10, width_mm=5, height_mm=2))
    assert d.content_bounds_mm() == (1, 2, 6, 10)


def test_text_autofit_keeps_multiline_within_requested_height():
    item = TextItem(text="ONE\nTWO\nTHREE", size_mm=6.0, autofit_height=True)
    tile, _ = render_item_tile(item)
    assert tile.height == mm_to_dots(6.0)


def test_text_manual_multiline_can_exceed_single_line_height():
    manual = TextItem(text="ONE\nTWO", size_mm=4.0, autofit_height=False)
    fitted = TextItem(text="ONE\nTWO", size_mm=4.0, autofit_height=True)
    manual_tile, _ = render_item_tile(manual)
    fitted_tile, _ = render_item_tile(fitted)
    assert fitted_tile.height == mm_to_dots(4.0)
    assert manual_tile.height > fitted_tile.height
