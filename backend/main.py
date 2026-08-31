from __future__ import annotations

import argparse
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api import dialogs, jobs, preview, settings, thumbnails, websocket
from backend.core.config import FRONTEND_DIR, AppConfig
from backend.core.errors import AppError, message_for
from backend.repositories.database import Database
from backend.services.download_manager import DownloadManager
from backend.services.events import EventHub
from backend.services.metadata_service import MetadataService
from backend.services.thumbnail_cache import ThumbnailCache
from backend.services.ytdlp import YtDlp


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> HTMLResponse:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    config: AppConfig = app.state.config
    database = Database(config.database_path, config.settings_config_path)
    await database.connect()
    events = EventHub()
    thumbnails_cache = ThumbnailCache(config.thumbnail_dir)
    ytdlp = YtDlp(config.ytdlp_path, config.ffmpeg_path, config.js_runtime)
    metadata = MetadataService(ytdlp, thumbnails_cache)
    downloads = DownloadManager(database, metadata, ytdlp, events)

    app.state.database = database
    app.state.events = events
    app.state.thumbnails = thumbnails_cache
    app.state.ytdlp = ytdlp
    app.state.metadata = metadata
    app.state.downloads = downloads

    await downloads.start()
    try:
        yield
    finally:
        await downloads.stop()
        await database.close()


def create_app(config: AppConfig) -> FastAPI:
    app = FastAPI(title="YouDownloader", version="0.1.0", lifespan=lifespan)
    app.state.config = config

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message or message_for(exc.code)}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)[-500:]}},
        )

    @app.get("/")
    async def index() -> HTMLResponse:
        html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace("%SESSION_TOKEN%", config.session_token)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.mount("/static", NoCacheStaticFiles(directory=FRONTEND_DIR), name="static")
    app.include_router(preview.router)
    app.include_router(settings.router)
    app.include_router(jobs.router)
    app.include_router(dialogs.router)
    app.include_router(thumbnails.router)
    app.include_router(websocket.router)
    return app


def run_server(config: AppConfig) -> None:
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level="info",
        access_log=False,
    )


def run_desktop(config: AppConfig) -> None:
    try:
        import webview
    except ImportError:
        print("pywebview neni nainstalovany. Spoustim pouze server.")
        run_server(config)
        return

    server_thread = threading.Thread(target=run_server, args=(config,), daemon=True)
    server_thread.start()
    url = f"http://{config.host}:{config.port}/"
    webview.create_window("YouDownloader", url, width=1200, height=820, min_size=(920, 640))
    webview.start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouDownloader")
    parser.add_argument("--server", action="store_true", help="Spustit jen lokalni webovy server.")
    parser.add_argument("--port", type=int, default=None, help="Port pro lokalni server.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = AppConfig.create(args.port)
    print(f"YouDownloader bezi na http://{config.host}:{config.port}/")
    if args.server:
        run_server(config)
    else:
        run_desktop(config)


if __name__ == "__main__":
    main()
