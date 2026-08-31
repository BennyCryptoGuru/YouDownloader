from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from backend.core.config import app_data_dir, default_download_dir


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


INITIAL_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    default_download_dir TEXT NOT NULL,
    default_preset TEXT NOT NULL DEFAULT 'video_mp4',
    default_quality TEXT NOT NULL DEFAULT 'best',
    concurrent_downloads INTEGER NOT NULL DEFAULT 1,
    conflict_policy TEXT NOT NULL DEFAULT 'skip',
    theme TEXT NOT NULL DEFAULT 'youtube',
    language TEXT NOT NULL DEFAULT 'en',
    open_folder_on_complete INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    title TEXT NOT NULL,
    source_id TEXT,
    channel TEXT,
    thumbnail_url TEXT,
    thumbnail_source_url TEXT,
    target_root TEXT NOT NULL,
    target_subfolder TEXT,
    preset TEXT NOT NULL,
    quality TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    current_item_index INTEGER,
    auto_attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    speed_bytes_per_second INTEGER,
    eta_seconds INTEGER,
    item_count INTEGER NOT NULL DEFAULT 1,
    completed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error_code TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS download_items (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES download_jobs(id) ON DELETE CASCADE,
    source_id TEXT,
    playlist_index INTEGER,
    title TEXT,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    speed_bytes_per_second INTEGER,
    eta_seconds INTEGER,
    downloaded_bytes INTEGER,
    total_bytes INTEGER,
    output_path TEXT,
    error_code TEXT,
    error_message TEXT,
    UNIQUE(job_id, playlist_index)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON download_jobs(status);
CREATE INDEX IF NOT EXISTS idx_items_job ON download_items(job_id, playlist_index);
"""

SETTINGS_CONFIG_FILENAME = "settings.json"
SETTINGS_CONFIG_KEYS = {
    "defaultDownloadDir": "default_download_dir",
    "defaultPreset": "default_preset",
    "defaultQuality": "default_quality",
    "concurrentDownloads": "concurrent_downloads",
    "conflictPolicy": "conflict_policy",
    "theme": "theme",
    "language": "language",
    "openFolderOnComplete": "open_folder_on_complete",
}


def default_settings_config_path() -> Path:
    return app_data_dir() / SETTINGS_CONFIG_FILENAME


class Database:
    def __init__(self, path: Path, settings_config_path: Path | None = None) -> None:
        self.path = path
        self.settings_config_path = settings_config_path or default_settings_config_path()
        self.connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.executescript(INITIAL_SQL)
        await self._ensure_columns()
        await self._ensure_duplicate_playlist_items_allowed()
        await self.connection.execute(
            """
            INSERT OR IGNORE INTO settings (
                id, default_download_dir, default_preset, default_quality,
                concurrent_downloads, conflict_policy, theme, language,
                open_folder_on_complete, updated_at
            ) VALUES (1, ?, 'video_mp4', 'best', 1, 'skip', 'youtube', 'en', 0, ?)
            """,
            (str(default_download_dir()), utc_now()),
        )
        await self._apply_settings_config_file()
        await self.connection.commit()
        await self.write_settings_config_file()

    async def close(self) -> None:
        if self.connection:
            await self.connection.close()
            self.connection = None

    def db(self) -> aiosqlite.Connection:
        if not self.connection:
            raise RuntimeError("Database is not connected")
        return self.connection

    async def _ensure_columns(self) -> None:
        settings_existing = await self.fetch_all("PRAGMA table_info(settings)")
        settings_column_names = {row["name"] for row in settings_existing}
        settings_migrations = {
            "language": "ALTER TABLE settings ADD COLUMN language TEXT NOT NULL DEFAULT 'en'",
        }
        for column, sql in settings_migrations.items():
            if column not in settings_column_names:
                await self.db().execute(sql)

        existing = await self.fetch_all("PRAGMA table_info(download_jobs)")
        column_names = {row["name"] for row in existing}
        migrations = {
            "current_item_index": "ALTER TABLE download_jobs ADD COLUMN current_item_index INTEGER",
            "auto_attempts": (
                "ALTER TABLE download_jobs ADD COLUMN auto_attempts INTEGER NOT NULL DEFAULT 0"
            ),
            "max_attempts": (
                "ALTER TABLE download_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 5"
            ),
            "speed_bytes_per_second": (
                "ALTER TABLE download_jobs ADD COLUMN speed_bytes_per_second INTEGER"
            ),
            "eta_seconds": "ALTER TABLE download_jobs ADD COLUMN eta_seconds INTEGER",
            "thumbnail_source_url": "ALTER TABLE download_jobs ADD COLUMN thumbnail_source_url TEXT",
        }
        for column, sql in migrations.items():
            if column not in column_names:
                await self.db().execute(sql)

        item_existing = await self.fetch_all("PRAGMA table_info(download_items)")
        item_column_names = {row["name"] for row in item_existing}
        item_migrations = {
            "speed_bytes_per_second": (
                "ALTER TABLE download_items ADD COLUMN speed_bytes_per_second INTEGER"
            ),
            "eta_seconds": "ALTER TABLE download_items ADD COLUMN eta_seconds INTEGER",
        }
        for column, sql in item_migrations.items():
            if column not in item_column_names:
                await self.db().execute(sql)
        await self.db().commit()

    async def _ensure_duplicate_playlist_items_allowed(self) -> None:
        table = await self.fetch_one(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'download_items'"
        )
        table_sql = (table or {}).get("sql") or ""
        if "UNIQUE(job_id, source_id)" not in table_sql:
            return

        await self.db().execute("PRAGMA foreign_keys = OFF")
        await self.db().execute(
            """
            CREATE TABLE download_items_new (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES download_jobs(id) ON DELETE CASCADE,
                source_id TEXT,
                playlist_index INTEGER,
                title TEXT,
                status TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                speed_bytes_per_second INTEGER,
                eta_seconds INTEGER,
                downloaded_bytes INTEGER,
                total_bytes INTEGER,
                output_path TEXT,
                error_code TEXT,
                error_message TEXT,
                UNIQUE(job_id, playlist_index)
            )
            """
        )
        await self.db().execute(
            """
            INSERT OR IGNORE INTO download_items_new (
                id, job_id, source_id, playlist_index, title, status, progress,
                speed_bytes_per_second, eta_seconds, downloaded_bytes, total_bytes,
                output_path, error_code, error_message
            )
            SELECT
                id, job_id, source_id, playlist_index, title, status, progress,
                NULL, NULL, downloaded_bytes, total_bytes, output_path, error_code, error_message
            FROM download_items
            """
        )
        await self.db().execute("DROP TABLE download_items")
        await self.db().execute("ALTER TABLE download_items_new RENAME TO download_items")
        await self.db().execute(
            "CREATE INDEX IF NOT EXISTS idx_items_job ON download_items(job_id, playlist_index)"
        )
        await self.db().execute("PRAGMA foreign_keys = ON")
        await self.db().commit()

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        async with self.db().execute(sql, params) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        async with self.db().execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        await self.db().execute(sql, params)
        await self.db().commit()

    async def execute_many(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        await self.db().executemany(sql, params)
        await self.db().commit()

    async def _apply_settings_config_file(self) -> None:
        values = self._read_settings_config_file()
        if not values:
            return
        values["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        await self.db().execute(
            f"UPDATE settings SET {assignments} WHERE id = 1",
            tuple(values.values()),
        )

    def _read_settings_config_file(self) -> dict[str, Any]:
        path = self.settings_config_path
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}

        values: dict[str, Any] = {}
        for file_key, db_key in SETTINGS_CONFIG_KEYS.items():
            value = payload.get(file_key)
            if value is None:
                value = payload.get(db_key)
            if value is None:
                continue
            if db_key == "open_folder_on_complete":
                value = int(bool(value))
            elif db_key == "concurrent_downloads":
                value = max(1, int(value))
            else:
                value = str(value)
            values[db_key] = value
        return values

    async def write_settings_config_file(self) -> None:
        row = await self.fetch_one("SELECT * FROM settings WHERE id = 1")
        if not row:
            return
        payload = {
            "defaultDownloadDir": row["default_download_dir"],
            "defaultPreset": row["default_preset"],
            "defaultQuality": row["default_quality"],
            "concurrentDownloads": row["concurrent_downloads"],
            "conflictPolicy": row["conflict_policy"],
            "theme": row["theme"],
            "language": row["language"],
            "openFolderOnComplete": bool(row["open_folder_on_complete"]),
            "updatedAt": row["updated_at"],
        }
        self.settings_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def job_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sourceUrl": row["source_url"],
        "kind": row["source_kind"],
        "sourceId": row["source_id"],
        "title": row["title"],
        "channel": row["channel"],
        "thumbnailUrl": row["thumbnail_url"],
        "thumbnailSourceUrl": row["thumbnail_source_url"],
        "targetRoot": row["target_root"],
        "targetSubfolder": row["target_subfolder"],
        "preset": row["preset"],
        "quality": row["quality"],
        "status": row["status"],
        "progress": row["progress"],
        "currentItemIndex": row["current_item_index"],
        "autoAttempts": row["auto_attempts"],
        "maxAttempts": row["max_attempts"],
        "speedBytesPerSecond": row["speed_bytes_per_second"],
        "etaSeconds": row["eta_seconds"],
        "itemCount": row["item_count"],
        "completedCount": row["completed_count"],
        "failedCount": row["failed_count"],
        "createdAt": row["created_at"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "errorCode": row["error_code"],
        "errorMessage": row["error_message"],
    }


def item_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "jobId": row["job_id"],
        "sourceId": row["source_id"],
        "playlistIndex": row["playlist_index"],
        "title": row["title"],
        "status": row["status"],
        "progress": row["progress"],
        "speedBytesPerSecond": row["speed_bytes_per_second"],
        "etaSeconds": row["eta_seconds"],
        "downloadedBytes": row["downloaded_bytes"],
        "totalBytes": row["total_bytes"],
        "outputPath": row["output_path"],
        "errorCode": row["error_code"],
        "errorMessage": row["error_message"],
    }


def settings_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "defaultDownloadDir": row["default_download_dir"],
        "defaultPreset": row["default_preset"],
        "defaultQuality": row["default_quality"],
        "concurrentDownloads": row["concurrent_downloads"],
        "conflictPolicy": row["conflict_policy"],
        "theme": row["theme"],
        "language": row["language"],
        "openFolderOnComplete": bool(row["open_folder_on_complete"]),
    }


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
