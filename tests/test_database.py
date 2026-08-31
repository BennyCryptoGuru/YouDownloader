import sqlite3

import pytest

from backend.repositories.database import Database, utc_now
from backend.services.download_manager import DownloadManager
from backend.services.events import EventHub


class FakeMetadata:
    @staticmethod
    def thumbnail_source_from_video_id(video_id):
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None

    @staticmethod
    def register_thumbnail_source(source):
        return "/api/v1/thumbnails/test-token" if source else None


@pytest.mark.asyncio
async def test_migration_allows_duplicate_source_ids_in_one_playlist(tmp_path):
    db_path = tmp_path / "app.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE download_jobs (
            id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            title TEXT NOT NULL,
            source_id TEXT,
            channel TEXT,
            thumbnail_url TEXT,
            target_root TEXT NOT NULL,
            target_subfolder TEXT,
            preset TEXT NOT NULL,
            quality TEXT NOT NULL,
            status TEXT NOT NULL,
            progress REAL NOT NULL DEFAULT 0,
            item_count INTEGER NOT NULL DEFAULT 1,
            completed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error_code TEXT,
            error_message TEXT
        );

        CREATE TABLE download_items (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES download_jobs(id) ON DELETE CASCADE,
            source_id TEXT,
            playlist_index INTEGER,
            title TEXT,
            status TEXT NOT NULL,
            progress REAL NOT NULL DEFAULT 0,
            downloaded_bytes INTEGER,
            total_bytes INTEGER,
            output_path TEXT,
            error_code TEXT,
            error_message TEXT,
            UNIQUE(job_id, source_id)
        );
        """
    )
    connection.commit()
    connection.close()

    database = Database(db_path, tmp_path / "settings.json")
    await database.connect()
    columns = await database.fetch_all("PRAGMA table_info(download_jobs)")
    assert "thumbnail_source_url" in {column["name"] for column in columns}

    now = utc_now()
    await database.execute(
        """
        INSERT INTO download_jobs (
            id, source_url, source_kind, title, target_root, preset, quality,
            status, item_count, created_at
        ) VALUES (
            'job-1', 'https://youtube.com/playlist?list=PL', 'playlist',
            'Playlist', 'C:/Downloads', 'audio_mp3', '192', 'queued', 2, ?
        )
        """,
        (now,),
    )

    await database.execute_many(
        """
        INSERT INTO download_items (
            id, job_id, source_id, playlist_index, title, status
        ) VALUES (?, 'job-1', 'same-video', ?, ?, 'queued')
        """,
        [("item-1", 1, "First"), ("item-2", 2, "Second")],
    )

    rows = await database.fetch_all(
        "SELECT source_id, playlist_index FROM download_items ORDER BY playlist_index"
    )
    await database.close()

    assert rows == [
        {"source_id": "same-video", "playlist_index": 1},
        {"source_id": "same-video", "playlist_index": 2},
    ]


@pytest.mark.asyncio
async def test_remove_job_deletes_finished_job_from_queue_history(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "settings.json")
    await database.connect()
    job_id = "finished-job"
    await database.execute(
        """
        INSERT INTO download_jobs (
            id, source_url, source_kind, title, target_root, preset, quality,
            status, item_count, created_at
        ) VALUES (
            ?, 'https://youtube.com/watch?v=abc', 'video', 'Video',
            'C:/Downloads', 'video_mp4', 'best', 'cancelled', 1, ?
        )
        """,
        (job_id, utc_now()),
    )
    await database.execute(
        """
        INSERT INTO download_items (
            id, job_id, source_id, playlist_index, title, status
        ) VALUES ('item-1', ?, 'abc', 1, 'Video', 'cancelled')
        """,
        (job_id,),
    )
    manager = DownloadManager.__new__(DownloadManager)
    manager.database = database
    manager.metadata = FakeMetadata()
    manager.events = EventHub()

    await manager.remove_job(job_id)
    row = await database.fetch_one("SELECT id FROM download_jobs WHERE id = ?", (job_id,))
    item = await database.fetch_one("SELECT id FROM download_items WHERE job_id = ?", (job_id,))
    await database.close()

    assert row is None
    assert item is None


@pytest.mark.asyncio
async def test_remove_job_deletes_active_job_from_queue_history(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "settings.json")
    await database.connect()
    job_id = "active-job"
    await database.execute(
        """
        INSERT INTO download_jobs (
            id, source_url, source_kind, title, target_root, preset, quality,
            status, item_count, created_at
        ) VALUES (
            ?, 'https://youtube.com/watch?v=abc', 'video', 'Video',
            'C:/Downloads', 'video_mp4', 'best', 'downloading', 1, ?
        )
        """,
        (job_id, utc_now()),
    )
    await database.execute(
        """
        INSERT INTO download_items (
            id, job_id, source_id, playlist_index, title, status
        ) VALUES ('item-1', ?, 'abc', 1, 'Video', 'downloading')
        """,
        (job_id,),
    )
    manager = DownloadManager.__new__(DownloadManager)
    manager.database = database
    manager.metadata = FakeMetadata()
    manager.events = EventHub()
    manager.active_processes = {}

    await manager.remove_job(job_id)
    row = await database.fetch_one("SELECT id FROM download_jobs WHERE id = ?", (job_id,))
    item = await database.fetch_one("SELECT id FROM download_items WHERE job_id = ?", (job_id,))
    await database.close()

    assert row is None
    assert item is None


@pytest.mark.asyncio
async def test_cancel_playlist_marks_unfinished_items_cancelled(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "settings.json")
    await database.connect()
    job_id = "playlist-cancel"
    await database.execute(
        """
        INSERT INTO download_jobs (
            id, source_url, source_kind, title, target_root, preset, quality,
            status, item_count, completed_count, created_at
        ) VALUES (
            ?, 'https://youtube.com/playlist?list=PL', 'playlist', 'Playlist',
            'C:/Downloads', 'video_mp4', 'best', 'downloading', 3, 1, ?
        )
        """,
        (job_id, utc_now()),
    )
    await database.execute_many(
        """
        INSERT INTO download_items (
            id, job_id, source_id, playlist_index, title, status, progress
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("item-1", job_id, "video-1", 1, "Hotovo", "completed", 100),
            ("item-2", job_id, "video-2", 2, "Aktuální", "downloading", 42),
            ("item-3", job_id, "video-3", 3, "Čeká", "queued", 0),
        ],
    )
    manager = DownloadManager.__new__(DownloadManager)
    manager.database = database
    manager.metadata = FakeMetadata()
    manager.events = EventHub()
    manager.active_processes = {}
    manager.cancel_requested = set()

    job = await manager.cancel_job(job_id)
    rows = await database.fetch_all(
        "SELECT playlist_index, status FROM download_items WHERE job_id = ? ORDER BY playlist_index",
        (job_id,),
    )
    await database.close()

    assert job["status"] == "cancelled"
    assert rows == [
        {"playlist_index": 1, "status": "completed"},
        {"playlist_index": 2, "status": "cancelled"},
        {"playlist_index": 3, "status": "cancelled"},
    ]


@pytest.mark.asyncio
async def test_sync_existing_downloaded_items_fixes_false_completed_items(tmp_path):
    playlist_dir = tmp_path / "downloads" / "Playlist"
    playlist_dir.mkdir(parents=True)
    (playlist_dir / "001 - One [video-1].mp4").write_text("ok", encoding="utf-8")

    database = Database(tmp_path / "app.db", tmp_path / "settings.json")
    await database.connect()
    job_id = "playlist-sync"
    await database.execute(
        """
        INSERT INTO download_jobs (
            id, source_url, source_kind, title, target_root, target_subfolder,
            preset, quality, status, item_count, completed_count, created_at
        ) VALUES (
            ?, 'https://youtube.com/playlist?list=PL', 'playlist', 'Playlist',
            ?, 'Playlist', 'video_mp4', 'best', 'queued', 3, 3, ?
        )
        """,
        (job_id, str(tmp_path / "downloads"), utc_now()),
    )
    await database.execute_many(
        """
        INSERT INTO download_items (
            id, job_id, source_id, playlist_index, title, status, progress
        ) VALUES (?, ?, ?, ?, ?, 'completed', 100)
        """,
        [
            ("item-1", job_id, "video-1", 1, "One"),
            ("item-2", job_id, "video-2", 2, "Two"),
            ("item-3", job_id, "video-3", 3, "Three"),
        ],
    )
    manager = DownloadManager.__new__(DownloadManager)
    manager.database = database
    manager.metadata = FakeMetadata()
    manager.events = EventHub()

    job = await manager.get_job(job_id)
    await manager._sync_existing_downloaded_items(job)
    rows = await database.fetch_all(
        "SELECT playlist_index, status FROM download_items WHERE job_id = ? ORDER BY playlist_index",
        (job_id,),
    )
    stored = await database.fetch_one(
        "SELECT completed_count, current_item_index FROM download_jobs WHERE id = ?",
        (job_id,),
    )
    await database.close()

    assert rows == [
        {"playlist_index": 1, "status": "completed"},
        {"playlist_index": 2, "status": "queued"},
        {"playlist_index": 3, "status": "queued"},
    ]
    assert stored["completed_count"] == 1
    assert stored["current_item_index"] == 2


@pytest.mark.asyncio
async def test_sync_existing_downloaded_items_resumes_after_highest_completed_gap(tmp_path):
    playlist_dir = tmp_path / "downloads" / "Playlist"
    playlist_dir.mkdir(parents=True)
    (playlist_dir / "001 - One [video-1].mp4").write_text("ok", encoding="utf-8")
    (playlist_dir / "003 - Three [video-3].mp4").write_text("ok", encoding="utf-8")

    database = Database(tmp_path / "app.db", tmp_path / "settings.json")
    await database.connect()
    job_id = "playlist-gap-resume"
    await database.execute(
        """
        INSERT INTO download_jobs (
            id, source_url, source_kind, title, target_root, target_subfolder,
            preset, quality, status, item_count, completed_count,
            current_item_index, created_at
        ) VALUES (
            ?, 'https://youtube.com/playlist?list=PL', 'playlist', 'Playlist',
            ?, 'Playlist', 'video_mp4', 'best', 'queued', 4, 0, 2, ?
        )
        """,
        (job_id, str(tmp_path / "downloads"), utc_now()),
    )
    await database.execute_many(
        """
        INSERT INTO download_items (
            id, job_id, source_id, playlist_index, title, status, progress
        ) VALUES (?, ?, ?, ?, ?, 'queued', 0)
        """,
        [
            ("item-1", job_id, "video-1", 1, "One"),
            ("item-2", job_id, "video-2", 2, "Two"),
            ("item-3", job_id, "video-3", 3, "Three"),
            ("item-4", job_id, "video-4", 4, "Four"),
        ],
    )
    manager = DownloadManager.__new__(DownloadManager)
    manager.database = database
    manager.metadata = FakeMetadata()
    manager.events = EventHub()

    job = await manager.get_job(job_id)
    await manager._sync_existing_downloaded_items(job)
    rows = await database.fetch_all(
        "SELECT playlist_index, status FROM download_items WHERE job_id = ? ORDER BY playlist_index",
        (job_id,),
    )
    stored = await database.fetch_one(
        "SELECT completed_count, current_item_index FROM download_jobs WHERE id = ?",
        (job_id,),
    )
    await database.close()

    assert rows == [
        {"playlist_index": 1, "status": "completed"},
        {"playlist_index": 2, "status": "queued"},
        {"playlist_index": 3, "status": "completed"},
        {"playlist_index": 4, "status": "queued"},
    ]
    assert stored["completed_count"] == 2
    assert stored["current_item_index"] == 4


@pytest.mark.asyncio
async def test_job_response_restores_thumbnail_from_first_playlist_item(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "settings.json")
    await database.connect()
    job_id = "playlist-job"
    await database.execute(
        """
        INSERT INTO download_jobs (
            id, source_url, source_kind, title, target_root, preset, quality,
            status, item_count, created_at
        ) VALUES (
            ?, 'https://youtube.com/playlist?list=PL', 'playlist', 'Playlist',
            'C:/Downloads', 'video_mp4', 'best', 'queued', 1, ?
        )
        """,
        (job_id, utc_now()),
    )
    await database.execute(
        """
        INSERT INTO download_items (
            id, job_id, source_id, playlist_index, title, status
        ) VALUES ('item-1', ?, 'abc123', 1, 'First video', 'queued')
        """,
        (job_id,),
    )

    manager = DownloadManager.__new__(DownloadManager)
    manager.database = database
    manager.metadata = FakeMetadata()

    job = await manager.get_job(job_id)
    stored = await database.fetch_one(
        "SELECT thumbnail_source_url, thumbnail_url FROM download_jobs WHERE id = ?",
        (job_id,),
    )
    await database.close()

    assert job["thumbnailUrl"] == "/api/v1/thumbnails/test-token"
    assert stored["thumbnail_source_url"] == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"
    assert stored["thumbnail_url"] == "/api/v1/thumbnails/test-token"


@pytest.mark.asyncio
async def test_settings_config_file_survives_database_restart(tmp_path):
    config_path = tmp_path / "settings.json"
    database = Database(tmp_path / "app.db", config_path)
    await database.connect()
    await database.execute(
        """
        UPDATE settings
        SET default_download_dir = ?,
            default_preset = 'audio_mp3',
            default_quality = '192',
            theme = 'dark',
            language = 'de',
            updated_at = ?
        WHERE id = 1
        """,
        ("C:/Music/Test", utc_now()),
    )
    await database.write_settings_config_file()
    await database.close()

    restarted = Database(tmp_path / "app.db", config_path)
    await restarted.connect()
    row = await restarted.fetch_one("SELECT * FROM settings WHERE id = 1")
    await restarted.close()

    assert row["default_download_dir"] == "C:/Music/Test"
    assert row["default_preset"] == "audio_mp3"
    assert row["default_quality"] == "192"
    assert row["theme"] == "dark"
    assert row["language"] == "de"
