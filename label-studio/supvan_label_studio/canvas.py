from __future__ import annotations

import math

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk
except Exception:
    raise

from PIL import Image


PREVIEW_PX_PER_MM = 28.0
MAX_CANVAS_WIDTH_PX = 32_000


def pil_to_pixbuf(image: Image.Image) -> GdkPixbuf.Pixbuf:
    rgba = image.convert("RGBA")
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(rgba.tobytes()),
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
        self.drag_before: str | None = None
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
        requested = PREVIEW_PX_PER_MM * self.zoom
        long_label_limit = MAX_CANVAS_WIDTH_PX / max(self.doc.length_mm, 1.0)
        return max(0.25, min(requested, long_label_limit))

    def printable_top_px(self) -> float:
        return (self.doc.stock_width_mm - self.doc.printable_width_mm) / 2.0 * self.pxmm

    def refresh_size(self) -> None:
        width = int(math.ceil(self.doc.length_mm * self.pxmm)) + 2
        height = int(math.ceil(self.doc.stock_width_mm * self.pxmm)) + 2
        self.set_size_request(max(180, width), max(120, height))
        self.invalidate_render()

    def invalidate_render(self) -> None:
        self.preview_cache = None
        self.queue_draw()

    def to_doc_mm(self, x: float, y: float) -> tuple[float, float]:
        along_mm = x / self.pxmm
        across_from_top = (y - self.printable_top_px()) / self.pxmm
        across_mm = self.doc.printable_width_mm - across_from_top
        return across_mm, along_mm

    def on_draw(self, _widget, cr):
        pxmm = self.pxmm
        stock_width_px = self.doc.length_mm * pxmm
        stock_height_px = self.doc.stock_width_mm * pxmm
        printable_top = self.printable_top_px()
        printable_height_px = self.doc.printable_width_mm * pxmm

        cr.set_source_rgb(0.95, 0.91, 0.82)
        cr.rectangle(0, 0, stock_width_px, stock_height_px)
        cr.fill()
        cr.set_source_rgb(1.0, 0.975, 0.90)
        cr.rectangle(0, printable_top, stock_width_px, printable_height_px)
        cr.fill()
        cr.set_source_rgb(0.55, 0.58, 0.62)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, max(1, stock_width_px - 1), max(1, stock_height_px - 1))
        cr.stroke()
        cr.set_dash([4.0, 4.0])
        cr.move_to(0, printable_top)
        cr.line_to(stock_width_px, printable_top)
        cr.move_to(0, printable_top + printable_height_px)
        cr.line_to(stock_width_px, printable_top + printable_height_px)
        cr.stroke()
        cr.set_dash([])

        if self.preview_cache is None:
            try:
                raster = self.doc.render().transpose(Image.Transpose.ROTATE_90)
                self.preview_cache = pil_to_pixbuf(raster)
            except Exception as error:
                self.owner.set_transient_status(f"Render error: {error}")
                return False
        target_width = max(1, int(round(stock_width_px)))
        target_height = max(1, int(round(printable_height_px)))
        scaled = self.preview_cache.scale_simple(
            target_width, target_height, GdkPixbuf.InterpType.NEAREST
        )
        Gdk.cairo_set_source_pixbuf(cr, scaled, 0, printable_top)
        cr.paint()

        if self.selected is not None and self.selected in self.doc.items:
            x_mm, y_mm, width_mm, height_mm = self.doc.item_bounds_mm(self.selected)
            selection_x = y_mm * pxmm
            selection_y = printable_top + (self.doc.printable_width_mm - (x_mm + width_mm)) * pxmm
            selection_width = height_mm * pxmm
            selection_height = width_mm * pxmm
            cr.set_source_rgb(0.12, 0.36, 0.82)
            cr.set_line_width(1.5)
            cr.set_dash([5.0, 3.0])
            cr.rectangle(
                selection_x - 2,
                selection_y - 2,
                selection_width + 4,
                selection_height + 4,
            )
            cr.stroke()
            cr.set_dash([])
        return False

    def on_press(self, _widget, event):
        self.grab_focus()
        if event.button != 1:
            return False
        x_mm, y_mm = self.to_doc_mm(event.x, event.y)
        item = None
        if 0 <= x_mm <= self.doc.printable_width_mm and 0 <= y_mm <= self.doc.length_mm:
            item = self.doc.hit_test(x_mm, y_mm)
        self.owner.set_selected(item)
        if item is not None:
            self.dragging = True
            self.drag_before = self.owner.snapshot()
            self.drag_dx = x_mm - item.x_mm
            self.drag_dy = y_mm - item.y_mm
            if event.type == Gdk.EventType._2BUTTON_PRESS:
                self.dragging = False
                self.owner.edit_selected()
        self.queue_draw()
        return True

    def on_release(self, _widget, event):
        if event.button != 1:
            return False
        was_dragging = self.dragging
        self.dragging = False
        if was_dragging and self.doc.auto_size:
            self.owner.apply_auto_size(shrink=True, record=False)
        if was_dragging and self.drag_before is not None:
            self.owner.finish_edit(self.drag_before)
        self.drag_before = None
        return True

    def on_motion(self, _widget, event):
        if not self.dragging or self.selected is None:
            return False
        x_mm, y_mm = self.to_doc_mm(event.x, event.y)
        self.selected.x_mm = x_mm - self.drag_dx
        self.selected.y_mm = y_mm - self.drag_dy
        self.doc.clamp_item(self.selected, allow_length_extend=True)
        if self.doc.auto_size:
            old_length = self.doc.length_mm
            self.doc.ensure_auto_length_for(self.selected)
            if self.doc.length_mm != old_length:
                self.owner.sync_document_controls()
                self.refresh_size()
            else:
                self.invalidate_render()
        else:
            self.invalidate_render()
        self.owner.sync_selection_controls()
        self.owner.update_status()
        return True

    def on_key(self, _widget, event):
        if self.selected is None:
            return False
        before = self.owner.snapshot()
        step = 1.0 if event.state & Gdk.ModifierType.SHIFT_MASK else self.doc.one_dot_mm
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
            return False
        self.doc.clamp_item(self.selected, allow_length_extend=True)
        if self.doc.auto_size:
            self.owner.apply_auto_size(shrink=False, record=False)
        self.owner.finish_edit(before)
        return True
