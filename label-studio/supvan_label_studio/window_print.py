from __future__ import annotations

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except Exception:
    raise

from .history import document_snapshot
from .print_backend import PrintError, choose_preferred_queue, list_printer_queues, preflight_printer, print_document
from .printer_profiles import (
    PrinterProfile, apply_profile_to_document, detected_media_choices,
    detected_resolution_dpi, profile_for_queue, save_profile,
)
from .workbench_bridge import load_workbench_session


class MainWindowPrintMixin:
    def refresh_queues(self, *_):
        preferred = self.queue_text() if hasattr(self, "queue_combo") else self.preferences.queue
        queues = list_printer_queues()
        selected = choose_preferred_queue(queues, preferred)
        self._syncing = True
        try:
            self.queue_combo.remove_all()
            for queue in queues:
                self.queue_combo.append_text(queue.name)
            self.queue_combo.get_child().set_text(selected)
            self.doc.queue = selected
            self.preferences.queue = selected
        finally:
            self._syncing = False
        self.refresh_printer_profile()
        self.update_status()
        return queues


    def refresh_printer_profile(self):
        if not hasattr(self, "printer_profile_label"):
            return None
        queue = self.queue_text() if hasattr(self, "queue_combo") else self.doc.queue
        profile = profile_for_queue(queue, self.doc.stock_width_mm)
        if profile is None:
            if hasattr(self, "stock_spin"):
                self.stock_spin.set_sensitive(True)
            self.printer_profile_label.set_text(
                f"Unconfigured CUPS queue · using document geometry: "
                f"{self.doc.printable_width_mm:.3f} mm / {self.doc.printable_width_dots} dots. "
                "Use Printer / Media Setup before relying on physical dimensions."
            )
            return None
        apply_profile_to_document(self.doc, profile)
        self.doc.queue = queue
        if hasattr(self, "stock_spin"):
            # Built-in verified media geometry is physical truth; custom profiles remain editable.
            self.stock_spin.set_sensitive(not (profile.built_in and profile.verified))
        self.printer_profile_label.set_text(profile.summary)
        if hasattr(self, "across_spin"):
            self.across_spin.set_range(0.0, self.doc.printable_width_mm)
            self.across_spin.set_increments(self.doc.one_dot_mm, 1.0)
        if hasattr(self, "canvas"):
            self.canvas.refresh_size()
        return profile

    def printer_setup(self, *_):
        queue = self.queue_text()
        if not queue:
            self.show_error("Printer setup", "Select a CUPS queue first.")
            return
        current = profile_for_queue(queue, self.doc.stock_width_mm)
        detected_dpi = detected_resolution_dpi(queue) or (current.nominal_dpi if current else 203)
        media_choices, media_default = detected_media_choices(queue)

        dialog = Gtk.Dialog(title=f"Printer / Media Setup · {queue}", transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Save Profile", Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)

        name = Gtk.Entry(); name.set_text(current.name if current else queue)
        stock = Gtk.SpinButton.new_with_range(1.0, 500.0, 0.125); stock.set_digits(3); stock.set_value(current.nominal_stock_width_mm if current else self.doc.stock_width_mm)
        printable = Gtk.SpinButton.new_with_range(1.0, 500.0, 0.125); printable.set_digits(3); printable.set_value(current.printable_width_mm if current else self.doc.printable_width_mm)
        dpi = Gtk.SpinButton.new_with_range(25, 4800, 1); dpi.set_digits(0); dpi.set_value(current.nominal_dpi if current else detected_dpi)
        media = Gtk.ComboBoxText.new_with_entry()
        for choice in media_choices: media.append_text(choice)
        media.get_child().set_text(current.media if current and current.media else media_default)
        verified = Gtk.CheckButton(label="Geometry verified by a real printer test")
        verified.set_active(bool(current.verified) if current else False)

        rows = [
            ("Profile name", name), ("Stock width (mm)", stock),
            ("Usable printable width (mm)", printable), ("Resolution (dpi)", dpi),
            ("CUPS media option", media),
        ]
        for row, (label, widget) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        grid.attach(verified, 0, len(rows), 2, 1)
        note = Gtk.Label(
            label=(
                "CUPS can report queues, resolution and media choices, but many drivers do not report "
                "their true unprintable margins. The usable width is therefore explicit profile data, "
                "not guessed by Studio."
            ), xalign=0
        )
        note.set_line_wrap(True)
        grid.attach(note, 0, len(rows) + 1, 2, 1)
        dialog.get_content_area().add(grid)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            target_dpi = int(dpi.get_value())
            dpm = target_dpi / 25.4
            usable_mm = float(printable.get_value())
            width_dots = max(8, int(round(usable_mm * dpm)))
            transport = current.transport if current else "cups-image"
            # Preserve the E10's proven 8-dot/mm transport when editing its built-in profile.
            if current and current.built_in and current.transport == "e10-exact-jpeg":
                dpm = current.dots_per_mm
                width_dots = max(8, int(round(usable_mm * dpm)))
                if width_dots != current.printable_width_dots:
                    self.show_error(
                        "E10 geometry is validated",
                        "The current Linux E10 transport is validated at 88 dots (11.0 mm). "
                        "A wider E10 raster needs a separately validated driver/profile rather than "
                        "silently changing the production profile.",
                    )
                    dialog.destroy()
                    return
            profile = PrinterProfile(
                key=f"cups-{queue}", name=name.get_text().strip() or queue, queue=queue,
                printable_width_dots=width_dots, dots_per_mm=dpm,
                nominal_stock_width_mm=float(stock.get_value()), nominal_dpi=target_dpi,
                transport=transport, media=media.get_child().get_text().strip(),
                verified=verified.get_active(), built_in=False,
            )
            save_profile(profile)
            apply_profile_to_document(self.doc, profile)
            self.preferences.stock_width_mm = self.doc.stock_width_mm
            self.sync_document_controls()
            self.refresh_printer_profile()
            self.canvas.refresh_size()
            self.update_status()
        dialog.destroy()

    def queue_text(self) -> str:
        return self.queue_combo.get_child().get_text().strip()

    def printer_check(self, *_):
        check = preflight_printer(self.queue_text())
        details = "\n".join(check.details) if check.details else "No additional details."
        if check.ready:
            profile = profile_for_queue(self.queue_text(), self.doc.stock_width_mm)
            geometry = profile.summary if profile else f"Geometry unconfigured · document currently {self.doc.printable_width_mm:.3f} mm / {self.doc.printable_width_dots} dots"
            self.show_info("Printer ready", f"{check.summary}\n\n{geometry}\n\n{details}")
        else:
            self.show_error("Printer needs attention", f"{check.summary}\n\n{details}")

    def print_clicked(self, *_):
        queue = self.queue_text() or "gosse-e10"
        copies = int(self.copies_spin.get_value())
        check = preflight_printer(queue)
        if not check.ready:
            self.show_error("Printer needs attention", "\n".join(check.details))
            return
        try:
            dots = self.doc.render().height
        except Exception as error:
            self.show_error("Label cannot be rendered", str(error))
            return
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="Print this label?",
        )
        dialog.format_secondary_text(
            f"Queue: {queue}\nCopies: {copies}\nContinuous tape: {self.doc.stock_width_mm:g} mm wide × {self.doc.length_mm:g} mm long\nRaster: {self.doc.printable_width_dots} × {dots} dots"
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Print", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        self.doc.queue = queue
        self.preferences.queue = queue
        self.preferences.copies = copies
        try:
            result = print_document(
                self.doc,
                queue=queue,
                copies=copies,
                profile=profile_for_queue(queue, self.doc.stock_width_mm),
                job_name=self.current_path.stem if self.current_path else "SUPVAN Label",
            )
            self.show_info("Print submitted", result)
        except PrintError as error:
            self.show_error("Print failed", str(error))
        except Exception as error:
            self.show_error("Print failed", f"Unexpected error: {error}")

    def load_workbench_request(self, request_path: str):
        try:
            session = load_workbench_session(request_path)
            self.workbench_session = session
            self.doc = session.document
            self.current_path = session.document_path
            self.saved_snapshot = document_snapshot(self.doc)
            self.history.reset()
            self.dirty = False
            self.canvas.doc = self.doc
            self.canvas.selected = None
            self.canvas.refresh_size()
            self.sync_all_controls()
            self.refresh_layers()
            self.workbench_button.show()
            self.set_transient_status(f"Workbench job: {session.job_id or 'label authoring'}")
            self.update_window_title()
            return False
        except Exception as error:
            self.show_error("Could not open Workbench request", str(error))
            return False

    def return_to_workbench(self, *_):
        if self.workbench_session is None:
            return
        try:
            result_path = self.workbench_session.write_result(self.doc, current_path=self.current_path)
            self.dirty = False
            self.saved_snapshot = document_snapshot(self.doc)
            self.update_window_title()
            self.set_transient_status(f"Returned label to Workbench: {result_path}")
        except Exception as error:
            self.show_error("Could not return label to Workbench", str(error))
            return
        Gtk.main_quit()
