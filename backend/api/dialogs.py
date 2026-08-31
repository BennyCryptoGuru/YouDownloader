from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.core.errors import AppError
from backend.core.security import verify_header_token

router = APIRouter(prefix="/api/v1", tags=["dialogs"])


class SelectFolderRequest(BaseModel):
    initial_directory: str | None = Field(default=None, alias="initialDirectory")


@router.post("/dialogs/select-folder")
async def select_folder(payload: SelectFolderRequest, request: Request) -> dict[str, str | None]:
    verify_header_token(request.app.state.config.session_token, request.headers.get("X-Session-Token"))
    selected = await run_in_threadpool(_select_folder_dialog, payload.initial_directory)
    return {"path": selected}


def _select_folder_dialog(initial_directory: str | None) -> str | None:
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as exc:
        raise AppError(
            "DIALOG_UNAVAILABLE",
            "Systemovy dialog pro vyber slozky neni dostupny.",
            status_code=503,
        ) from exc

    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    initial_dir = _existing_initial_directory(initial_directory)
    try:
        selected = filedialog.askdirectory(
            parent=root,
            initialdir=initial_dir,
            title="Vyberte cilovou slozku",
            mustexist=False,
        )
    finally:
        root.destroy()

    return str(Path(selected).resolve()) if selected else None


def _existing_initial_directory(initial_directory: str | None) -> str:
    if initial_directory:
        path = Path(initial_directory).expanduser()
        if path.exists():
            return str(path)
        if path.parent.exists():
            return str(path.parent)
    return str(Path.home())

