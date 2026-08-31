from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from backend.core.errors import AppError


class YtDlp:
    def __init__(self, executable: str, ffmpeg: str | None = None, js_runtime: str | None = None) -> None:
        self.executable = executable
        self.ffmpeg = ffmpeg
        self.js_runtime = js_runtime

    def ensure_available(self) -> None:
        if Path(self.executable).exists() or shutil.which(self.executable):
            return
        if importlib.util.find_spec("yt_dlp"):
            return
        if not Path(self.executable).exists() and not self.executable == "yt-dlp":
            raise AppError("YTDLP_MISSING", "yt-dlp nebyl nalezen.", status_code=503)

    def command(self) -> list[str]:
        self.ensure_available()
        if Path(self.executable).exists() or shutil.which(self.executable):
            return [self.executable]
        return [sys.executable, "-m", "yt_dlp"]

    async def dump_json(self, url: str, *, playlist: bool) -> dict:
        self.ensure_available()
        args = [
            *self.command(),
            "--no-config",
            "--skip-download",
            "--dump-single-json",
            "--ignore-errors",
        ]
        if self.js_runtime:
            args.extend(["--js-runtimes", self.js_runtime])
        if playlist:
            args.append("--yes-playlist")
            args.append("--flat-playlist")
        else:
            args.append("--no-playlist")
        args.append(url)
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        if process.returncode != 0:
            raise AppError("VIDEO_UNAVAILABLE", stderr.decode("utf-8", "replace")[-500:])
        try:
            return json.loads(stdout.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise AppError("VIDEO_UNAVAILABLE", "yt-dlp nevratil platna metadata.") from exc

    async def run_download(self, args: list[str], cwd: Path) -> AsyncIterator[str]:
        self.ensure_available()
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        assert process.stdout is not None
        async for raw_line in process.stdout:
            yield raw_line.decode("utf-8", "replace").strip()
        return_code = await process.wait()
        if return_code != 0:
            raise AppError("NETWORK_ERROR", f"yt-dlp skoncil s kodem {return_code}.")
