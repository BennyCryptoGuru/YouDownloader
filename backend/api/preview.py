from __future__ import annotations

from fastapi import APIRouter, Request

from backend.core.security import verify_header_token
from backend.domain.models import PreviewRequest

router = APIRouter(prefix="/api/v1", tags=["preview"])


@router.post("/preview")
async def preview(payload: PreviewRequest, request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    response = await request.app.state.metadata.preview(payload.source_url, payload.scope)
    return response.model_dump(by_alias=True)


@router.get("/presets")
async def presets(request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    from backend.domain.presets import preset_list

    return {"presets": preset_list()}

