from __future__ import annotations

from fastapi import APIRouter, WebSocket

from backend.core.security import verify_websocket_token

router = APIRouter(prefix="/api/v1", tags=["events"])


@router.websocket("/events")
async def events(websocket: WebSocket) -> None:
    if not await verify_websocket_token(websocket, websocket.app.state.config.session_token):
        return
    await websocket.accept()
    async for event in websocket.app.state.events.subscribe():
        await websocket.send_json(event)

