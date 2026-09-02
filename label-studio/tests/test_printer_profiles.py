from types import SimpleNamespace

from supvan_label_studio.core import LabelDocument
from supvan_label_studio.printer_profiles import (
    PrinterProfile,
    apply_profile_to_document,
    detected_media_choices,
    detected_resolution_dpi,
    e10_profile,
    load_profiles,
    profile_for_queue,
    save_profile,
)


def test_e10_profile_preserves_validated_linux_geometry():
    profile = e10_profile("gosse-e10")
    assert profile.printable_width_dots == 88
    assert profile.printable_width_mm == 11.0
    assert profile.verified
    assert profile.transport == "e10-exact-jpeg"


def test_custom_profile_persists_and_applies(tmp_path):
    path = tmp_path / "profiles.json"
    profile = PrinterProfile(
        key="office-label", name="Office labeler", queue="office-label",
        printable_width_dots=144, dots_per_mm=12.0,
        nominal_stock_width_mm=14.0, nominal_dpi=300,
        media="Custom.14x50mm", verified=True,
    )
    save_profile(profile, path)
    loaded = load_profiles(path)["office-label"]
    doc = LabelDocument(auto_size=False)
    apply_profile_to_document(doc, loaded)
    assert doc.printable_width_dots == 144
    assert doc.printable_width_mm == 12.0
    assert doc.stock_width_mm == 14.0


def test_cups_options_expose_resolution_and_media_without_guessing_width(monkeypatch):
    monkeypatch.setattr("supvan_label_studio.printer_profiles.shutil.which", lambda _name: "/usr/bin/tool")

    def fake_run(command, **_kwargs):
        assert command[:3] == ["lpoptions", "-p", "office-label"]
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Resolution/Resolution: *300dpi 600dpi\n"
                "PageSize/Media Size: *w100h200 w120h300\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("supvan_label_studio.printer_profiles.subprocess.run", fake_run)
    assert detected_resolution_dpi("office-label") == 300
    choices, default = detected_media_choices("office-label")
    assert choices == ["w100h200", "w120h300"]
    assert default == "w100h200"


def test_e10_builtin_profile_is_canonical_15mm_tape():
    # The current production roll is 15 mm wide; custom profiles can still model other media.
    profile = e10_profile("gosse-e10", stock_width_mm=12.0)
    assert profile.nominal_stock_width_mm == 15.0
