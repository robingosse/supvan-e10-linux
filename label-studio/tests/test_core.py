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
    # Full-width QR is 11 mm long in feed direction, plus 3 mm end margin.
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


def test_fill_printable_band_uses_document_raster_width():
    d = LabelDocument(length_mm=50, auto_size=False, printable_width_dots=96, dots_per_mm=8.0)
    item = TextItem(text="ONE\nTWO", size_mm=3.0, autofit_height=True, fill_printable_band=True)
    tile, _ = render_item_tile(item, d.dots_per_mm, d.printable_width_dots)
    assert tile.width == 96
    rotated, _ = render_item_tile(TextItem(text="ONE\nTWO", fill_printable_band=True, rotation=90), d.dots_per_mm, d.printable_width_dots)
    assert rotated.width == 96
    assert d.printable_width_mm == 12.0


def test_custom_printer_geometry_roundtrips():
    d = LabelDocument(
        length_mm=50, auto_size=False, printable_width_dots=144,
        dots_per_mm=12.0, printer_profile_key="custom-300dpi",
    )
    restored = LabelDocument.from_dict(d.to_dict())
    assert restored.printable_width_dots == 144
    assert restored.dots_per_mm == 12.0
    assert restored.printable_width_mm == 12.0
    assert restored.printer_profile_key == "custom-300dpi"


def test_continuous_text_90_uses_full_band_and_grows_along_tape():
    short = TextItem(text="SHORT", fill_printable_band=True, rotation=90)
    long = TextItem(text="THIS IS A MUCH LONGER MESSAGE", fill_printable_band=True, rotation=90)
    short_tile, _ = render_item_tile(short)
    long_tile, _ = render_item_tile(long)
    assert short_tile.width == PRINTABLE_WIDTH_DOTS
    assert long_tile.width == PRINTABLE_WIDTH_DOTS
    assert long_tile.height > short_tile.height


def test_continuous_multiline_shares_printable_band_instead_of_fixed_length():
    two_lines = TextItem(text="FIRST LINE\nSECOND LINE", fill_printable_band=True, rotation=90)
    three_lines = TextItem(text="FIRST LINE\nSECOND LINE\nTHIRD", fill_printable_band=True, rotation=90)
    two_tile, _ = render_item_tile(two_lines)
    three_tile, _ = render_item_tile(three_lines)
    assert two_tile.width == PRINTABLE_WIDTH_DOTS
    assert three_tile.width == PRINTABLE_WIDTH_DOTS
    # Both consume the same physical across-tape print band; feed length follows text.
    assert two_tile.height > 0
    assert three_tile.height > 0


def test_auto_length_increases_for_longer_continuous_message():
    short = LabelDocument(auto_size=True, auto_margin_mm=3.0)
    short.add(TextItem(text="BIN A", fill_printable_band=True, rotation=90, y_mm=3.0))
    long = LabelDocument(auto_size=True, auto_margin_mm=3.0)
    long.add(TextItem(text="BIN A — LONGER DESCRIPTION FOR THE DRAWER", fill_printable_band=True, rotation=90, y_mm=3.0))
    assert long.length_mm > short.length_mm
    assert short.stock_width_mm == 15.0
    assert long.stock_width_mm == 15.0


def test_standard_new_text_rotation_is_90_and_roundtrips():
    d = LabelDocument()
    assert d.default_text_rotation == 90
    restored = LabelDocument.from_dict(d.to_dict())
    assert restored.default_text_rotation == 90
