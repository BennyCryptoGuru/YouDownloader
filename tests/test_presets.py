import pytest

from backend.core.errors import AppError
from backend.domain.presets import ytdlp_args_for_preset
from backend.services.download_manager import YTDLP_PROGRESS_RE, DownloadManager
from backend.services.ytdlp import YtDlp


def test_mp3_quality_maps_to_audio_args():
    args = ytdlp_args_for_preset("audio_mp3", "192")

    assert "--extract-audio" in args
    assert "--audio-format" in args
    assert "mp3" in args
    assert "192K" in args


def test_unknown_quality_is_rejected():
    with pytest.raises(AppError):
        ytdlp_args_for_preset("video_mp4", "999p")


def test_mp4_best_prefers_stable_https_formats_before_m3u8_fallbacks():
    args = ytdlp_args_for_preset("video_mp4", "best")
    selector = args[args.index("-f") + 1]

    assert "bv*[ext=mp4][protocol=https]+ba[ext=m4a][protocol=https]" in selector
    assert selector.index("[protocol=https]") < selector.index("bv*[ext=mp4]+ba[ext=m4a]")


def test_download_args_include_resume_and_retry_options():
    manager = DownloadManager.__new__(DownloadManager)
    manager.ytdlp = YtDlp("yt-dlp", "resources/bin/ffmpeg.exe", "node:node")

    args = manager._download_args(
        {
            "kind": "video",
            "targetRoot": "C:/Downloads",
            "targetSubfolder": None,
            "title": "Video",
            "preset": "audio_mp3",
            "quality": "192",
            "sourceUrl": "https://www.youtube.com/watch?v=abc123",
        }
    )

    assert "--continue" in args
    assert "--part" in args
    assert args[args.index("--retries") + 1] == "10"
    assert args[args.index("--fragment-retries") + 1] == "10"
    assert args[args.index("--file-access-retries") + 1] == "5"
    assert args[args.index("--socket-timeout") + 1] == "30"
    assert "--progress-template" in args
    assert "__YDL_PROGRESS__" in args[args.index("--progress-template") + 1]


def test_playlist_download_args_resume_from_current_item_index():
    manager = DownloadManager.__new__(DownloadManager)
    manager.ytdlp = YtDlp("yt-dlp", "resources/bin/ffmpeg.exe", "node:node")

    args = manager._download_args(
        {
            "kind": "playlist",
            "targetRoot": "C:/Downloads",
            "targetSubfolder": "Playlist",
            "title": "Playlist",
            "preset": "video_mp4",
            "quality": "best",
            "sourceUrl": "https://youtube.com/playlist?list=PL42",
            "currentItemIndex": 95,
        }
    )

    assert args[args.index("--playlist-start") + 1] == "95"


def test_download_output_speed_and_eta_parsing():
    line = "[download]  44.5% of 120.00MiB at 2.50MiB/s ETA 01:23"

    assert DownloadManager._parse_speed(line) == 2_621_440
    assert DownloadManager._parse_eta(line) == 83


def test_download_progress_template_parsing():
    line = "[download] __YDL_PROGRESS__ 44.5%\t2.50MiB/s\t01:23"
    match = YTDLP_PROGRESS_RE.search(line)

    assert match is not None
    assert DownloadManager._parse_progress_percent(match.group("percent")) == 44.5
    assert DownloadManager._parse_speed_value(match.group("speed")) == 2_621_440
    assert DownloadManager._parse_eta_value(match.group("eta")) == 83


def test_download_progress_template_parses_downloaded_and_total_bytes():
    line = "[download] __YDL_PROGRESS__ NA\t2.50MiB/s\tUnknown\t120000000\t240000000\t250000000"
    match = YTDLP_PROGRESS_RE.search(line)

    assert match is not None
    downloaded = DownloadManager._parse_byte_count(match.group("downloaded"))
    total = DownloadManager._parse_byte_count(match.group("total"))
    estimated = DownloadManager._parse_byte_count(match.group("estimated"))

    assert downloaded == 120_000_000
    assert total == 240_000_000
    assert estimated == 250_000_000
    assert DownloadManager._progress_from_bytes(downloaded, total) == 50
