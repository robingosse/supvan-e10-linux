from types import SimpleNamespace

from supvan_label_studio.core import LabelDocument
from supvan_label_studio.printer_catalog import builtin_family_keys
from supvan_label_studio.printer_profiles import (
    PrinterProfile,
    apply_profile_to_document,
    detected_media_choices,
    detected_resolution_dpi,
    documented_family_for_queue,
    documented_profile_for_queue,
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
    assert profile.evidence == "hardware-validated"
    assert profile.transport == "e10-exact-jpeg"


def test_custom_profile_persists_and_applies(tmp_path):
    path = tmp_path / "profiles.json"
    profile = PrinterProfile(
        key="office-label", name="Office labeler", queue="office-label",
        printable_width_dots=144, dots_per_mm=12.0,
        nominal_stock_width_mm=14.0, nominal_dpi=300,
        media="Custom.14x50mm", verified=True,
        vendor="Example", family="Bench unit", evidence="hardware-validated",
    )
    save_profile(profile, path)
    loaded = load_profiles(path)["office-label"]
    doc = LabelDocument(auto_size=False)
    apply_profile_to_document(doc, loaded)
    assert doc.printable_width_dots == 144
    assert doc.printable_width_mm == 12.0
    assert doc.stock_width_mm == 14.0
    assert loaded.vendor == "Example"
    assert loaded.evidence == "hardware-validated"


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


def test_catalog_contains_five_non_supvan_target_ecosystems():
    assert builtin_family_keys() == (
        "brother-pt-p710bt",
        "niimbot-b1",
        "dymo-labelwriter-550",
        "zebra-zd421-203",
        "rollo-x1040-wireless",
    )


def test_brother_pt_p710bt_uses_vendor_raster_table_for_each_tape_width():
    expected = {
        3.5: 24,
        6.0: 32,
        9.0: 50,
        12.0: 70,
        18.0: 112,
        24.0: 128,
    }
    for stock_mm, dots in expected.items():
        profile = documented_profile_for_queue("Brother_PT-P710BT", stock_mm)
        assert profile is not None
        assert profile.printable_width_dots == dots
        assert profile.nominal_stock_width_mm == stock_mm
        assert profile.nominal_dpi == 180
        assert profile.evidence == "vendor-documented"
        assert not profile.verified


def test_niimbot_b1_recognizes_common_queue_name_and_384_dot_band():
    profile = documented_profile_for_queue("NIIMBOT_B1", 50.0)
    assert profile is not None
    assert profile.printable_width_dots == 384
    assert profile.printable_width_mm == 48.0
    assert profile.nominal_dpi == 203


def test_dymo_550_uses_conservative_vendor_max_print_width():
    profile = documented_profile_for_queue("DYMO_LabelWriter_550", 62.0)
    assert profile is not None
    assert profile.printable_width_dots == 661
    assert profile.nominal_dpi == 300
    assert profile.printable_width_mm <= 56.0


def test_zebra_zd421_203_profile_uses_published_104mm_maximum_width():
    profile = documented_profile_for_queue("Zebra_ZD421", 108.0)
    assert profile is not None
    assert profile.printable_width_dots == 832
    assert profile.printable_width_mm == 104.0
    assert profile.nominal_dpi == 203


def test_rollo_is_recognized_but_does_not_fabricate_printable_band():
    family = documented_family_for_queue("Rollo_X1040_Wireless")
    assert family is not None
    assert family.key == "rollo-x1040-wireless"
    assert family.media_width_min_mm == 40.0
    assert family.media_width_max_mm == 104.0
    assert documented_profile_for_queue("Rollo_X1040_Wireless", 104.0) is None


def test_queue_specific_calibration_overrides_builtin_catalog(tmp_path):
    path = tmp_path / "profiles.json"
    calibrated = PrinterProfile(
        key="calibrated-brother", name="My calibrated Brother", queue="Brother_PT-P710BT",
        printable_width_dots=126, dots_per_mm=180.0 / 25.4,
        nominal_stock_width_mm=24.0, nominal_dpi=180,
        verified=True, evidence="hardware-validated",
    )
    save_profile(calibrated, path)
    loaded = profile_for_queue("Brother_PT-P710BT", 24.0, path)
    assert loaded is not None
    assert loaded.key == "calibrated-brother"
    assert loaded.printable_width_dots == 126
    assert loaded.verified
