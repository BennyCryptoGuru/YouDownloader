from __future__ import annotations

from dataclasses import dataclass

from backend.core.errors import AppError


@dataclass(frozen=True, slots=True)
class Preset:
    id: str
    label: str
    type: str
    qualities: tuple[str, ...]


PRESETS: dict[str, Preset] = {
    "video_mp4": Preset(
        id="video_mp4",
        label="MP4 video",
        type="video",
        qualities=("best", "2160p", "1440p", "1080p", "720p", "480p"),
    ),
    "video_webm": Preset(
        id="video_webm",
        label="WebM video",
        type="video",
        qualities=("best", "1080p", "720p"),
    ),
    "audio_mp3": Preset(
        id="audio_mp3",
        label="MP3 audio",
        type="audio",
        qualities=("320", "192", "128"),
    ),
    "audio_m4a": Preset(id="audio_m4a", label="M4A audio", type="audio", qualities=("best",)),
    "audio_opus": Preset(id="audio_opus", label="Opus audio", type="audio", qualities=("best",)),
}


def preset_list() -> list[dict[str, object]]:
    return [
        {"id": item.id, "label": item.label, "type": item.type, "qualities": list(item.qualities)}
        for item in PRESETS.values()
    ]


def ytdlp_args_for_preset(preset_id: str, quality: str) -> list[str]:
    preset = PRESETS.get(preset_id)
    if not preset:
        raise AppError("NO_COMPATIBLE_FORMAT", "Neznama predvolba formatu.")
    if quality not in preset.qualities:
        raise AppError("NO_COMPATIBLE_FORMAT", "Neznama kvalita pro zvolenou predvolbu.")

    if preset_id == "video_mp4":
        if quality == "best":
            selector = (
                "bv*[ext=mp4][protocol=https]+ba[ext=m4a][protocol=https]/"
                "b[ext=mp4][protocol=https]/"
                "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
            )
        else:
            height = quality.removesuffix("p")
            selector = (
                f"bv*[height<={height}][ext=mp4][protocol=https]+ba[ext=m4a][protocol=https]/"
                f"b[height<={height}][ext=mp4][protocol=https]/"
                f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
                f"b[height<={height}][ext=mp4]/bv*[height<={height}]+ba/b"
            )
        return ["-f", selector, "--merge-output-format", "mp4", "--recode-video", "mp4"]

    if preset_id == "video_webm":
        if quality == "best":
            selector = "bv*[ext=webm]+ba[ext=webm]/b[ext=webm]/bv*+ba/b"
        else:
            height = quality.removesuffix("p")
            selector = f"bv*[height<={height}][ext=webm]+ba[ext=webm]/b[height<={height}][ext=webm]/bv*[height<={height}]+ba/b"
        return ["-f", selector, "--merge-output-format", "webm"]

    if preset_id == "audio_mp3":
        return ["-f", "ba/b", "--extract-audio", "--audio-format", "mp3", "--audio-quality", f"{quality}K"]

    if preset_id == "audio_m4a":
        return ["-f", "ba[ext=m4a]/ba/b", "--extract-audio", "--audio-format", "m4a"]

    if preset_id == "audio_opus":
        return ["-f", "ba[ext=opus]/ba/b", "--extract-audio", "--audio-format", "opus"]

    raise AppError("NO_COMPATIBLE_FORMAT", "Neznama predvolba formatu.")
