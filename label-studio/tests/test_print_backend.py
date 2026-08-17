from PIL import Image

from supvan_label_studio.core import LabelDocument, PRINTABLE_WIDTH_DOTS
from supvan_label_studio.print_backend import export_jpeg_exact


def test_exact_jpeg_keeps_88_by_length_geometry(tmp_path):
    d = LabelDocument(length_mm=123.0, auto_size=False)
    p = tmp_path / "label.jpg"
    export_jpeg_exact(d, p)
    with Image.open(p) as img:
        assert img.size == (PRINTABLE_WIDTH_DOTS, 984)
        assert img.mode == "L"

from supvan_label_studio.print_backend import choose_default_queue


def test_choose_default_queue_prefers_exact_supvan_e10_match():
    queues = ["Office_Laser", "SUPVAN_E10", "Other"]
    assert choose_default_queue(queues) == "SUPVAN_E10"


def test_choose_default_queue_keeps_saved_queue_when_present():
    queues = ["Office_Laser", "My_E10"]
    assert choose_default_queue(queues, "My_E10") == "My_E10"


def test_choose_default_queue_falls_back_without_machine_specific_name():
    queues = ["Printer_A", "Printer_B"]
    assert choose_default_queue(queues) == "Printer_A"
