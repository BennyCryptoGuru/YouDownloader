from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from backend.core.errors import AppError
from backend.core.security import verify_header_token
from backend.domain.models import SettingsPatch
from backend.repositories.database import settings_to_api, utc_now

router = APIRouter(prefix="/api/v1", tags=["settings"])

ALLOWED_FIELDS = {
    "default_download_dir",
    "default_preset",
    "default_quality",
    "concurrent_downloads",
    "conflict_policy",
    "theme",
    "language",
    "open_folder_on_complete",
}


@router.get("/settings")
async def get_settings(request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    row = await request.app.state.database.fetch_one("SELECT * FROM settings WHERE id = 1")
    return settings_to_api(row)


@router.patch("/settings")
async def patch_settings(payload: SettingsPatch, request: Request) -> dict:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    values = payload.model_dump(exclude_unset=True)
    if values.get("default_download_dir"):
        path = Path(values["default_download_dir"]).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AppError("TARGET_NOT_WRITABLE", "Slozku nelze vytvorit.") from exc

    if not values:
        row = await request.app.state.database.fetch_one("SELECT * FROM settings WHERE id = 1")
        return settings_to_api(row)

    values["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in values if key in ALLOWED_FIELDS or key == "updated_at")
    params = tuple(values[key] for key in values if key in ALLOWED_FIELDS or key == "updated_at")
    await request.app.state.database.execute(
        f"UPDATE settings SET {assignments} WHERE id = 1",
        params,
    )
    row = await request.app.state.database.fetch_one("SELECT * FROM settings WHERE id = 1")
    await request.app.state.database.write_settings_config_file()
    return settings_to_api(row)
