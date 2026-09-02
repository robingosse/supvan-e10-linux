from PIL import Image

from supvan_label_studio.core import LabelDocument, PRINTABLE_WIDTH_DOTS
from types import SimpleNamespace

from supvan_label_studio.print_backend import (
    choose_preferred_queue,
    export_jpeg_exact,
    list_printer_queues,
    print_document,
)


def test_exact_jpeg_keeps_88_by_length_geometry(tmp_path):
    d = LabelDocument(length_mm=123.0, auto_size=False)
    p = tmp_path / "label.jpg"
    export_jpeg_exact(d, p)
    with Image.open(p) as img:
        assert img.size == (PRINTABLE_WIDTH_DOTS, 984)
        assert img.mode == "L"


def test_queue_discovery_parses_default_and_disabled(monkeypatch):
    monkeypatch.setattr("supvan_label_studio.print_backend.shutil.which", lambda _name: "/usr/bin/tool")

    def fake_run(command, **_kwargs):
        if command == ["lpstat", "-d"]:
            return SimpleNamespace(returncode=0, stdout="system default destination: gosse-e10\n", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "printer gosse-e10 is idle. enabled since today\n"
                "printer old-label disabled since yesterday\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("supvan_label_studio.print_backend.subprocess.run", fake_run)
    queues = list_printer_queues()
    assert [queue.name for queue in queues] == ["gosse-e10", "old-label"]
    assert queues[0].is_default and queues[0].enabled
    assert not queues[1].enabled
    assert choose_preferred_queue(queues) == "gosse-e10"


def test_print_submits_requested_copy_count(monkeypatch):
    commands = []
    monkeypatch.setattr("supvan_label_studio.print_backend.shutil.which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr("supvan_label_studio.print_backend._queue_exists", lambda _queue: True)

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="request id is gosse-e10-42\n", stderr="")

    monkeypatch.setattr("supvan_label_studio.print_backend.subprocess.run", fake_run)
    result = print_document(LabelDocument(auto_size=False), copies=3)
    assert commands[0][0:7] == ["lp", "-d", "gosse-e10", "-n", "3", "-t", "SUPVAN Label Studio"]
    assert "Copies requested: 3" in result


def test_generic_cups_profile_submits_png_with_media(monkeypatch):
    from supvan_label_studio.printer_profiles import PrinterProfile

    commands = []
    monkeypatch.setattr("supvan_label_studio.print_backend.shutil.which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr("supvan_label_studio.print_backend._queue_exists", lambda _queue: True)

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="request id is office-label-7\n", stderr="")

    monkeypatch.setattr("supvan_label_studio.print_backend.subprocess.run", fake_run)
    doc = LabelDocument(
        queue="office-label", auto_size=False, printable_width_dots=144, dots_per_mm=12.0,
        stock_width_mm=14.0, printer_profile_key="office-label",
    )
    profile = PrinterProfile(
        key="office-label", name="Office labeler", queue="office-label",
        printable_width_dots=144, dots_per_mm=12.0, nominal_stock_width_mm=14.0,
        nominal_dpi=300, transport="cups-image", media="Custom.14x50mm", verified=True,
    )
    result = print_document(doc, profile=profile)
    assert commands[0][:3] == ["lp", "-d", "office-label"]
    media_index = commands[0].index("-o")
    assert commands[0][media_index:media_index + 2] == ["-o", "media=Custom.14x50mm"]
    assert commands[0][-1].endswith(".png")
    assert "Office labeler" in result
