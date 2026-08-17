from __future__ import annotations

import io
import math
import os
import sys
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk
except Exception as e:  # pragma: no cover
    print(
        "SUPVAN Label Studio requires GTK 3 Python bindings.\n"
        "Install: sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo",
        file=sys.stderr,
    )
    raise

from PIL import Image

from .core import (
    LabelDocument,
    TextItem,
    QRItem,
    BoxItem,
    LineItem,
    ImageItem,
    PRINTABLE_WIDTH_MM,
    ONE_DOT_MM,
    MAX_LENGTH_MM,
    image_item_from_file,
    qr_safe_module_scale,
)
from .print_backend import PrintError, detect_default_queue, export_png, print_document

APP_TITLE = "SUPVAN E10 Label Studio v0.2.1 (Unofficial)"
PREVIEW_PX_PER_MM = 28.0


def pil_to_pixbuf(img: Image.Image) -> GdkPixbuf.Pixbuf:
    rgba = img.convert("RGBA")
    data = rgba.tobytes()
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(data),
        GdkPixbuf.Colorspace.RGB,
        True,
        8,
        rgba.width,
        rgba.height,
        rgba.width * 4,
    )


class LabelCanvas(Gtk.DrawingArea):
    def __init__(self, owner: "MainWindow"):
        super().__init__()
        self.owner = owner
        self.doc = owner.doc
        self.selected = None
        self.dragging = False
        self.drag_dx = 0.0
        self.drag_dy = 0.0
        self.zoom = 1.0
        self.preview_cache = None
        self.set_can_focus(True)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("key-press-event", self.on_key)
        self.refresh_size()

    @property
    def pxmm(self) -> float:
        return PREVIEW_PX_PER_MM * self.zoom

    def printable_top_px(self) -> float:
        return (self.doc.stock_width_mm - PRINTABLE_WIDTH_MM) / 2.0 * self.pxmm

    def refresh_size(self):
        # Editor is intentionally rotated 90 degrees: tape feeds left-to-right.
        width = int(math.ceil(self.doc.length_mm * self.pxmm)) + 2
        height = int(math.ceil(self.doc.stock_width_mm * self.pxmm)) + 2
        self.set_size_request(max(180, width), max(120, height))
        self.invalidate_render()

    def invalidate_render(self):
        self.preview_cache = None
        self.queue_draw()

    def to_doc_mm(self, x: float, y: float) -> tuple[float, float]:
        # Inverse of the 90-degree CCW preview rotation.  Document x is
        # across the tape; document y is the feed/length axis.
        along_mm = x / self.pxmm
        across_from_top = (y - self.printable_top_px()) / self.pxmm
        across_mm = PRINTABLE_WIDTH_MM - across_from_top
        return across_mm, along_mm

    def on_draw(self, widget, cr):
        pxmm = self.pxmm
        stock_w = self.doc.length_mm * pxmm
        stock_h = self.doc.stock_width_mm * pxmm
        top = self.printable_top_px()
        printable_h = PRINTABLE_WIDTH_MM * pxmm

        # Horizontal tape strip, with the verified 11 mm printable band centered.
        cr.set_source_rgb(0.97, 0.97, 0.97)
        cr.rectangle(0, 0, stock_w, stock_h)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, top, stock_w, printable_h)
        cr.fill()
        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, max(1, stock_w - 1), max(1, stock_h - 1))
        cr.stroke()
        cr.set_dash([4.0, 4.0])
        cr.move_to(0, top)
        cr.line_to(stock_w, top)
        cr.move_to(0, top + printable_h)
        cr.line_to(stock_w, top + printable_h)
        cr.stroke()
        cr.set_dash([])

        # Core raster stays physically correct (88 dots across × N dots long).
        # Only the editor view is rotated so the roll runs left-to-right.
        if self.preview_cache is None:
            try:
                img = self.doc.render().transpose(Image.Transpose.ROTATE_90)
                self.preview_cache = pil_to_pixbuf(img)
            except Exception as e:
                self.owner.show_error("Render error", str(e))
                return False
        pix = self.preview_cache
        target_w = max(1, int(round(stock_w)))
        target_h = max(1, int(round(printable_h)))
        scaled = pix.scale_simple(target_w, target_h, GdkPixbuf.InterpType.NEAREST)
        Gdk.cairo_set_source_pixbuf(cr, scaled, 0, top)
        cr.paint()

        if self.selected is not None and self.selected in self.doc.items:
            x, y, w, h = self.doc.item_bounds_mm(self.selected)
            # 90-degree CCW transform of the item's document-space bounds.
            sx = y * pxmm
            sy = top + (PRINTABLE_WIDTH_MM - (x + w)) * pxmm
            sw = h * pxmm
            sh = w * pxmm
            cr.set_source_rgb(0.1, 0.45, 0.9)
            cr.set_line_width(1.5)
            cr.set_dash([5.0, 3.0])
            cr.rectangle(sx - 2, sy - 2, sw + 4, sh + 4)
            cr.stroke()
            cr.set_dash([])
        return False

    def on_press(self, widget, event):
        self.grab_focus()
        if event.button != 1:
            return False
        x_mm, y_mm = self.to_doc_mm(event.x, event.y)
        if 0 <= x_mm <= PRINTABLE_WIDTH_MM and 0 <= y_mm <= self.doc.length_mm:
            item = self.doc.hit_test(x_mm, y_mm)
        else:
            item = None
        self.selected = item
        self.owner.update_status()
        if item is not None:
            self.dragging = True
            self.drag_dx = x_mm - item.x_mm
            self.drag_dy = y_mm - item.y_mm
        self.queue_draw()
        return True

    def on_release(self, widget, event):
        if event.button == 1:
            self.dragging = False
            if self.doc.auto_size:
                self.owner.apply_auto_size(shrink=True)
        return True

    def on_motion(self, widget, event):
        if not self.dragging or self.selected is None:
            return False
        x_mm, y_mm = self.to_doc_mm(event.x, event.y)
        self.selected.x_mm = x_mm - self.drag_dx
        self.selected.y_mm = y_mm - self.drag_dy
        self.doc.clamp_item(self.selected, allow_length_extend=True)
        if self.doc.auto_size:
            old_len = self.doc.length_mm
            self.doc.ensure_auto_length_for(self.selected)
            if self.doc.length_mm != old_len:
                self.owner.sync_length_controls()
                self.refresh_size()
            else:
                self.invalidate_render()
        else:
            self.invalidate_render()
        self.owner.update_status()
        return True

    def on_key(self, widget, event):
        if self.selected is None:
            return False
        step = 1.0 if (event.state & Gdk.ModifierType.SHIFT_MASK) else ONE_DOT_MM
        changed = True
        if event.keyval == Gdk.KEY_Left:
            self.selected.y_mm -= step
        elif event.keyval == Gdk.KEY_Right:
            self.selected.y_mm += step
        elif event.keyval == Gdk.KEY_Up:
            self.selected.x_mm += step
        elif event.keyval == Gdk.KEY_Down:
            self.selected.x_mm -= step
        elif event.keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self.owner.delete_selected()
            return True
        else:
            changed = False
        if changed:
            self.doc.clamp_item(self.selected, allow_length_extend=True)
            if self.doc.auto_size:
                self.owner.apply_auto_size(shrink=False)
            self.invalidate_render()
            self.owner.update_status()
            return True
        return False


class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE)
        self.set_default_size(1060, 760)
        self.set_border_width(8)
        self.doc = LabelDocument()
        self.current_path: Path | None = None
        self.connect("delete-event", lambda *_: Gtk.main_quit())

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(root)

        root.pack_start(self.make_toolbar(), False, False, 0)
        root.pack_start(self.make_settings_bar(), False, False, 0)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.canvas = LabelCanvas(self)
        self.scroller.add(self.canvas)
        root.pack_start(self.scroller, True, True, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.set_selectable(True)
        root.pack_start(self.status, False, False, 0)
        self.refresh_printer_queue(quiet=True)
        self.update_status()
        self.show_all()

    def button(self, label, cb, tooltip=None):
        b = Gtk.Button(label=label)
        b.connect("clicked", cb)
        if tooltip:
            b.set_tooltip_text(tooltip)
        return b

    def make_toolbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for label, cb, tip in [
            ("New", self.new_doc, "New label"),
            ("Open", self.open_doc, "Open .supvanlabel template"),
            ("Save", self.save_doc, "Save template"),
            ("Add Text", self.add_text, "Add movable text"),
            ("Generate QR Code", self.add_qr, "Generate a scan-safe full-width movable QR code"),
            ("Add Image", self.add_image, "Import PNG/JPEG/SVG-rasterized image"),
            ("Box", self.add_box, "Add rectangle"),
            ("Line", self.add_line, "Add horizontal line"),
            ("Edit Selected", self.edit_selected, "Edit the selected object"),
            ("Rotate 90°", self.rotate_selected, "Rotate selected object clockwise"),
            ("Duplicate", self.duplicate_selected, "Duplicate selected object"),
            ("Delete", self.delete_selected, "Delete selected object"),
            ("Export PNG", self.export_png_clicked, "Export exact 88-dot print raster"),
            ("PRINT", self.print_clicked, "Submit to CUPS"),
        ]:
            bar.pack_start(self.button(label, cb, tip), False, False, 0)
        return bar

    def make_settings_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.pack_start(Gtk.Label(label="Stock:"), False, False, 0)
        self.stock_combo = Gtk.ComboBoxText()
        self.stock_combo.append_text("15 mm")
        self.stock_combo.append_text("12 mm")
        self.stock_combo.set_active(0)
        self.stock_combo.connect("changed", self.stock_changed)
        bar.pack_start(self.stock_combo, False, False, 0)

        self.auto_check = Gtk.CheckButton(label="Auto-size length")
        self.auto_check.set_active(self.doc.auto_size)
        self.auto_check.set_tooltip_text("Grow/shrink the strip to fit content plus the end margin")
        self.auto_check.connect("toggled", self.auto_size_changed)
        bar.pack_start(self.auto_check, False, False, 0)

        bar.pack_start(Gtk.Label(label="Length (mm):"), False, False, 0)
        adj = Gtk.Adjustment(self.doc.length_mm, 5.0, MAX_LENGTH_MM, ONE_DOT_MM, 1.0, 0)
        self.length_spin = Gtk.SpinButton(adjustment=adj, climb_rate=1.0, digits=3)
        self.length_spin.set_numeric(True)
        self.length_spin.connect("value-changed", self.length_changed)
        self.length_spin.set_sensitive(not self.doc.auto_size)
        bar.pack_start(self.length_spin, False, False, 0)

        bar.pack_start(Gtk.Label(label="End margin:"), False, False, 0)
        marg_adj = Gtk.Adjustment(self.doc.auto_margin_mm, 0.0, 100.0, ONE_DOT_MM, 1.0, 0)
        self.margin_spin = Gtk.SpinButton(adjustment=marg_adj, climb_rate=1.0, digits=3)
        self.margin_spin.set_numeric(True)
        self.margin_spin.connect("value-changed", self.margin_changed)
        bar.pack_start(self.margin_spin, False, False, 0)

        bar.pack_start(self.button("Fit Now", self.fit_contents), False, False, 0)

        bar.pack_start(Gtk.Label(label="Queue:"), False, False, 0)
        self.queue_entry = Gtk.Entry()
        self.queue_entry.set_text(self.doc.queue)
        self.queue_entry.set_width_chars(15)
        self.queue_entry.connect("changed", lambda w: setattr(self.doc, "queue", w.get_text().strip()))
        bar.pack_start(self.queue_entry, False, False, 0)
        bar.pack_start(self.button("Refresh", self.refresh_printer_queue, "Detect CUPS printer queues"), False, False, 0)

        bar.pack_start(Gtk.Label(label="Zoom:"), False, False, 0)
        self.zoom_combo = Gtk.ComboBoxText()
        for z in ("50%", "75%", "100%", "150%", "200%"):
            self.zoom_combo.append_text(z)
        self.zoom_combo.set_active(2)
        self.zoom_combo.connect("changed", self.zoom_changed)
        bar.pack_start(self.zoom_combo, False, False, 0)

        hint = Gtk.Label(label="Tape runs left → right. Printable band: 11 mm / 88 dots. Arrow keys = 1 dot; Shift+Arrow = 1 mm.")
        hint.set_xalign(0)
        bar.pack_start(hint, True, True, 8)
        return bar

    def refresh_printer_queue(self, *_args, quiet: bool = False):
        current = self.queue_entry.get_text().strip() if hasattr(self, "queue_entry") else self.doc.queue
        detected = detect_default_queue(current or None)
        if detected:
            self.doc.queue = detected
            self.queue_entry.set_text(detected)
            if not quiet:
                self.show_info("Printer detected", f"Using CUPS queue: {detected}")
        elif not quiet:
            self.show_error(
                "No printer queue found",
                "No CUPS printer queue is currently available. Start/pair the E10 driver, then click Refresh again.",
            )
        return False

    def show_error(self, title: str, message: str):
        d = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        d.format_secondary_text(message)
        d.run()
        d.destroy()

    def show_info(self, title: str, message: str):
        d = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        d.format_secondary_text(message)
        d.run()
        d.destroy()

    def text_dialog(self, title, fields):
        d = Gtk.Dialog(title=title, transient_for=self, flags=0)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        widgets = {}
        for row, (name, label, kind, default) in enumerate(fields):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            if kind == "entry":
                w = Gtk.Entry(); w.set_text(str(default))
            elif kind == "multiline":
                w = Gtk.TextView(); w.set_wrap_mode(Gtk.WrapMode.WORD_CHAR); w.set_size_request(420, 100)
                w.get_buffer().set_text(str(default))
            elif kind == "spin":
                w = Gtk.SpinButton.new_with_range(0.5, 20.0, 0.125); w.set_digits(3); w.set_value(float(default))
            elif kind == "check":
                w = Gtk.CheckButton(); w.set_active(bool(default))
            elif kind == "combo":
                options, active = default
                w = Gtk.ComboBoxText()
                for o in options: w.append_text(o)
                w.set_active(options.index(active) if active in options else 0)
            else:
                raise ValueError(kind)
            grid.attach(w, 1, row, 1, 1)
            widgets[name] = (kind, w)
        d.get_content_area().add(grid)
        d.show_all()
        resp = d.run()
        result = None
        if resp == Gtk.ResponseType.OK:
            result = {}
            for name, (kind, w) in widgets.items():
                if kind == "entry": result[name] = w.get_text()
                elif kind == "multiline":
                    b = w.get_buffer(); result[name] = b.get_text(b.get_start_iter(), b.get_end_iter(), True)
                elif kind == "spin": result[name] = w.get_value()
                elif kind == "check": result[name] = w.get_active()
                elif kind == "combo": result[name] = w.get_active_text()
        d.destroy()
        return result

    def sync_length_controls(self):
        if hasattr(self, "length_spin"):
            self.length_spin.set_value(self.doc.length_mm)
            self.length_spin.set_sensitive(not self.doc.auto_size)
        if hasattr(self, "auto_check") and self.auto_check.get_active() != self.doc.auto_size:
            self.auto_check.set_active(self.doc.auto_size)
        if hasattr(self, "margin_spin"):
            self.margin_spin.set_value(self.doc.auto_margin_mm)

    def apply_auto_size(self, shrink=True):
        if not self.doc.auto_size:
            return
        if shrink:
            self.doc.auto_length(self.doc.auto_margin_mm, 10.0)
        elif self.canvas.selected is not None:
            self.doc.ensure_auto_length_for(self.canvas.selected)
        self.sync_length_controls()
        self.canvas.refresh_size()
        self.update_status()

    def auto_size_changed(self, w):
        self.doc.auto_size = bool(w.get_active())
        self.length_spin.set_sensitive(not self.doc.auto_size)
        if self.doc.auto_size:
            self.apply_auto_size(shrink=True)
        else:
            self.canvas.refresh_size()
            self.update_status()

    def margin_changed(self, w):
        self.doc.auto_margin_mm = float(w.get_value())
        self.doc.validate()
        if self.doc.auto_size:
            self.apply_auto_size(shrink=True)

    def next_y(self, height_mm=4.0):
        if not self.doc.items:
            return 1.0
        bottom = max(
            (self.doc.item_bounds_mm(i)[1] + self.doc.item_bounds_mm(i)[3] for i in self.doc.items),
            default=0,
        )
        if self.doc.auto_size:
            return min(max(0.0, bottom + 1.0), max(0.0, MAX_LENGTH_MM - height_mm))
        return min(max(0.0, bottom + 1.0), max(0.0, self.doc.length_mm - height_mm))

    def add_text(self, *_):
        r = self.text_dialog("Add Text", [
            ("text", "Text", "multiline", "Label text"),
            ("size", "Height (mm)", "spin", 3.0),
            ("family", "Font family", "entry", "DejaVu Sans"),
            ("bold", "Bold", "check", False),
        ])
        if not r: return
        item = TextItem(text=r["text"], size_mm=r["size"], family=r["family"], bold=r["bold"], y_mm=self.next_y(4))
        self.doc.add(item); self.canvas.selected = item; self.sync_length_controls(); self.canvas.refresh_size(); self.update_status()

    def add_qr(self, *_):
        r = self.text_dialog("Generate QR Code", [
            ("data", "Text / URL / data", "multiline", "https://"),
            ("ecc", "Error correction", "combo", (["L", "M", "Q", "H"], "M")),
        ])
        if not r: return
        try:
            modules, scale = qr_safe_module_scale(r["data"], r["ecc"])
            if scale < 1:
                raise ValueError("QR payload is too long for the E10 printable width.")
            if scale == 1:
                self.show_info(
                    "Dense QR warning",
                    f"This QR is {modules} modules wide and will print at 1 dot per module. It may be difficult to scan at 203 dpi. Shorter data is strongly recommended.",
                )
            item = QRItem(data=r["data"], ecc=r["ecc"], full_width=True, y_mm=self.next_y(PRINTABLE_WIDTH_MM))
            self.doc.add(item); self.canvas.selected = item; self.sync_length_controls(); self.canvas.refresh_size(); self.update_status()
        except Exception as e:
            self.show_error("Could not generate QR code", str(e))

    def add_image(self, *_):
        d = Gtk.FileChooserDialog("Import Image", self, Gtk.FileChooserAction.OPEN, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        filt = Gtk.FileFilter(); filt.set_name("Images"); filt.add_pixbuf_formats(); d.add_filter(filt)
        resp = d.run(); path = d.get_filename() if resp == Gtk.ResponseType.OK else None; d.destroy()
        if not path: return
        try:
            item = image_item_from_file(path); item.y_mm = self.next_y(item.height_mm)
            self.doc.add(item); self.canvas.selected = item; self.sync_length_controls(); self.canvas.refresh_size(); self.update_status()
        except Exception as e:
            self.show_error("Could not import image", str(e))

    def add_box(self, *_):
        item = BoxItem(width_mm=8.0, height_mm=4.0, y_mm=self.next_y(4.0)); self.doc.add(item)
        self.canvas.selected = item; self.sync_length_controls(); self.canvas.refresh_size(); self.update_status()

    def add_line(self, *_):
        item = LineItem(width_mm=PRINTABLE_WIDTH_MM, y_mm=self.next_y(1.0)); self.doc.add(item)
        self.canvas.selected = item; self.sync_length_controls(); self.canvas.refresh_size(); self.update_status()

    def edit_selected(self, *_):
        item = self.canvas.selected
        if item is None:
            return
        try:
            if isinstance(item, TextItem):
                r = self.text_dialog("Edit Text", [
                    ("text", "Text", "multiline", item.text),
                    ("size", "Height (mm)", "spin", item.size_mm),
                    ("family", "Font family", "entry", item.family),
                    ("bold", "Bold", "check", item.bold),
                ])
                if not r: return
                item.text, item.size_mm, item.family, item.bold = r["text"], r["size"], r["family"], r["bold"]
            elif isinstance(item, QRItem):
                r = self.text_dialog("Edit QR Code", [
                    ("data", "Text / URL / data", "multiline", item.data),
                    ("ecc", "Error correction", "combo", (["L", "M", "Q", "H"], item.ecc)),
                ])
                if not r: return
                modules, scale = qr_safe_module_scale(r["data"], r["ecc"])
                if scale < 1:
                    raise ValueError("QR payload is too long for the E10 printable width.")
                item.data, item.ecc = r["data"], r["ecc"]
                if scale == 1:
                    self.show_info("Dense QR warning", f"This QR is {modules} modules wide and will print at 1 dot per module. Shorter data is recommended.")
            elif isinstance(item, ImageItem):
                r = self.text_dialog("Edit Image Size", [
                    ("width", "Width (mm)", "spin", item.width_mm),
                    ("height", "Height (mm)", "spin", item.height_mm),
                ])
                if not r: return
                item.width_mm = min(PRINTABLE_WIDTH_MM, r["width"]); item.height_mm = r["height"]
            elif isinstance(item, BoxItem):
                r = self.text_dialog("Edit Box", [
                    ("width", "Width (mm)", "spin", item.width_mm),
                    ("height", "Height (mm)", "spin", item.height_mm),
                ])
                if not r: return
                item.width_mm = min(PRINTABLE_WIDTH_MM, r["width"]); item.height_mm = r["height"]
            elif isinstance(item, LineItem):
                r = self.text_dialog("Edit Line", [("width", "Width (mm)", "spin", item.width_mm)])
                if not r: return
                item.width_mm = min(PRINTABLE_WIDTH_MM, r["width"] )
            self.doc.clamp_item(item, allow_length_extend=self.doc.auto_size)
            if self.doc.auto_size:
                self.apply_auto_size(shrink=True)
            else:
                self.canvas.invalidate_render(); self.update_status()
        except Exception as e:
            self.show_error("Could not edit object", str(e))

    def rotate_selected(self, *_):
        if self.canvas.selected is None: return
        self.canvas.selected.rotation = (self.canvas.selected.rotation + 90) % 360
        self.doc.clamp_item(self.canvas.selected, allow_length_extend=self.doc.auto_size)
        if self.doc.auto_size:
            self.apply_auto_size(shrink=True)
        else:
            self.canvas.invalidate_render(); self.update_status()

    def duplicate_selected(self, *_):
        if self.canvas.selected is None: return
        self.canvas.selected = self.doc.duplicate(self.canvas.selected)
        self.sync_length_controls(); self.canvas.refresh_size(); self.update_status()

    def delete_selected(self, *_):
        if self.canvas.selected is None: return
        try: self.doc.remove(self.canvas.selected)
        except ValueError: pass
        self.canvas.selected = None
        if self.doc.auto_size:
            self.apply_auto_size(shrink=True)
        else:
            self.canvas.invalidate_render(); self.update_status()

    def fit_contents(self, *_):
        self.doc.auto_length(self.doc.auto_margin_mm, 10.0)
        self.sync_length_controls()
        self.canvas.refresh_size(); self.update_status()

    def length_changed(self, w):
        if self.doc.auto_size:
            if abs(w.get_value() - self.doc.length_mm) > 1e-6:
                w.set_value(self.doc.length_mm)
            return
        self.doc.length_mm = w.get_value(); self.doc.validate()
        for i in self.doc.items:
            self.doc.clamp_item(i)
        self.canvas.refresh_size(); self.update_status()

    def stock_changed(self, w):
        text = w.get_active_text() or "15 mm"
        self.doc.stock_width_mm = 12.0 if text.startswith("12") else 15.0
        self.canvas.refresh_size(); self.update_status()

    def zoom_changed(self, w):
        text = w.get_active_text() or "100%"
        self.canvas.zoom = float(text.rstrip("%")) / 100.0
        self.canvas.refresh_size()

    def update_status(self):
        sel = self.canvas.selected if hasattr(self, "canvas") else None
        selected = "None"
        if sel is not None:
            x, y, w, h = self.doc.item_bounds_mm(sel)
            selected = f"{sel.kind}  across={x:.3f}mm along={y:.3f}mm  {w:.3f}×{h:.3f}mm"
        mode = "AUTO" if self.doc.auto_size else "MANUAL"
        self.status.set_text(
            f"Tape {self.doc.stock_width_mm:g}mm wide × {self.doc.length_mm:g}mm long ({mode}) | "
            f"printable 11mm / 88 dots | selected: {selected}"
        )

    def new_doc(self, *_):
        self.doc = LabelDocument(); self.current_path = None
        self.canvas.doc = self.doc; self.canvas.selected = None
        self.stock_combo.set_active(0); self.queue_entry.set_text(self.doc.queue)
        self.sync_length_controls()
        self.canvas.refresh_size(); self.update_status()

    def open_doc(self, *_):
        d = Gtk.FileChooserDialog("Open Label", self, Gtk.FileChooserAction.OPEN, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        filt = Gtk.FileFilter(); filt.set_name("SUPVAN Label (*.supvanlabel)"); filt.add_pattern("*.supvanlabel"); filt.add_pattern("*.json"); d.add_filter(filt)
        resp = d.run(); path = d.get_filename() if resp == Gtk.ResponseType.OK else None; d.destroy()
        if not path: return
        try:
            self.doc = LabelDocument.load(path); self.current_path = Path(path); self.canvas.doc = self.doc; self.canvas.selected = None
            self.stock_combo.set_active(1 if self.doc.stock_width_mm == 12 else 0); self.queue_entry.set_text(self.doc.queue)
            self.sync_length_controls()
            self.canvas.refresh_size(); self.update_status()
        except Exception as e: self.show_error("Could not open label", str(e))

    def save_doc(self, *_):
        path = self.current_path
        if path is None:
            d = Gtk.FileChooserDialog("Save Label", self, Gtk.FileChooserAction.SAVE, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
            d.set_do_overwrite_confirmation(True); d.set_current_name("label.supvanlabel")
            resp = d.run(); fn = d.get_filename() if resp == Gtk.ResponseType.OK else None; d.destroy()
            if not fn: return
            path = Path(fn)
            if path.suffix.lower() not in (".supvanlabel", ".json"): path = path.with_suffix(".supvanlabel")
        try:
            self.doc.save(path); self.current_path = path
        except Exception as e: self.show_error("Could not save label", str(e))

    def export_png_clicked(self, *_):
        d = Gtk.FileChooserDialog("Export Exact Raster", self, Gtk.FileChooserAction.SAVE, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
        d.set_do_overwrite_confirmation(True); d.set_current_name("label.png")
        resp = d.run(); fn = d.get_filename() if resp == Gtk.ResponseType.OK else None; d.destroy()
        if not fn: return
        try:
            path = Path(fn); path = path if path.suffix.lower() == ".png" else path.with_suffix(".png")
            export_png(self.doc, path); self.show_info("Exported", f"Exact E10 raster: 88 × {self.doc.render().height} dots\n{path}")
        except Exception as e: self.show_error("Export failed", str(e))

    def print_clicked(self, *_):
        self.doc.queue = self.queue_entry.get_text().strip()
        try:
            result = print_document(self.doc)
            self.show_info("Print submitted", result)
        except PrintError as e:
            self.show_error("Print failed", str(e))
        except Exception as e:
            self.show_error("Print failed", f"Unexpected error: {e}")


def main():
    win = MainWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
