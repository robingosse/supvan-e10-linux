from __future__ import annotations

from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gtk
except Exception:
    raise

from .canvas import LabelCanvas
from .core import LabelDocument, MAX_LENGTH_MM, ONE_DOT_MM, PRINTABLE_WIDTH_MM
from .history import DocumentHistory, document_snapshot
from .preferences import AppPreferences, load_preferences
from .theme import THEME_CSS
from .workbench_bridge import WorkbenchSession

APP_NAME = "SUPVAN Label Studio"
APP_VERSION = "0.3.2"
APP_TITLE = f"{APP_NAME} {APP_VERSION}"


def apply_styles() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(THEME_CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


class MainWindowLayoutMixin:
    def __init__(self):
        apply_styles()
        super().__init__()
        self.set_default_size(1280, 820)
        self.set_size_request(980, 620)
        self.preferences: AppPreferences = load_preferences()
        self.doc = LabelDocument(
            stock_width_mm=self.preferences.stock_width_mm,
            queue=self.preferences.queue,
        )
        self.current_path: Path | None = None
        self.history = DocumentHistory(limit=100)
        self.saved_snapshot = document_snapshot(self.doc)
        self.dirty = False
        self._syncing = True
        self._transient_status = ""
        self.workbench_session: WorkbenchSession | None = None

        self.set_titlebar(self.make_headerbar())
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        workspace = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(workspace, True, True, 0)
        workspace.pack_start(self.make_left_panel(), False, False, 0)
        workspace.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        canvas_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        canvas_frame.get_style_context().add_class("canvas-frame")
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_shadow_type(Gtk.ShadowType.IN)
        self.canvas = LabelCanvas(self)
        self.canvas.zoom = self.preferences.zoom_percent / 100.0
        self.scroller.add(self.canvas)
        canvas_frame.pack_start(self.scroller, True, True, 12)
        workspace.pack_start(canvas_frame, True, True, 0)

        workspace.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        workspace.pack_start(self.make_right_panel(), False, False, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.set_margin_start(10)
        self.status.set_margin_end(10)
        self.status.set_margin_top(6)
        self.status.set_margin_bottom(6)
        self.status.set_ellipsize(3)
        self.status.get_style_context().add_class("status-bar")
        root.pack_start(Gtk.Separator(), False, False, 0)
        root.pack_start(self.status, False, False, 0)

        self.connect("delete-event", self.on_delete_event)
        self.connect("key-press-event", self.on_window_key)
        self._syncing = False
        self.refresh_queues()
        self.sync_all_controls()
        self.update_window_title()
        self.update_status()
        self.show_all()

    def make_headerbar(self):
        bar = Gtk.HeaderBar()
        bar.set_show_close_button(True)
        bar.set_title(APP_NAME)
        bar.set_subtitle("Workstation label editor")

        self.new_button = self.button("New", self.new_doc, "Ctrl+N")
        self.open_button = self.button("Open", self.open_doc, "Ctrl+O")
        self.save_button = self.button("Save", self.save_doc, "Ctrl+S")
        bar.pack_start(self.new_button)
        bar.pack_start(self.open_button)
        bar.pack_start(self.save_button)

        self.undo_button = self.button("Undo", self.undo, "Ctrl+Z")
        self.redo_button = self.button("Redo", self.redo, "Ctrl+Shift+Z")
        bar.pack_start(self.undo_button)
        bar.pack_start(self.redo_button)

        self.workbench_button = self.button("Return to Workbench", self.return_to_workbench)
        self.workbench_button.get_style_context().add_class("workbench-button")
        self.workbench_button.set_no_show_all(True)
        bar.pack_end(self.workbench_button)

        self.print_button = self.button("Print Label", self.print_clicked, "Ctrl+P")
        self.print_button.get_style_context().add_class("print-button")
        bar.pack_end(self.print_button)
        return bar

    def button(self, label, callback, tooltip=None):
        button = Gtk.Button(label=label)
        button.set_relief(Gtk.ReliefStyle.NORMAL)
        button.get_style_context().add_class("studio-button")
        button.connect("clicked", callback)
        if tooltip:
            button.set_tooltip_text(tooltip)
        return button

    def section_title(self, text):
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class("section-title")
        return label

    def labeled_control(self, label, control):
        row = Gtk.Box(spacing=6)
        row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        row.pack_end(control, False, False, 0)
        return row

    def make_left_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        panel.set_size_request(250, -1)
        panel.get_style_context().add_class("studio-panel")

        panel.pack_start(self.section_title("ADD TO LABEL"), False, False, 0)
        tool_grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        tools = [
            ("Text", self.add_text),
            ("QR Code", self.add_qr),
            ("Image", self.add_image),
            ("Box", self.add_box),
            ("Line", self.add_line),
        ]
        for index, (label, callback) in enumerate(tools):
            tool_grid.attach(self.button(label, callback), index % 2, index // 2, 1, 1)
        panel.pack_start(tool_grid, False, False, 0)

        panel.pack_start(self.section_title("LABEL STOCK"), False, False, 0)
        stock_row = Gtk.Box(spacing=6)
        stock_row.pack_start(Gtk.Label(label="Width", xalign=0), True, True, 0)
        self.stock_combo = Gtk.ComboBoxText()
        self.stock_combo.append_text("15 mm")
        self.stock_combo.append_text("12 mm")
        self.stock_combo.connect("changed", self.stock_changed)
        stock_row.pack_end(self.stock_combo, False, False, 0)
        panel.pack_start(stock_row, False, False, 0)

        self.auto_check = Gtk.CheckButton(label="Fit length to contents")
        self.auto_check.connect("toggled", self.auto_size_changed)
        panel.pack_start(self.auto_check, False, False, 0)

        self.length_spin = Gtk.SpinButton.new_with_range(5.0, MAX_LENGTH_MM, ONE_DOT_MM)
        self.length_spin.set_digits(3)
        self.length_spin.connect("value-changed", self.length_changed)
        panel.pack_start(self.labeled_control("Length (mm)", self.length_spin), False, False, 0)

        self.margin_spin = Gtk.SpinButton.new_with_range(0.0, 100.0, ONE_DOT_MM)
        self.margin_spin.set_digits(3)
        self.margin_spin.connect("value-changed", self.margin_changed)
        panel.pack_start(self.labeled_control("End margin", self.margin_spin), False, False, 0)
        panel.pack_start(self.button("Fit Contents Now", self.fit_contents), False, False, 0)

        panel.pack_start(self.section_title("VIEW"), False, False, 0)
        self.zoom_combo = Gtk.ComboBoxText()
        for zoom in ("50%", "75%", "100%", "150%", "200%"):
            self.zoom_combo.append_text(zoom)
        self.zoom_combo.connect("changed", self.zoom_changed)
        panel.pack_start(self.labeled_control("Zoom", self.zoom_combo), False, False, 0)

        panel.pack_start(self.section_title("PRINTER"), False, False, 0)
        self.queue_combo = Gtk.ComboBoxText.new_with_entry()
        self.queue_combo.get_child().connect("changed", self.queue_changed)
        panel.pack_start(self.queue_combo, False, False, 0)
        printer_buttons = Gtk.Box(spacing=6)
        printer_buttons.pack_start(self.button("Refresh", self.refresh_queues), True, True, 0)
        printer_buttons.pack_start(self.button("Printer Check", self.printer_check), True, True, 0)
        panel.pack_start(printer_buttons, False, False, 0)
        self.copies_spin = Gtk.SpinButton.new_with_range(1, 999, 1)
        self.copies_spin.set_digits(0)
        self.copies_spin.connect("value-changed", self.copies_changed)
        panel.pack_start(self.labeled_control("Copies", self.copies_spin), False, False, 0)

        hint = Gtk.Label(
            label="Tape runs left → right. Arrow keys move one printer dot; Shift+Arrow moves 1 mm.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("muted")
        panel.pack_end(hint, False, False, 0)
        return panel

    def make_right_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        panel.set_size_request(285, -1)
        panel.get_style_context().add_class("studio-panel")

        panel.pack_start(self.section_title("SELECTED OBJECT"), False, False, 0)
        self.selected_label = Gtk.Label(label="Nothing selected", xalign=0)
        self.selected_label.set_ellipsize(3)
        panel.pack_start(self.selected_label, False, False, 0)

        self.across_spin = Gtk.SpinButton.new_with_range(0, PRINTABLE_WIDTH_MM, ONE_DOT_MM)
        self.across_spin.set_digits(3)
        self.across_spin.connect("value-changed", self.position_changed)
        panel.pack_start(self.labeled_control("Across (mm)", self.across_spin), False, False, 0)

        self.along_spin = Gtk.SpinButton.new_with_range(0, MAX_LENGTH_MM, ONE_DOT_MM)
        self.along_spin.set_digits(3)
        self.along_spin.connect("value-changed", self.position_changed)
        panel.pack_start(self.labeled_control("Along (mm)", self.along_spin), False, False, 0)

        self.rotation_combo = Gtk.ComboBoxText()
        for rotation in ("0°", "90°", "180°", "270°"):
            self.rotation_combo.append_text(rotation)
        self.rotation_combo.connect("changed", self.rotation_changed)
        panel.pack_start(self.labeled_control("Rotation", self.rotation_combo), False, False, 0)

        panel.pack_start(Gtk.Label(label="Align across printable band", xalign=0), False, False, 0)
        align_row = Gtk.Box(spacing=5)
        align_row.pack_start(self.button("Top", lambda *_: self.align_selected("end")), True, True, 0)
        align_row.pack_start(self.button("Centre", lambda *_: self.align_selected("center")), True, True, 0)
        align_row.pack_start(self.button("Bottom", lambda *_: self.align_selected("start")), True, True, 0)
        panel.pack_start(align_row, False, False, 0)

        object_row = Gtk.Box(spacing=5)
        object_row.pack_start(self.button("Edit", self.edit_selected), True, True, 0)
        object_row.pack_start(self.button("Duplicate", self.duplicate_selected), True, True, 0)
        self.delete_button = self.button("Delete", self.delete_selected)
        self.delete_button.get_style_context().add_class("danger-button")
        object_row.pack_start(self.delete_button, True, True, 0)
        panel.pack_start(object_row, False, False, 0)

        panel.pack_start(self.section_title("LAYERS"), False, False, 0)
        layer_scroller = Gtk.ScrolledWindow()
        layer_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        layer_scroller.set_shadow_type(Gtk.ShadowType.IN)
        self.layer_list = Gtk.ListBox()
        self.layer_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.layer_list.connect("row-selected", self.layer_selected)
        layer_scroller.add(self.layer_list)
        panel.pack_start(layer_scroller, True, True, 0)

        layer_row = Gtk.Box(spacing=5)
        layer_row.pack_start(self.button("Send Back", lambda *_: self.move_selected_layer(-1)), True, True, 0)
        layer_row.pack_start(self.button("Bring Forward", lambda *_: self.move_selected_layer(1)), True, True, 0)
        panel.pack_start(layer_row, False, False, 0)
        panel.pack_start(self.button("Export Exact PNG", self.export_png_clicked), False, False, 0)
        return panel
