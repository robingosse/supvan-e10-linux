from __future__ import annotations

from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
except Exception:
    raise

from .core import LabelDocument, MAX_LENGTH_MM, ONE_DOT_MM
from .history import document_snapshot
from .preferences import save_preferences
from .print_backend import export_png
from .printer_profiles import apply_profile_to_document, profile_for_queue
from .window_layout import APP_TITLE


class MainWindowIOMixin:
    def confirm_discard_changes(self) -> bool:
        if not self.dirty:
            return True
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Save changes to this label?",
        )
        dialog.format_secondary_text("Unsaved changes will be lost if you discard them.")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Discard", Gtk.ResponseType.REJECT)
        dialog.add_button("Save", Gtk.ResponseType.ACCEPT)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            return self.save_doc()
        return response == Gtk.ResponseType.REJECT

    def new_doc(self, *_):
        if not self.confirm_discard_changes():
            return False
        self.doc = LabelDocument(
            stock_width_mm=self.preferences.stock_width_mm,
            queue=self.preferences.queue,
        )
        profile = profile_for_queue(self.doc.queue, self.doc.stock_width_mm)
        if profile is not None:
            apply_profile_to_document(self.doc, profile)
        self.current_path = None
        self.history.reset()
        self.saved_snapshot = self.snapshot()
        self.dirty = False
        self.canvas.doc = self.doc
        self.canvas.selected = None
        self.sync_all_controls()
        self.canvas.refresh_size()
        self.update_window_title()
        self.update_status()
        return True

    def open_doc(self, *_):
        if not self.confirm_discard_changes():
            return False
        dialog = Gtk.FileChooserDialog(
            "Open Label",
            self,
            Gtk.FileChooserAction.OPEN,
            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK),
        )
        label_filter = Gtk.FileFilter()
        label_filter.set_name("SUPVAN labels")
        label_filter.add_pattern("*.supvanlabel")
        label_filter.add_pattern("*.json")
        dialog.add_filter(label_filter)
        if self.preferences.last_open_directory:
            dialog.set_current_folder(self.preferences.last_open_directory)
        response = dialog.run()
        filename = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not filename:
            return False
        return self.load_document_path(filename)

    def load_document_path(self, filename):
        try:
            self.doc = LabelDocument.load(filename)
            self.current_path = Path(filename)
            self.preferences.last_open_directory = str(self.current_path.parent)
            self.history.reset()
            self.saved_snapshot = self.snapshot()
            self.dirty = False
            self.canvas.doc = self.doc
            self.canvas.selected = None
            self.sync_all_controls()
            self.canvas.refresh_size()
            self.update_window_title()
            self.update_status()
            return True
        except Exception as error:
            self.show_error("Could not open label", str(error))
            return False

    def save_doc(self, *_):
        path = self.current_path
        if path is None:
            dialog = Gtk.FileChooserDialog(
                "Save Label",
                self,
                Gtk.FileChooserAction.SAVE,
                (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK),
            )
            dialog.set_do_overwrite_confirmation(True)
            dialog.set_current_name("label.supvanlabel")
            if self.preferences.last_open_directory:
                dialog.set_current_folder(self.preferences.last_open_directory)
            response = dialog.run()
            filename = dialog.get_filename() if response == Gtk.ResponseType.OK else None
            dialog.destroy()
            if not filename:
                return False
            path = Path(filename)
            if path.suffix.lower() not in (".supvanlabel", ".json"):
                path = path.with_suffix(".supvanlabel")
        try:
            self.doc.queue = self.queue_text() or self.doc.queue
            self.doc.save(path)
            self.current_path = path
            self.preferences.last_open_directory = str(path.parent)
            self.saved_snapshot = self.snapshot()
            self.dirty = False
            self.update_window_title()
            self.set_transient_status(f"Saved {path.name}")
            return True
        except Exception as error:
            self.show_error("Could not save label", str(error))
            return False

    def export_png_clicked(self, *_):
        dialog = Gtk.FileChooserDialog(
            "Export Exact Raster",
            self,
            Gtk.FileChooserAction.SAVE,
            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK),
        )
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name("label.png")
        if self.preferences.last_export_directory:
            dialog.set_current_folder(self.preferences.last_export_directory)
        response = dialog.run()
        filename = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not filename:
            return
        try:
            path = Path(filename)
            if path.suffix.lower() != ".png":
                path = path.with_suffix(".png")
            export_png(self.doc, path)
            self.preferences.last_export_directory = str(path.parent)
            self.show_info(
                "Exported exact raster",
                f"{self.doc.printable_width_dots} × {self.doc.render().height} dots\n"
                f"{self.doc.printable_width_mm:.3f} mm usable width\n\n{path}",
            )
        except Exception as error:
            self.show_error("Export failed", str(error))

    def text_dialog(self, title, fields):
        dialog = Gtk.Dialog(title=title, transient_for=self, flags=0)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK,
            Gtk.ResponseType.OK,
        )
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        widgets = {}
        for row_number, (name, label, kind, default) in enumerate(fields):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row_number, 1, 1)
            if kind == "entry":
                widget = Gtk.Entry()
                widget.set_text(str(default))
            elif kind == "multiline":
                widget = Gtk.TextView()
                widget.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
                widget.set_size_request(440, 110)
                widget.get_buffer().set_text(str(default))
            elif kind == "spin":
                widget = Gtk.SpinButton.new_with_range(self.doc.one_dot_mm, MAX_LENGTH_MM, self.doc.one_dot_mm)
                widget.set_digits(3)
                widget.set_value(float(default))
            elif kind == "integer":
                widget = Gtk.SpinButton.new_with_range(1, 16, 1)
                widget.set_digits(0)
                widget.set_value(int(default))
            elif kind == "check":
                widget = Gtk.CheckButton()
                widget.set_active(bool(default))
            elif kind == "combo":
                options, active = default
                widget = Gtk.ComboBoxText()
                for option in options:
                    widget.append_text(option)
                widget.set_active(options.index(active) if active in options else 0)
            else:
                raise ValueError(kind)
            grid.attach(widget, 1, row_number, 1, 1)
            widgets[name] = (kind, widget)
        dialog.get_content_area().add(grid)
        dialog.show_all()
        response = dialog.run()
        result = None
        if response == Gtk.ResponseType.OK:
            result = {}
            for name, (kind, widget) in widgets.items():
                if kind == "entry":
                    result[name] = widget.get_text()
                elif kind == "multiline":
                    buffer = widget.get_buffer()
                    result[name] = buffer.get_text(
                        buffer.get_start_iter(), buffer.get_end_iter(), True
                    )
                elif kind == "spin":
                    result[name] = widget.get_value()
                elif kind == "integer":
                    result[name] = int(widget.get_value())
                elif kind == "check":
                    result[name] = widget.get_active()
                elif kind == "combo":
                    result[name] = widget.get_active_text()
        dialog.destroy()
        return result

    def show_error(self, title: str, message: str):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def show_info(self, title: str, message: str):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def update_window_title(self):
        filename = self.current_path.name if self.current_path else "Untitled label"
        marker = "*" if self.dirty else ""
        self.set_title(f"{marker}{filename} — {APP_TITLE}")
        titlebar = self.get_titlebar()
        if isinstance(titlebar, Gtk.HeaderBar):
            titlebar.set_title(f"{marker}{filename}")
            titlebar.set_subtitle(APP_TITLE)

    def set_transient_status(self, message: str):
        self._transient_status = message
        self.update_status()
        GLib.timeout_add_seconds(5, self.clear_transient_status)

    def clear_transient_status(self):
        self._transient_status = ""
        self.update_status()
        return False

    def update_status(self):
        if not hasattr(self, "status"):
            return
        if self._transient_status:
            self.status.set_text(self._transient_status)
            return
        item = self.canvas.selected
        selected = "No selection"
        if item is not None and item in self.doc.items:
            x, y, width, height = self.doc.item_bounds_mm(item)
            selected = (
                f"{item.kind}: across {x:.3f} mm, along {y:.3f} mm, "
                f"{width:.3f} × {height:.3f} mm"
            )
        mode = "auto length" if self.doc.auto_size else "manual length"
        queue = self.queue_text() if hasattr(self, "queue_combo") else self.doc.queue
        self.status.set_text(
            f"{self.doc.stock_width_mm:g} mm tape × {self.doc.length_mm:g} mm long • {mode} • "
            f"{self.doc.printable_width_dots}-dot / {self.doc.printable_width_mm:.3f} mm printable band • "
            f"Queue: {queue or 'none'} • {selected}"
        )

    def on_window_key(self, _widget, event):
        control = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if not control:
            return False
        key_name = Gdk.keyval_name(event.keyval)
        key = key_name.lower() if key_name else ""
        if key == "n":
            self.new_doc()
        elif key == "o":
            self.open_doc()
        elif key == "s":
            self.save_doc()
        elif key == "p":
            self.print_clicked()
        elif key == "z" and shift:
            self.redo()
        elif key == "z":
            self.undo()
        elif key == "y":
            self.redo()
        elif key == "d":
            self.duplicate_selected()
        else:
            return False
        return True

    def on_delete_event(self, *_):
        if not self.confirm_discard_changes():
            return True
        self.preferences.queue = self.queue_text() or self.preferences.queue
        self.preferences.stock_width_mm = self.doc.stock_width_mm
        self.preferences.zoom_percent = int(round(self.canvas.zoom * 100))
        self.preferences.copies = int(self.copies_spin.get_value())
        try:
            save_preferences(self.preferences)
        except OSError:
            pass
        Gtk.main_quit()
        return False
