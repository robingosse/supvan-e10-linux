from supvan_label_studio.preferences import AppPreferences, load_preferences, save_preferences


def test_preferences_roundtrip(tmp_path):
    path = tmp_path / "preferences.json"
    expected = AppPreferences(queue="office-e10", stock_width_mm=12, zoom_percent=150, copies=4)
    save_preferences(expected, path)
    actual = load_preferences(path)
    assert actual == expected


def test_invalid_preferences_fall_back_safely(tmp_path):
    path = tmp_path / "preferences.json"
    path.write_text("not json")
    actual = load_preferences(path)
    assert actual.queue == "gosse-e10"
    assert actual.copies == 1
