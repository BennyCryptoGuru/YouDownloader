from __future__ import annotations

from fastapi import APIRouter, Request, Response

from backend.core.errors import AppError

router = APIRouter(prefix="/api/v1", tags=["thumbnails"])


@router.get("/thumbnails/{token}")
async def thumbnail(token: str, request: Request) -> Response:
    source = request.app.state.metadata.thumbnail_source_for_token(token)
    if not source:
        raise AppError("INVALID_URL", "Nahled uz neni v cache.", status_code=404)
    content, content_type = await request.app.state.thumbnails.get(token, source)
    return Response(content=content, media_type=content_type)

