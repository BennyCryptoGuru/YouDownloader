from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import Header, WebSocket

from backend.core.errors import AppError

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}

KEEP_QUERY_PARAMS = {"v", "list", "index", "t", "start"}
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")


@dataclass(slots=True)
class UrlInfo:
    normalized_url: str
    has_video: bool
    has_playlist: bool

    @property
    def default_scope(self) -> str:
        if self.has_playlist:
            return "playlist"
        return "single"

    @property
    def scope_options(self) -> list[str]:
        if self.has_video and self.has_playlist:
            return ["single", "playlist"]
        return [self.default_scope]


def normalize_youtube_url(raw_url: str) -> UrlInfo:
    parsed = urlparse(raw_url.strip())
    host = parsed.netloc.lower()
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
        raise AppError("INVALID_URL", "Vlozte platny HTTPS odkaz na YouTube.")

    query = dict(parse_qsl(parsed.query, keep_blank_values=False))
    shorts_video_id = _video_id_from_shorts_path(parsed.path)
    youtu_be_video_id = _video_id_from_youtu_be_path(parsed.path) if host == "youtu.be" else None
    has_video = bool(query.get("v")) or bool(shorts_video_id) or bool(youtu_be_video_id)
    has_playlist = bool(query.get("list"))

    if not has_video and not has_playlist:
        raise AppError("INVALID_URL", "Odkaz neobsahuje video ani playlist.")

    clean_path = parsed.path
    clean_query = [(key, value) for key, value in parse_qsl(parsed.query) if key in KEEP_QUERY_PARAMS]
    if shorts_video_id and not query.get("v"):
        clean_path = "/watch"
        clean_query = [
            ("v", shorts_video_id),
            *[(key, value) for key, value in clean_query if key != "v"],
        ]
    clean_url = urlunparse(
        (
            parsed.scheme,
            host,
            clean_path,
            "",
            urlencode(clean_query),
            "",
        )
    )
    return UrlInfo(clean_url, has_video=has_video, has_playlist=has_playlist)


def _video_id_from_shorts_path(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or parts[0].lower() != "shorts":
        return None
    video_id = parts[1]
    if YOUTUBE_VIDEO_ID_RE.fullmatch(video_id):
        return video_id
    return None


def _video_id_from_youtu_be_path(path: str) -> str | None:
    video_id = path.strip("/").split("/", 1)[0]
    if YOUTUBE_VIDEO_ID_RE.fullmatch(video_id):
        return video_id
    return None


def require_token(
    x_session_token: Annotated[str | None, Header(alias="X-Session-Token")] = None,
) -> str:
    if not x_session_token:
        raise AppError("INVALID_TOKEN", "Chybi session token.", status_code=401)
    return x_session_token


def verify_header_token(expected_token: str, received_token: str | None) -> None:
    if not received_token or received_token != expected_token:
        raise AppError("INVALID_TOKEN", "Neplatny session token.", status_code=401)


async def verify_websocket_token(websocket: WebSocket, expected_token: str) -> bool:
    token = websocket.query_params.get("token")
    if token != expected_token:
        await websocket.close(code=1008)
        return False
    return True
