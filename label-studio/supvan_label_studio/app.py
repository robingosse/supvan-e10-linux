from __future__ import annotations

import sys

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk
except Exception:  # pragma: no cover - exercised on a desktop with GTK installed
    print(
        "SUPVAN Label Studio requires GTK 3 Python bindings.\n"
        "Install: sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo",
        file=sys.stderr,
    )
    raise

from .window_edit import MainWindowEditMixin
from .window_io import MainWindowIOMixin
from .window_layout import MainWindowLayoutMixin
from .window_media import MainWindowMediaMixin
from .window_print import MainWindowPrintMixin


class MainWindow(
    MainWindowLayoutMixin,
    MainWindowMediaMixin,
    MainWindowEditMixin,
    MainWindowPrintMixin,
    MainWindowIOMixin,
    Gtk.Window,
):
    """SUPVAN Label Studio main application window."""


def main():
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workbench-request")
    parser.add_argument("path", nargs="?")
    args, _unknown = parser.parse_known_args(sys.argv[1:])

    window = MainWindow()
    window.show_all()
    if args.workbench_request:
        GLib.idle_add(window.load_workbench_request, args.workbench_request)
    elif args.path:
        GLib.idle_add(window.load_document_path, args.path)
    Gtk.main()


if __name__ == "__main__":
    main()
