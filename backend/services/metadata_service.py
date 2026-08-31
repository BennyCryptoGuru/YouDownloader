from __future__ import annotations

from backend.core.security import normalize_youtube_url
from backend.domain.models import PreviewItem, PreviewResponse
from backend.services.thumbnail_cache import ThumbnailCache
from backend.services.ytdlp import YtDlp


class MetadataService:
    def __init__(self, ytdlp: YtDlp, thumbnails: ThumbnailCache) -> None:
        self.ytdlp = ytdlp
        self.thumbnails = thumbnails
        self._thumbnail_urls: dict[str, str] = {}

    async def preview(self, source_url: str, scope: str = "auto") -> PreviewResponse:
        url_info = normalize_youtube_url(source_url)
        if scope not in {"auto", "single", "playlist"}:
            scope = "auto"
        resolved_scope = url_info.default_scope if scope == "auto" else scope
        if resolved_scope == "single" and not url_info.has_video:
            resolved_scope = "playlist"
        if resolved_scope == "playlist" and not url_info.has_playlist:
            resolved_scope = "single"
        playlist = resolved_scope == "playlist"
        data = await self.ytdlp.dump_json(url_info.normalized_url, playlist=playlist)

        if playlist:
            entries = data.get("entries") or []
            items = [
                PreviewItem(
                    index=int(entry.get("playlist_index") or index),
                    id=entry.get("id"),
                    title=entry.get("title") or "Bez nazvu",
                    duration=entry.get("duration"),
                )
                for index, entry in enumerate(entries, start=1)
                if entry
            ]
            thumb = self._best_thumbnail(data)
            thumbnail_url = self.register_thumbnail_source(thumb)
            return PreviewResponse(
                kind="playlist",
                sourceUrl=url_info.normalized_url,
                id=data.get("id"),
                title=data.get("title") or "Playlist",
                channel=data.get("channel") or data.get("uploader"),
                thumbnailUrl=thumbnail_url,
                thumbnail_source_url=thumb,
                itemCount=data.get("playlist_count") or len(entries),
                scopeOptions=url_info.scope_options,
                items=items,
            )

        thumb = self._best_thumbnail(data)
        thumbnail_url = self.register_thumbnail_source(thumb)
        return PreviewResponse(
            kind="video",
            sourceUrl=url_info.normalized_url,
            id=data.get("id"),
            title=data.get("title") or "Video",
            channel=data.get("channel") or data.get("uploader"),
            thumbnailUrl=thumbnail_url,
            thumbnail_source_url=thumb,
            duration=data.get("duration"),
            uploadDate=data.get("upload_date"),
            viewCount=data.get("view_count"),
            itemCount=1,
            scopeOptions=url_info.scope_options,
            items=[],
        )

    def thumbnail_source_for_token(self, token: str) -> str | None:
        return self._thumbnail_urls.get(token)

    def register_thumbnail_source(self, url: str | None) -> str | None:
        token = self.thumbnails.token_for_url(url)
        if not token or not url:
            return None
        self._thumbnail_urls[token] = url
        return f"/api/v1/thumbnails/{token}"

    @staticmethod
    def thumbnail_source_from_video_id(video_id: str | None) -> str | None:
        if not video_id:
            return None
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    @staticmethod
    def _best_thumbnail(data: dict) -> str | None:
        thumbnails = data.get("thumbnails") or []
        if thumbnails:
            selected = max(thumbnails, key=lambda item: item.get("width") or 0)
            return selected.get("url")
        return data.get("thumbnail")
