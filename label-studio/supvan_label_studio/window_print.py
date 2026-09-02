from __future__ import annotations

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except Exception:
    raise

from .history import document_snapshot
from .print_backend import PrintError, choose_preferred_queue, list_printer_queues, preflight_printer, print_document
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
        self.update_status()
        return queues

    def queue_text(self) -> str:
        return self.queue_combo.get_child().get_text().strip()

    def printer_check(self, *_):
        check = preflight_printer(self.queue_text())
        details = "\n".join(check.details) if check.details else "No additional details."
        if check.ready:
            self.show_info("Printer ready", f"{check.summary}\n\n{details}")
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
            f"Queue: {queue}\nCopies: {copies}\nLabel: {self.doc.stock_width_mm:g} × {self.doc.length_mm:g} mm\nExact raster: 88 × {dots} dots"
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
