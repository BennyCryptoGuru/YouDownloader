from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.core.errors import AppError

ALLOWED_THUMBNAIL_HOSTS = {
    "i.ytimg.com",
    "i1.ytimg.com",
    "i2.ytimg.com",
    "i3.ytimg.com",
    "i4.ytimg.com",
    "img.youtube.com",
}


class ThumbnailCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def token_for_url(self, url: str | None) -> str | None:
        if not url:
            return None
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    async def get(self, token: str, url: str) -> tuple[bytes, str]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.lower() not in ALLOWED_THUMBNAIL_HOSTS:
            raise AppError("INVALID_URL", "Nepovolena domena nahledu.", status_code=400)

        suffix = ".jpg"
        content_type_path = self.directory / f"{token}.mime"
        image_path = self.directory / f"{token}{suffix}"
        if image_path.exists() and content_type_path.exists():
            return image_path.read_bytes(), content_type_path.read_text(encoding="utf-8")

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(url)
        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400 or not content_type.startswith("image/"):
            raise AppError("INVALID_URL", "Nahled se nepodarilo nacist.", status_code=502)
        if len(response.content) > 5_000_000:
            raise AppError("INVALID_URL", "Nahled je prilis velky.", status_code=400)

        image_path.write_bytes(response.content)
        content_type_path.write_text(content_type, encoding="utf-8")
        return response.content, content_type

