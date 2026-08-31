import pytest

from backend.core.errors import AppError
from backend.core.security import normalize_youtube_url


def test_video_with_playlist_url_auto_selects_playlist_and_strips_tracking_params():
    info = normalize_youtube_url(
        "https://www.youtube.com/watch?v=abc123&utm_source=x&list=PL42&t=12s"
    )

    assert info.has_video is True
    assert info.has_playlist is True
    assert info.default_scope == "playlist"
    assert info.scope_options == ["single", "playlist"]
    assert "utm_source" not in info.normalized_url
    assert "v=abc123" in info.normalized_url
    assert "list=PL42" in info.normalized_url


def test_playlist_url_is_playlist_scope():
    info = normalize_youtube_url("https://www.youtube.com/playlist?list=PL42")

    assert info.has_video is False
    assert info.has_playlist is True
    assert info.default_scope == "playlist"


def test_rejects_non_youtube_url():
    with pytest.raises(AppError):
        normalize_youtube_url("https://example.com/watch?v=abc123")
