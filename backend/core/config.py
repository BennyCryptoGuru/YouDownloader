from __future__ import annotations

import secrets
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "YouDownloader"
DEFAULT_PORT = 8765
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
RESOURCES_DIR = PROJECT_ROOT / "resources"
BIN_DIR = RESOURCES_DIR / "bin"
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
CACHE_DIR = PROJECT_ROOT / "cache"
LOG_DIR = PROJECT_ROOT / "logs"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def preferred_or_free_port(preferred_port: int = DEFAULT_PORT) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred_port))
        except OSError:
            return get_free_port()
    return preferred_port


def default_download_dir() -> Path:
    target = Path.home() / "Downloads" / APP_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def app_data_dir() -> Path:
    path = DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_cache_dir() -> Path:
    path = CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_log_dir() -> Path:
    path = LOG_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_or_path_command(name: str) -> str:
    suffix = ".exe" if sys.platform.startswith("win") else ""
    bundled = BIN_DIR / f"{name}{suffix}"
    if bundled.exists():
        return str(bundled)
    found = shutil.which(name) or shutil.which(f"{name}{suffix}")
    if found:
        return found
    return str(bundled)


@dataclass(slots=True)
class AppConfig:
    host: str = "127.0.0.1"
    port: int = 0
    session_token: str = ""
    database_path: Path = app_data_dir() / "app.db"
    settings_config_path: Path = CONFIG_DIR / "settings.json"
    thumbnail_dir: Path = app_cache_dir() / "thumbnails"
    ytdlp_path: str = bundled_or_path_command("yt-dlp")
    ffmpeg_path: str = bundled_or_path_command("ffmpeg")
    ffprobe_path: str = bundled_or_path_command("ffprobe")
    deno_path: str = bundled_or_path_command("deno")
    node_path: str = bundled_or_path_command("node")

    @property
    def js_runtime(self) -> str | None:
        deno = Path(self.deno_path)
        if deno.exists() or shutil.which(self.deno_path):
            return f"deno:{self.deno_path}"
        node = Path(self.node_path)
        if node.exists() or shutil.which(self.node_path):
            return f"node:{self.node_path}"
        return None

    @classmethod
    def create(cls, port: int | None = None) -> AppConfig:
        thumb_dir = app_cache_dir() / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            port=port if port is not None else preferred_or_free_port(),
            session_token=secrets.token_urlsafe(32),
            thumbnail_dir=thumb_dir,
        )
