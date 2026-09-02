from __future__ import annotations

from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except Exception:
    raise

from .core import (
    BoxItem, ImageItem, LineItem, MAX_LENGTH_MM, ONE_DOT_MM, PRINTABLE_WIDTH_MM,
    QRItem, TextItem, image_item_from_file, qr_safe_module_scale,
)
from .history import document_from_snapshot, document_snapshot


class MainWindowEditMixin:
    def snapshot(self) -> str:
        return document_snapshot(self.doc)

    def finish_edit(self, before: str, refresh_layers: bool = True) -> bool:
        after = self.snapshot()
        changed = self.history.record(before, after)
        if not changed:
            return False
        self.dirty = after != self.saved_snapshot
        self.canvas.doc = self.doc
        self.sync_document_controls()
        self.sync_selection_controls()
        if refresh_layers:
            self.refresh_layers()
        self.canvas.refresh_size()
        self.update_history_buttons()
        self.update_window_title()
        self.update_status()
        return True

    def restore_snapshot(self, snapshot: str, selected_id: str = "") -> None:
        self.doc = document_from_snapshot(snapshot)
        self.canvas.doc = self.doc
        selected = next((item for item in self.doc.items if item.id == selected_id), None)
        self.canvas.selected = selected
        self.dirty = snapshot != self.saved_snapshot
        self.sync_all_controls()
        self.canvas.refresh_size()
        self.update_history_buttons()
        self.update_window_title()
        self.update_status()

    def undo(self, *_):
        selected_id = self.canvas.selected.id if self.canvas.selected is not None else ""
        snapshot = self.history.undo(self.snapshot())
        if snapshot is not None:
            self.restore_snapshot(snapshot, selected_id)

    def redo(self, *_):
        selected_id = self.canvas.selected.id if self.canvas.selected is not None else ""
        snapshot = self.history.redo(self.snapshot())
        if snapshot is not None:
            self.restore_snapshot(snapshot, selected_id)

    def update_history_buttons(self) -> None:
        self.undo_button.set_sensitive(self.history.can_undo)
        self.redo_button.set_sensitive(self.history.can_redo)

    def set_selected(self, item, from_layers=False) -> None:
        self.canvas.selected = item
        self.sync_selection_controls()
        if not from_layers:
            self.select_layer_row(item)
        self.canvas.queue_draw()
        self.update_status()

    def select_layer_row(self, item) -> None:
        self._syncing = True
        try:
            target_id = item.id if item is not None else None
            row = next(
                (row for row in self.layer_list.get_children() if getattr(row, "item_id", None) == target_id),
                None,
            )
            self.layer_list.select_row(row)
        finally:
            self._syncing = False

    def item_caption(self, item) -> str:
        if isinstance(item, TextItem):
            summary = (item.text or "Blank text").replace("\n", " ")[:28]
        elif isinstance(item, QRItem):
            summary = (item.data or "Empty QR")[:28]
        elif isinstance(item, ImageItem):
            summary = item.name
        else:
            summary = item.kind.title()
        return f"{item.kind.upper()}  {summary}"

    def refresh_layers(self) -> None:
        if not hasattr(self, "layer_list"):
            return
        selected_id = self.canvas.selected.id if self.canvas.selected is not None else None
        self._syncing = True
        try:
            for child in list(self.layer_list.get_children()):
                self.layer_list.remove(child)
            for item in reversed(self.doc.items):
                row = Gtk.ListBoxRow()
                row.item_id = item.id
                label = Gtk.Label(label=self.item_caption(item), xalign=0)
                label.set_margin_start(7)
                label.set_margin_end(7)
                label.set_margin_top(6)
                label.set_margin_bottom(6)
                label.set_ellipsize(3)
                row.add(label)
                self.layer_list.add(row)
            self.layer_list.show_all()
            row = next(
                (row for row in self.layer_list.get_children() if row.item_id == selected_id),
                None,
            )
            self.layer_list.select_row(row)
        finally:
            self._syncing = False

    def layer_selected(self, _listbox, row) -> None:
        if self._syncing:
            return
        item_id = getattr(row, "item_id", None) if row is not None else None
        item = next((candidate for candidate in self.doc.items if candidate.id == item_id), None)
        self.set_selected(item, from_layers=True)

    def sync_document_controls(self) -> None:
        if not hasattr(self, "stock_combo"):
            return
        self._syncing = True
        try:
            self.stock_combo.set_active(1 if self.doc.stock_width_mm == 12.0 else 0)
            self.auto_check.set_active(self.doc.auto_size)
            self.length_spin.set_value(self.doc.length_mm)
            self.length_spin.set_sensitive(not self.doc.auto_size)
            self.margin_spin.set_value(self.doc.auto_margin_mm)
            self.margin_spin.set_sensitive(self.doc.auto_size)
            zoom_text = f"{int(round(self.canvas.zoom * 100))}%"
            zoom_options = ["50%", "75%", "100%", "150%", "200%"]
            self.zoom_combo.set_active(zoom_options.index(zoom_text) if zoom_text in zoom_options else 2)
            self.queue_combo.get_child().set_text(self.doc.queue or self.preferences.queue)
            self.copies_spin.set_value(self.preferences.copies)
        finally:
            self._syncing = False

    def sync_selection_controls(self) -> None:
        if not hasattr(self, "selected_label"):
            return
        item = self.canvas.selected
        self._syncing = True
        try:
            enabled = item is not None and item in self.doc.items
            self.across_spin.set_sensitive(enabled)
            self.along_spin.set_sensitive(enabled)
            self.rotation_combo.set_sensitive(enabled)
            self.delete_button.set_sensitive(enabled)
            if not enabled:
                self.selected_label.set_text("Nothing selected")
                self.across_spin.set_value(0)
                self.along_spin.set_value(0)
                self.rotation_combo.set_active(0)
            else:
                _, _, width, height = self.doc.item_bounds_mm(item)
                self.selected_label.set_text(
                    f"{self.item_caption(item)}  •  {width:.3f} × {height:.3f} mm"
                )
                self.across_spin.set_value(item.x_mm)
                self.along_spin.set_value(item.y_mm)
                self.rotation_combo.set_active((item.rotation % 360) // 90)
        finally:
            self._syncing = False

    def sync_all_controls(self) -> None:
        self.sync_document_controls()
        self.refresh_layers()
        self.sync_selection_controls()
        self.update_history_buttons()

    def apply_auto_size(self, shrink=True, record=True):
        if not self.doc.auto_size:
            return
        before = self.snapshot() if record else ""
        if shrink:
            self.doc.auto_length(self.doc.auto_margin_mm, 10.0)
        elif self.canvas.selected is not None:
            self.doc.ensure_auto_length_for(self.canvas.selected)
        if record:
            self.finish_edit(before)
        else:
            self.sync_document_controls()
            self.canvas.refresh_size()
            self.update_status()

    def auto_size_changed(self, widget):
        if self._syncing:
            return
        before = self.snapshot()
        self.doc.auto_size = bool(widget.get_active())
        if self.doc.auto_size:
            self.doc.auto_length(self.doc.auto_margin_mm, 10.0)
        self.finish_edit(before)

    def margin_changed(self, widget):
        if self._syncing:
            return
        before = self.snapshot()
        self.doc.auto_margin_mm = float(widget.get_value())
        self.doc.validate()
        if self.doc.auto_size:
            self.doc.auto_length(self.doc.auto_margin_mm, 10.0)
        self.finish_edit(before, refresh_layers=False)

    def length_changed(self, widget):
        if self._syncing or self.doc.auto_size:
            return
        before = self.snapshot()
        self.doc.length_mm = widget.get_value()
        self.doc.validate()
        for item in self.doc.items:
            self.doc.clamp_item(item)
        self.finish_edit(before)

    def stock_changed(self, widget):
        if self._syncing:
            return
        before = self.snapshot()
        text = widget.get_active_text() or "15 mm"
        self.doc.stock_width_mm = 12.0 if text.startswith("12") else 15.0
        self.preferences.stock_width_mm = self.doc.stock_width_mm
        self.finish_edit(before, refresh_layers=False)

    def zoom_changed(self, widget):
        if self._syncing:
            return
        text = widget.get_active_text() or "100%"
        self.canvas.zoom = float(text.rstrip("%")) / 100.0
        self.preferences.zoom_percent = int(round(self.canvas.zoom * 100))
        self.canvas.refresh_size()
        self.update_status()

    def queue_changed(self, widget):
        if self._syncing:
            return
        queue = widget.get_text().strip()
        if queue:
            self.doc.queue = queue
            self.preferences.queue = queue
        self.update_status()

    def copies_changed(self, widget):
        if not self._syncing:
            self.preferences.copies = int(widget.get_value())

    def position_changed(self, _widget):
        if self._syncing or self.canvas.selected is None:
            return
        before = self.snapshot()
        self.canvas.selected.x_mm = self.across_spin.get_value()
        self.canvas.selected.y_mm = self.along_spin.get_value()
        self.doc.clamp_item(self.canvas.selected, allow_length_extend=self.doc.auto_size)
        if self.doc.auto_size:
            self.doc.ensure_auto_length_for(self.canvas.selected)
        self.finish_edit(before, refresh_layers=False)

    def rotation_changed(self, widget):
        if self._syncing or self.canvas.selected is None:
            return
        before = self.snapshot()
        self.canvas.selected.rotation = max(0, widget.get_active()) * 90
        self.doc.clamp_item(self.canvas.selected, allow_length_extend=self.doc.auto_size)
        if self.doc.auto_size:
            self.doc.auto_length(self.doc.auto_margin_mm, 10.0)
        self.finish_edit(before)

    def align_selected(self, alignment):
        if self.canvas.selected is None:
            return
        before = self.snapshot()
        self.doc.align_across(self.canvas.selected, alignment)
        self.finish_edit(before, refresh_layers=False)

    def move_selected_layer(self, offset):
        if self.canvas.selected is None:
            return
        before = self.snapshot()
        self.doc.move_layer(self.canvas.selected, offset)
        self.finish_edit(before)

    def next_y(self, height_mm=4.0):
        bounds = self.doc.content_bounds_mm()
        if bounds is None:
            return 1.0
        bottom = bounds[1] + bounds[3]
        maximum = MAX_LENGTH_MM if self.doc.auto_size else self.doc.length_mm
        return min(max(0.0, bottom + 1.0), max(0.0, maximum - height_mm))

    def add_and_select(self, item):
        before = self.snapshot()
        self.doc.add(item)
        self.canvas.selected = item
        self.finish_edit(before)

    def add_text(self, *_):
        result = self.text_dialog(
            "Add Text",
            [
                ("text", "Text", "multiline", "Label text"),
                ("size", "Height (mm)", "spin", 3.0),
                ("autofit_height", "Autofit to height", "check", True),
                ("family", "Font family", "entry", "DejaVu Sans"),
                ("bold", "Bold", "check", False),
            ],
        )
        if result:
            self.add_and_select(
                TextItem(
                    text=result["text"],
                    size_mm=result["size"],
                    autofit_height=result["autofit_height"],
                    family=result["family"],
                    bold=result["bold"],
                    y_mm=self.next_y(4),
                )
            )

    def add_qr(self, *_):
        result = self.text_dialog(
            "Generate QR Code",
            [
                ("data", "Text / URL / data", "multiline", "https://"),
                ("ecc", "Error correction", "combo", (["L", "M", "Q", "H"], "M")),
            ],
        )
        if not result:
            return
        try:
            modules, scale = qr_safe_module_scale(result["data"], result["ecc"])
            if scale < 1:
                raise ValueError("QR payload is too long for the E10 printable width.")
            if scale == 1:
                self.show_info(
                    "Dense QR warning",
                    f"This code is {modules} modules wide and prints at one dot per module. Shorter data will scan more reliably.",
                )
            self.add_and_select(
                QRItem(
                    data=result["data"],
                    ecc=result["ecc"],
                    full_width=True,
                    y_mm=self.next_y(PRINTABLE_WIDTH_MM),
                )
            )
        except Exception as error:
            self.show_error("Could not generate QR code", str(error))

    def add_image(self, *_):
        dialog = Gtk.FileChooserDialog(
            "Import Image",
            self,
            Gtk.FileChooserAction.OPEN,
            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK),
        )
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Images")
        image_filter.add_pixbuf_formats()
        dialog.add_filter(image_filter)
        if self.preferences.last_open_directory:
            dialog.set_current_folder(self.preferences.last_open_directory)
        response = dialog.run()
        filename = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not filename:
            return
        try:
            self.preferences.last_open_directory = str(Path(filename).parent)
            item = image_item_from_file(filename)
            item.y_mm = self.next_y(item.height_mm)
            self.add_and_select(item)
        except Exception as error:
            self.show_error("Could not import image", str(error))

    def add_box(self, *_):
        self.add_and_select(BoxItem(width_mm=8.0, height_mm=4.0, y_mm=self.next_y(4.0)))

    def add_line(self, *_):
        self.add_and_select(
            LineItem(width_mm=PRINTABLE_WIDTH_MM, y_mm=self.next_y(ONE_DOT_MM))
        )

    def edit_selected(self, *_):
        item = self.canvas.selected
        if item is None:
            return
        before = self.snapshot()
        try:
            if isinstance(item, TextItem):
                result = self.text_dialog(
                    "Edit Text",
                    [
                        ("text", "Text", "multiline", item.text),
                        ("size", "Height (mm)", "spin", item.size_mm),
                        ("autofit_height", "Autofit to height", "check", item.autofit_height),
                        ("family", "Font family", "entry", item.family),
                        ("bold", "Bold", "check", item.bold),
                    ],
                )
                if not result:
                    return
                item.text = result["text"]
                item.size_mm = result["size"]
                item.autofit_height = result["autofit_height"]
                item.family = result["family"]
                item.bold = result["bold"]
            elif isinstance(item, QRItem):
                result = self.text_dialog(
                    "Edit QR Code",
                    [
                        ("data", "Text / URL / data", "multiline", item.data),
                        ("ecc", "Error correction", "combo", (["L", "M", "Q", "H"], item.ecc)),
                    ],
                )
                if not result:
                    return
                modules, scale = qr_safe_module_scale(result["data"], result["ecc"])
                if scale < 1:
                    raise ValueError("QR payload is too long for the E10 printable width.")
                item.data = result["data"]
                item.ecc = result["ecc"]
                if scale == 1:
                    self.show_info(
                        "Dense QR warning",
                        f"This code is {modules} modules wide and prints at one dot per module.",
                    )
            elif isinstance(item, ImageItem):
                result = self.text_dialog(
                    "Edit Image Size",
                    [
                        ("width", "Width (mm)", "spin", item.width_mm),
                        ("height", "Height (mm)", "spin", item.height_mm),
                    ],
                )
                if not result:
                    return
                item.width_mm = min(PRINTABLE_WIDTH_MM, result["width"])
                item.height_mm = result["height"]
            elif isinstance(item, BoxItem):
                result = self.text_dialog(
                    "Edit Box",
                    [
                        ("width", "Width (mm)", "spin", item.width_mm),
                        ("height", "Height (mm)", "spin", item.height_mm),
                        ("line", "Line thickness (dots)", "integer", item.line_dots),
                    ],
                )
                if not result:
                    return
                item.width_mm = min(PRINTABLE_WIDTH_MM, result["width"])
                item.height_mm = result["height"]
                item.line_dots = result["line"]
            elif isinstance(item, LineItem):
                result = self.text_dialog(
                    "Edit Line",
                    [
                        ("width", "Width (mm)", "spin", item.width_mm),
                        ("line", "Thickness (dots)", "integer", item.line_dots),
                    ],
                )
                if not result:
                    return
                item.width_mm = min(PRINTABLE_WIDTH_MM, result["width"])
                item.line_dots = result["line"]
            self.doc.clamp_item(item, allow_length_extend=self.doc.auto_size)
            if self.doc.auto_size:
                self.doc.auto_length(self.doc.auto_margin_mm, 10.0)
            self.finish_edit(before)
        except Exception as error:
            self.restore_snapshot(before, item.id)
            self.show_error("Could not edit object", str(error))

    def duplicate_selected(self, *_):
        if self.canvas.selected is None:
            return
        before = self.snapshot()
        self.canvas.selected = self.doc.duplicate(self.canvas.selected)
        self.finish_edit(before)

    def delete_selected(self, *_):
        if self.canvas.selected is None:
            return
        before = self.snapshot()
        self.doc.remove(self.canvas.selected)
        self.canvas.selected = None
        if self.doc.auto_size:
            self.doc.auto_length(self.doc.auto_margin_mm, 10.0)
        self.finish_edit(before)

    def fit_contents(self, *_):
        before = self.snapshot()
        self.doc.auto_length(self.doc.auto_margin_mm, 10.0)
        self.finish_edit(before)
