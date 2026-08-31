from backend.services.filename import sanitize_filename


def test_sanitizes_windows_filename_characters():
    assert sanitize_filename('A/B:C*D?"E') == "A_B_C_D__E"


def test_avoids_reserved_windows_names():
    assert sanitize_filename("CON") == "CON_"


def test_uses_fallback_for_empty_names():
    assert sanitize_filename("   ...   ", fallback="video") == "video"

