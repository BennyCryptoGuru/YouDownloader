from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psutil

from backend.core.errors import AppError
from backend.domain.models import JobCreateRequest
from backend.domain.presets import ytdlp_args_for_preset
from backend.repositories.database import Database, item_to_api, job_to_api, utc_now
from backend.services.events import EventHub
from backend.services.filename import sanitize_filename
from backend.services.metadata_service import MetadataService
from backend.services.ytdlp import YtDlp

PROGRESS_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
SPEED_RE = re.compile(r"\bat\s+([0-9.]+)([KMG]i?B|B)/s", re.IGNORECASE)
ETA_RE = re.compile(r"\bETA\s+([0-9:]+|Unknown)", re.IGNORECASE)
PLAYLIST_ITEM_RE = re.compile(r"\[download\]\s+Downloading item (?P<index>\d+) of (?P<count>\d+)")
ALREADY_DOWNLOADED_RE = re.compile(r"\[download\]\s+(.+)\s+has already been downloaded")
YTDLP_ITEM_RE = re.compile(r"^__YDL_ITEM__(?P<index>\d+)\t(?P<id>[^\t]*)\t(?P<title>.*)$")
YTDLP_PROGRESS_RE = re.compile(
    r"__YDL_PROGRESS__(?P<percent>[^\t]*)\t(?P<speed>[^\t]*)\t(?P<eta>[^\t\r\n]*)"
    r"(?:\t(?P<downloaded>[^\t\r\n]*)\t(?P<total>[^\t\r\n]*)\t(?P<estimated>[^\t\r\n]*))?"
)
SPEED_VALUE_RE = re.compile(r"([0-9.]+)\s*([KMG]i?B|B)/s", re.IGNORECASE)
FILE_VIDEO_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{6,})\]\.[^.]+$")

AUTO_RETRY_ATTEMPTS = 5
NETWORK_CHECK_INTERVAL_SECONDS = 5
NETWORK_WAIT_TIMEOUT_SECONDS = 30 * 60
YTDLP_OUTPUT_IDLE_TIMEOUT_SECONDS = 300
YTDLP_READ_POLL_SECONDS = 1
RETRYABLE_CODES = {"NETWORK_ERROR"}
NON_RETRYABLE_HINTS = (
    "private video",
    "video unavailable",
    "sign in to confirm",
    "this video is not available",
    "members-only",
    "requested format is not available",
)


class DownloadManager:
    def __init__(
        self,
        database: Database,
        metadata: MetadataService,
        ytdlp: YtDlp,
        events: EventHub,
    ) -> None:
        self.database = database
        self.metadata = metadata
        self.ytdlp = ytdlp
        self.events = events
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker_task: asyncio.Task | None = None
        self.running_jobs: set[str] = set()
        self.cancel_requested: set[str] = set()
        self.active_processes: dict[str, asyncio.subprocess.Process] = {}
        self.total_size_estimates: dict[tuple[str, str, str], int | None] = {}

    async def start(self) -> None:
        await self._requeue_interrupted()
        await self._enqueue_queued_jobs()
        if not self.worker_task or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self.worker_task:
            self.worker_task.cancel()
        for job_id in list(self.active_processes):
            await self.cancel_job(job_id)

    async def create_job(self, request: JobCreateRequest) -> dict[str, Any]:
        preview = await self.metadata.preview(request.source_url, request.scope)
        settings = await self.database.fetch_one("SELECT * FROM settings WHERE id = 1")
        if not settings:
            raise AppError("TARGET_NOT_WRITABLE", "Nastaveni nebylo nalezeno.")

        target_root = Path(request.target_directory or settings["default_download_dir"]).expanduser()
        self._ensure_writable_directory(target_root)

        target_subfolder = sanitize_filename(preview.title) if preview.kind == "playlist" else None
        job_id = str(uuid.uuid4())
        created_at = utc_now()
        await self.database.execute(
            """
            INSERT INTO download_jobs (
                id, source_url, source_kind, title, source_id, channel, thumbnail_url,
                thumbnail_source_url, target_root, target_subfolder, preset, quality, status, progress,
                item_count, completed_count, failed_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, 0, 0, ?)
            """,
            (
                job_id,
                preview.source_url,
                preview.kind,
                preview.title,
                preview.id,
                preview.channel,
                preview.thumbnail_url,
                preview.thumbnail_source_url,
                str(target_root),
                target_subfolder,
                request.preset,
                request.quality,
                preview.item_count or 1,
                created_at,
            ),
        )

        if preview.items:
            await self.database.execute_many(
                """
                INSERT INTO download_items (
                    id, job_id, source_id, playlist_index, title, status
                ) VALUES (?, ?, ?, ?, ?, 'queued')
                """,
                [
                    (
                        str(uuid.uuid4()),
                        job_id,
                        item.id,
                        item.index,
                        item.title,
                    )
                    for item in preview.items
                ],
            )
        else:
            await self.database.execute(
                """
                INSERT INTO download_items (
                    id, job_id, source_id, playlist_index, title, status
                ) VALUES (?, ?, ?, 1, ?, 'queued')
                """,
                (str(uuid.uuid4()), job_id, preview.id, preview.title),
            )

        job = await self.get_job(job_id)
        await self._sync_existing_downloaded_items(job)
        await self.queue.put(job_id)
        job = await self.get_job(job_id)
        await self.events.publish({"type": "job.created", "job": job})
        return job

    async def list_jobs(self) -> list[dict[str, Any]]:
        rows = await self.database.fetch_all(
            "SELECT * FROM download_jobs ORDER BY created_at DESC"
        )
        if await self._recover_jobs_without_live_process(rows):
            rows = await self.database.fetch_all(
                "SELECT * FROM download_jobs ORDER BY created_at DESC"
            )
        return [await self._job_with_items(row) for row in rows]

    async def get_job(self, job_id: str) -> dict[str, Any]:
        row = await self.database.fetch_one("SELECT * FROM download_jobs WHERE id = ?", (job_id,))
        if not row:
            raise AppError("JOB_NOT_FOUND", "Uloha nebyla nalezena.", status_code=404)
        return await self._job_with_items(row)

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        self.cancel_requested.add(job_id)
        process = self.active_processes.get(job_id)
        if process and process.returncode is None:
            self._terminate_tree(process.pid)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                self._kill_tree(process.pid)
                await process.wait()
        await self._cancel_unfinished_items(job_id)
        await self._update_job(job_id, status="cancelled", finished_at=utc_now())
        return await self.get_job(job_id)

    async def pause_job(self, job_id: str) -> dict[str, Any]:
        process = self.active_processes.get(job_id)
        if not process or process.returncode is not None:
            raise AppError("PROCESS_NOT_FOUND", "Uloha prave nebezi.", status_code=404)
        self._walk_process_tree(process.pid, lambda proc: proc.suspend())
        await self._update_job(job_id, status="paused")
        return await self.get_job(job_id)

    async def resume_job(self, job_id: str) -> dict[str, Any]:
        process = self.active_processes.get(job_id)
        if process and process.returncode is None:
            self._walk_process_tree(process.pid, lambda proc: proc.resume())
            await self._update_job(job_id, status="downloading")
        else:
            await self.queue.put(job_id)
            await self._update_job(job_id, status="queued")
        return await self.get_job(job_id)

    async def retry_failed(self, job_id: str) -> dict[str, Any]:
        job = await self.get_job(job_id)
        if job["kind"] == "playlist":
            await self._reset_incomplete_playlist_items(job_id)
            await self._sync_existing_downloaded_items(job)
            synced_job = await self.get_job(job_id)
            resume_index = await self._resume_playlist_item_index(synced_job)
            await self._update_job(
                job_id,
                status="queued",
                progress=0,
                current_item_index=resume_index,
                auto_attempts=0,
                speed_bytes_per_second=None,
                eta_seconds=None,
                error_code=None,
                error_message=None,
                finished_at=None,
            )
        else:
            await self._update_job(
                job_id,
                status="queued",
                progress=0,
                auto_attempts=0,
                speed_bytes_per_second=None,
                eta_seconds=None,
                error_code=None,
                error_message=None,
                finished_at=None,
            )
        await self.queue.put(job_id)
        return await self.get_job(job_id)

    async def remove_job(self, job_id: str) -> None:
        await self.get_job(job_id)
        cancel_requested = getattr(self, "cancel_requested", set())
        cancel_requested.add(job_id)
        self.cancel_requested = cancel_requested
        process = getattr(self, "active_processes", {}).get(job_id)
        if process and process.returncode is None:
            self._terminate_tree(process.pid)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                self._kill_tree(process.pid)
                await process.wait()
        await self.database.execute("DELETE FROM download_jobs WHERE id = ?", (job_id,))
        self.cancel_requested.discard(job_id)
        await self.events.publish({"type": "job.removed", "jobId": job_id})

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                job = await self.get_job(job_id)
                if job["status"] in {"cancelled", "completed"}:
                    continue
                self.cancel_requested.discard(job_id)
                self.running_jobs.add(job_id)
                await self._run_job_with_retries(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - worker boundary converts failures to job state
                latest = await self._try_get_job(job_id)
                if latest is None or latest["status"] == "cancelled":
                    continue
                message = str(exc)[-500:]
                code = exc.code if isinstance(exc, AppError) else "NETWORK_ERROR"
                await self._update_job(
                    job_id,
                    status="failed",
                    error_code=code,
                    error_message=message,
                    finished_at=utc_now(),
                )
                await self.events.publish(
                    {"type": "job.failed", "jobId": job_id, "code": code, "message": message}
                )
            finally:
                self.active_processes.pop(job_id, None)
                self.running_jobs.discard(job_id)
                self.queue.task_done()

    async def _job_with_items(self, row: dict[str, Any]) -> dict[str, Any]:
        job = job_to_api(row)
        items = await self.database.fetch_all(
            """
            SELECT *
            FROM download_items
            WHERE job_id = ?
            ORDER BY playlist_index
            """,
            (row["id"],),
        )
        job["items"] = [item_to_api(item) for item in items]
        await self._ensure_job_thumbnail(job, row, items)
        return job

    async def _ensure_job_thumbnail(
        self,
        job: dict[str, Any],
        row: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> None:
        source = row.get("thumbnail_source_url")
        if not source:
            video_id = row.get("source_id")
            if (row.get("source_kind") == "playlist" or not video_id) and items:
                video_id = items[0].get("source_id")
            source = self.metadata.thumbnail_source_from_video_id(video_id)
        thumbnail_url = self.metadata.register_thumbnail_source(source)
        if thumbnail_url:
            job["thumbnailUrl"] = thumbnail_url
            job["thumbnailSourceUrl"] = source
            if row.get("thumbnail_source_url") != source or row.get("thumbnail_url") != thumbnail_url:
                await self.database.execute(
                    """
                    UPDATE download_jobs
                    SET thumbnail_source_url = ?,
                        thumbnail_url = ?
                    WHERE id = ?
                    """,
                    (source, thumbnail_url, row["id"]),
                )

    async def _try_get_job(self, job_id: str) -> dict[str, Any] | None:
        try:
            return await self.get_job(job_id)
        except AppError as exc:
            if exc.code == "JOB_NOT_FOUND":
                return None
            raise

    async def _run_job_with_retries(self, job: dict[str, Any]) -> None:
        max_attempts = int(job.get("maxAttempts") or AUTO_RETRY_ATTEMPTS)
        attempt = int(job.get("autoAttempts") or 0)
        while attempt < max_attempts:
            latest = await self.get_job(job["id"])
            if self._is_cancel_requested(job["id"]) or latest["status"] in {"cancelled", "completed"}:
                return
            try:
                if self._is_cancel_requested(job["id"]):
                    return
                await self._run_job(latest)
                return
            except AppError as exc:
                attempt += 1
                if exc.code not in RETRYABLE_CODES:
                    raise
                if attempt >= max_attempts:
                    latest = await self.get_job(job["id"])
                    if await self._skip_current_playlist_item(latest, exc.message):
                        attempt = 0
                        continue
                    raise
                await self._wait_for_network(job["id"], attempt, max_attempts, exc.message)
        raise AppError("NETWORK_ERROR", "Automaticke opakovani bylo vycerpano.")

    async def _run_job(self, job: dict[str, Any]) -> None:
        if job["kind"] == "playlist":
            await self._reset_incomplete_playlist_items(job["id"])
            await self._sync_existing_downloaded_items(job)
            synced_job = await self.get_job(job["id"])
            resume_index = await self._resume_playlist_item_index(synced_job)
            if resume_index > int(job.get("itemCount") or 1):
                await self._complete_job_from_item_counts(job["id"])
                return
            job = await self.get_job(job["id"])
            job["resumeFromIndex"] = resume_index
        else:
            job["resumeFromIndex"] = 1

        await self._update_job(
            job["id"],
            status="downloading",
            started_at=utc_now(),
            finished_at=None,
            error_code=None,
            error_message=None,
            current_item_index=job["resumeFromIndex"] if job["kind"] == "playlist" else None,
            progress=0,
            speed_bytes_per_second=None,
            eta_seconds=None,
        )
        args = self._download_args(job)
        target = Path(job["targetRoot"])
        target.mkdir(parents=True, exist_ok=True)

        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self.active_processes[job["id"]] = process
        assert process.stdout is not None
        last_progress = -1.0
        last_publish = datetime.now(UTC)
        playlist_start_index = int(job.get("resumeFromIndex") or job.get("currentItemIndex") or 1)
        current_item_index = playlist_start_index
        seen_item_marker = False
        output_tail: list[str] = []
        last_activity = datetime.now(UTC)
        last_disk_bytes: int | None = None
        last_disk_sample_at = last_activity
        try:
            while True:
                if self._is_cancel_requested(job["id"]):
                    return
                try:
                    raw_line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=YTDLP_READ_POLL_SECONDS,
                    )
                except TimeoutError as exc:
                    now = datetime.now(UTC)
                    disk_bytes = self._current_download_part_size(job, current_item_index)
                    if disk_bytes is not None:
                        elapsed = (now - last_disk_sample_at).total_seconds()
                        total_bytes = await self._current_download_total_bytes(
                            job["id"],
                            current_item_index,
                        )
                        if not total_bytes:
                            total_bytes = await self._estimate_current_item_total_bytes(
                                job,
                                current_item_index,
                            )
                        progress = self._progress_from_bytes(disk_bytes, total_bytes)
                        if (
                            last_disk_bytes is not None
                            and elapsed > 0
                            and disk_bytes > last_disk_bytes
                        ):
                            disk_speed = int((disk_bytes - last_disk_bytes) / elapsed)
                            last_activity = now
                            if (now - last_publish).total_seconds() >= 0.4:
                                last_publish = now
                                await self._publish_progress_update(
                                    job,
                                    current_item_index,
                                    progress,
                                    disk_speed,
                                    None,
                                    disk_bytes,
                                    total_bytes,
                                )
                        last_disk_bytes = disk_bytes
                        last_disk_sample_at = now

                    if (now - last_activity).total_seconds() < YTDLP_OUTPUT_IDLE_TIMEOUT_SECONDS:
                        continue

                    await self._update_job(
                        job["id"],
                        status="waiting_for_network",
                        error_code="NETWORK_ERROR",
                        error_message=(
                            "Stahovani dlouho neposlalo zadny vystup. "
                            "Ukoncuji zasekly proces a zkusim navazat znovu."
                        ),
                    )
                    self._terminate_tree(process.pid)
                    try:
                        await asyncio.wait_for(process.wait(), timeout=10)
                    except TimeoutError:
                        self._kill_tree(process.pid)
                        await process.wait()
                    raise AppError(
                        "NETWORK_ERROR",
                        "yt-dlp dlouho neposlal zadny vystup. Uloha se automaticky spusti znovu.",
                    ) from exc
                if not raw_line:
                    break
                if self._is_cancel_requested(job["id"]):
                    return
                last_activity = datetime.now(UTC)
                line = raw_line.decode("utf-8", "replace").strip()
                if line:
                    output_tail = [*output_tail[-24:], line]
                lowered = line.lower()
                ytdlp_item_match = YTDLP_ITEM_RE.match(line)
                if ytdlp_item_match:
                    seen_item_marker = True
                    next_item_index = int(ytdlp_item_match.group("index"))
                    if next_item_index != current_item_index:
                        await self._finalize_playlist_item_from_disk(job, current_item_index)
                    current_item_index = next_item_index
                    last_progress = -1.0
                    await self._update_item(
                        job["id"],
                        current_item_index,
                        source_id=ytdlp_item_match.group("id") or None,
                        title=ytdlp_item_match.group("title") or None,
                        status="downloading",
                        progress=0,
                        speed_bytes_per_second=None,
                        eta_seconds=None,
                    )
                    counts = await self._item_counts(job["id"])
                    await self._update_job(
                        job["id"],
                        status="downloading",
                        progress=0,
                        current_item_index=current_item_index,
                        completed_count=counts["completed"],
                        failed_count=counts["failed"],
                        speed_bytes_per_second=None,
                        eta_seconds=None,
                    )
                    continue
                ytdlp_progress_match = YTDLP_PROGRESS_RE.search(line)
                if ytdlp_progress_match:
                    progress = self._parse_progress_percent(ytdlp_progress_match.group("percent"))
                    speed = self._parse_speed_value(ytdlp_progress_match.group("speed"))
                    eta = self._parse_eta_value(ytdlp_progress_match.group("eta"))
                    downloaded_bytes = self._parse_byte_count(
                        ytdlp_progress_match.group("downloaded")
                    )
                    total_bytes = self._parse_byte_count(ytdlp_progress_match.group("total"))
                    estimated_bytes = self._parse_byte_count(
                        ytdlp_progress_match.group("estimated")
                    )
                    total_or_estimated_bytes = total_bytes or estimated_bytes
                    if progress is None:
                        progress = self._progress_from_bytes(
                            downloaded_bytes,
                            total_or_estimated_bytes,
                        )
                    now = datetime.now(UTC)
                    if (
                        (
                            progress is not None
                            or speed is not None
                            or eta is not None
                            or downloaded_bytes is not None
                            or total_or_estimated_bytes is not None
                        )
                        and (
                            progress is None
                            or progress != last_progress
                            or speed is not None
                            or eta is not None
                        )
                        and (now - last_publish).total_seconds() >= 0.4
                    ):
                        if progress is not None:
                            last_progress = progress
                        last_publish = now
                        await self._publish_progress_update(
                            job,
                            current_item_index,
                            progress,
                            speed,
                            eta,
                            downloaded_bytes,
                            total_or_estimated_bytes,
                        )
                    continue
                item_match = PLAYLIST_ITEM_RE.search(line)
                if item_match:
                    relative_item_index = int(item_match.group("index"))
                    relative_item_count = int(item_match.group("count"))
                    item_count = max(
                        int(job["itemCount"]),
                        playlist_start_index + relative_item_count - 1,
                    )
                    if not seen_item_marker:
                        next_item_index = playlist_start_index + relative_item_index - 1
                        if next_item_index != current_item_index:
                            await self._finalize_playlist_item_from_disk(job, current_item_index)
                        current_item_index = next_item_index
                        last_progress = -1.0
                        await self._update_item(
                            job["id"],
                            current_item_index,
                            status="downloading",
                            progress=0,
                            speed_bytes_per_second=None,
                            eta_seconds=None,
                        )
                    counts = await self._item_counts(job["id"])
                    await self._update_job(
                        job["id"],
                        status="downloading",
                        progress=0,
                        current_item_index=current_item_index,
                        item_count=item_count,
                        completed_count=counts["completed"],
                        failed_count=counts["failed"],
                        speed_bytes_per_second=None,
                        eta_seconds=None,
                    )
                if "postprocess" in lowered or "extractaudio" in lowered or "merging formats" in lowered:
                    await self._update_job(job["id"], status="postprocessing")
                    await self._update_item(job["id"], current_item_index, status="postprocessing")
                    await self.events.publish(
                        {"type": "job.status", "jobId": job["id"], "status": "postprocessing"}
                    )
                if ALREADY_DOWNLOADED_RE.search(line):
                    await self._update_item(
                        job["id"],
                        current_item_index,
                        status="completed",
                        progress=100,
                    )
                    counts = await self._item_counts(job["id"])
                    await self._update_job(
                        job["id"],
                        completed_count=counts["completed"],
                        failed_count=counts["failed"],
                    )
                match = PROGRESS_RE.search(line)
                if match:
                    progress = max(0.0, min(100.0, float(match.group(1))))
                    speed = self._parse_speed(line)
                    eta = self._parse_eta(line)
                    now = datetime.now(UTC)
                    if (
                        (
                            progress != last_progress
                            or speed is not None
                            or eta is not None
                        )
                        and (now - last_publish).total_seconds() >= 0.4
                    ):
                        last_progress = progress
                        last_publish = now
                        await self._publish_progress_update(
                            job,
                            current_item_index,
                            progress,
                            speed,
                            eta,
                            None,
                            None,
                        )
            return_code = await process.wait()
        finally:
            if self.active_processes.get(job["id"]) is process:
                self.active_processes.pop(job["id"], None)
        if self._is_cancel_requested(job["id"]):
            return
        if return_code != 0:
            message = "\n".join(output_tail[-8:]) or f"yt-dlp skoncil s kodem {return_code}."
            code = self._classify_failure(message)
            raise AppError(code, message)
        if job["kind"] == "playlist":
            await self._finalize_playlist_item_from_disk(job, current_item_index)
            await self._sync_existing_downloaded_items(await self.get_job(job["id"]))
            await self._mark_missing_playlist_items_failed(job["id"])
            await self._complete_job_from_item_counts(job["id"])
        else:
            await self._update_job(
                job["id"],
                status="completed",
                progress=100,
                speed_bytes_per_second=None,
                eta_seconds=None,
                completed_count=job["itemCount"],
                finished_at=utc_now(),
            )
        completed = await self.get_job(job["id"])
        await self.events.publish({"type": "job.completed", "job": completed})

    async def _publish_progress_update(
        self,
        job: dict[str, Any],
        current_item_index: int,
        progress: float | None,
        speed: int | None,
        eta: int | None,
        downloaded_bytes: int | None = None,
        total_bytes: int | None = None,
    ) -> None:
        item_fields: dict[str, Any] = {"status": "downloading"}
        job_fields: dict[str, Any] = {"status": "downloading"}
        if progress is not None:
            item_fields["progress"] = progress
            job_fields["progress"] = progress
        if speed is not None:
            item_fields["speed_bytes_per_second"] = speed
            job_fields["speed_bytes_per_second"] = speed
        if eta is not None:
            item_fields["eta_seconds"] = eta
            job_fields["eta_seconds"] = eta
        if downloaded_bytes is not None:
            item_fields["downloaded_bytes"] = downloaded_bytes
        if total_bytes is not None:
            item_fields["total_bytes"] = total_bytes
        await self._update_item(job["id"], current_item_index, **item_fields)
        await self._update_job(job["id"], **job_fields)
        await self.events.publish(
            {
                "type": "job.progress",
                "jobId": job["id"],
                "status": "downloading",
                "itemIndex": current_item_index,
                "percent": progress,
                "speedBytesPerSecond": speed,
                "etaSeconds": eta,
                "downloadedBytes": downloaded_bytes,
                "totalBytes": total_bytes,
                "itemCount": job["itemCount"],
            }
        )

    async def _recover_jobs_without_live_process(self, rows: list[dict[str, Any]]) -> bool:
        recovered = False
        for row in rows:
            if row["status"] not in {"downloading", "postprocessing"}:
                continue
            process = self.active_processes.get(row["id"])
            if process and process.returncode is None:
                continue
            await self.database.execute(
                """
                UPDATE download_jobs
                SET status = 'queued',
                    progress = 0,
                    speed_bytes_per_second = NULL,
                    eta_seconds = NULL,
                    error_code = 'NETWORK_ERROR',
                    error_message = 'Stahovaci proces nebezi. Zarazuji ulohu znovu do fronty.'
                WHERE id = ?
                """,
                (row["id"],),
            )
            await self.queue.put(row["id"])
            recovered = True
        return recovered

    async def _cancel_unfinished_items(self, job_id: str) -> None:
        await self.database.execute(
            """
            UPDATE download_items
            SET status = 'cancelled',
                speed_bytes_per_second = NULL,
                eta_seconds = NULL
            WHERE job_id = ?
              AND status NOT IN ('completed', 'failed', 'cancelled')
            """,
            (job_id,),
        )

    async def _skip_current_playlist_item(self, job: dict[str, Any], reason: str) -> bool:
        if job["kind"] != "playlist":
            return False
        current_item_index = int(job.get("currentItemIndex") or 1)
        item_count = int(job.get("itemCount") or 1)
        await self._update_item(
            job["id"],
            current_item_index,
            status="failed",
            progress=100,
            error_code="NETWORK_ERROR",
            error_message=reason[-500:],
        )
        counts = await self._item_counts(job["id"])
        if current_item_index >= item_count:
            await self._update_job(
                job["id"],
                status="completed",
                progress=100,
                completed_count=counts["completed"],
                failed_count=counts["failed"],
                auto_attempts=0,
                speed_bytes_per_second=None,
                eta_seconds=None,
                error_code=None,
                error_message=(
                    "Playlist skoncil. Nektere polozky se nepodarilo stahnout "
                    "ani po opakovani."
                ),
                finished_at=utc_now(),
            )
            return True
        await self._update_job(
            job["id"],
            status="queued",
            progress=0,
            current_item_index=current_item_index + 1,
            completed_count=counts["completed"],
            failed_count=counts["failed"],
            auto_attempts=0,
            speed_bytes_per_second=None,
            eta_seconds=None,
            error_code=None,
            error_message=(
                f"Polozka {current_item_index} se opakovane zasekla. "
                "Preskakuji ji a pokracuji dalsi polozkou."
            ),
        )
        return True

    async def _sync_existing_downloaded_items(self, job: dict[str, Any]) -> None:
        if job["kind"] != "playlist":
            return
        target_subfolder = job.get("targetSubfolder") or sanitize_filename(job["title"])
        target = Path(job["targetRoot"]) / target_subfolder
        downloaded_ids = self._downloaded_video_ids(target) if target.exists() else []
        if not downloaded_ids:
            await self.database.execute(
                """
                UPDATE download_items
                SET status = 'queued',
                    progress = 0,
                    speed_bytes_per_second = NULL,
                    eta_seconds = NULL
                WHERE job_id = ?
                  AND status = 'completed'
                """,
                (job["id"],),
            )
            counts = await self._item_counts(job["id"])
            resume_index = await self._resume_playlist_item_index(job)
            await self._update_job(
                job["id"],
                completed_count=counts["completed"],
                failed_count=counts["failed"],
                current_item_index=resume_index,
            )
            return

        placeholders = ",".join("?" for _ in downloaded_ids)
        await self.database.execute(
            f"""
            UPDATE download_items
            SET status = 'completed',
                progress = 100,
                error_code = NULL,
                error_message = NULL
            WHERE job_id = ?
              AND source_id IN ({placeholders})
            """,
            (job["id"], *downloaded_ids),
        )
        await self.database.execute(
            f"""
            UPDATE download_items
            SET status = 'queued',
                progress = 0,
                speed_bytes_per_second = NULL,
                eta_seconds = NULL
            WHERE job_id = ?
              AND status = 'completed'
              AND source_id IS NOT NULL
              AND source_id NOT IN ({placeholders})
            """,
            (job["id"], *downloaded_ids),
        )
        counts = await self._item_counts(job["id"])
        resume_index = await self._resume_playlist_item_index(job)
        await self._update_job(
            job["id"],
            completed_count=counts["completed"],
            failed_count=counts["failed"],
            current_item_index=resume_index,
        )

    async def _finalize_playlist_item_from_disk(
        self,
        job: dict[str, Any],
        playlist_index: int,
    ) -> None:
        item = await self.database.fetch_one(
            """
            SELECT source_id, status
            FROM download_items
            WHERE job_id = ? AND playlist_index = ?
            """,
            (job["id"], playlist_index),
        )
        if not item or item["status"] == "completed":
            return

        target_subfolder = job.get("targetSubfolder") or sanitize_filename(job["title"])
        target = Path(job["targetRoot"]) / target_subfolder
        downloaded_ids = self._downloaded_video_ids(target) if target.exists() else []
        if item["source_id"] and item["source_id"] in downloaded_ids:
            await self._update_item(
                job["id"],
                playlist_index,
                status="completed",
                progress=100,
                speed_bytes_per_second=None,
                eta_seconds=None,
                error_code=None,
                error_message=None,
            )
        elif item["status"] in {"downloading", "postprocessing"}:
            await self._update_item(
                job["id"],
                playlist_index,
                status="failed",
                progress=100,
                speed_bytes_per_second=None,
                eta_seconds=None,
                error_code="ITEM_NOT_DOWNLOADED",
                error_message="yt-dlp presel na dalsi polozku, ale soubor nebyl vytvoren.",
            )

        counts = await self._item_counts(job["id"])
        await self._update_job(
            job["id"],
            completed_count=counts["completed"],
            failed_count=counts["failed"],
        )

    @staticmethod
    def _downloaded_video_ids(target: Path) -> list[str]:
        ids: set[str] = set()
        ignored_suffixes = {".part", ".ytdl", ".tmp", ".temp"}
        for path in target.iterdir():
            if not path.is_file() or path.suffix.lower() in ignored_suffixes:
                continue
            match = FILE_VIDEO_ID_RE.search(path.name)
            if match:
                ids.add(match.group(1))
        return sorted(ids)

    def _current_download_part_size(
        self,
        job: dict[str, Any],
        current_item_index: int | None,
    ) -> int | None:
        try:
            target = Path(job["targetRoot"])
            if job["kind"] == "playlist":
                target_subfolder = job.get("targetSubfolder") or sanitize_filename(job["title"])
                target = target / target_subfolder
            if not target.exists():
                return None

            candidates = [path for path in target.glob("*.part") if path.is_file()]
            if job["kind"] == "playlist" and current_item_index:
                item_prefix = f"{current_item_index:03d} - "
                candidates = [path for path in candidates if path.name.startswith(item_prefix)]
            if not candidates:
                return None
            if job["kind"] == "playlist":
                return sum(path.stat().st_size for path in candidates)
            latest = max(candidates, key=lambda path: path.stat().st_mtime)
            return latest.stat().st_size
        except OSError:
            return None

    async def _current_download_total_bytes(
        self,
        job_id: str,
        current_item_index: int | None,
    ) -> int | None:
        row = await self.database.fetch_one(
            """
            SELECT total_bytes
            FROM download_items
            WHERE job_id = ? AND playlist_index = ?
            """,
            (job_id, current_item_index or 1),
        )
        return self._parse_byte_count((row or {}).get("total_bytes"))

    async def _estimate_current_item_total_bytes(
        self,
        job: dict[str, Any],
        current_item_index: int | None,
    ) -> int | None:
        item = await self.database.fetch_one(
            """
            SELECT source_id
            FROM download_items
            WHERE job_id = ? AND playlist_index = ?
            """,
            (job["id"], current_item_index or 1),
        )
        source_id = (item or {}).get("source_id") or job.get("sourceId")
        if not source_id:
            return None

        cache = getattr(self, "total_size_estimates", None)
        if cache is None:
            cache = {}
            self.total_size_estimates = cache
        cache_key = (str(source_id), str(job.get("preset") or ""), str(job.get("quality") or ""))
        if cache_key in cache:
            return cache[cache_key]

        try:
            data = await self.ytdlp.dump_json(
                f"https://www.youtube.com/watch?v={source_id}",
                playlist=False,
            )
        except (AppError, TimeoutError, OSError):
            cache[cache_key] = None
            return None

        total_bytes = self._metadata_total_bytes(data)
        cache[cache_key] = total_bytes
        if total_bytes is not None:
            await self._update_item(
                job["id"],
                current_item_index or 1,
                total_bytes=total_bytes,
            )
        return total_bytes

    @classmethod
    def _metadata_total_bytes(cls, data: dict[str, Any]) -> int | None:
        requested_formats = data.get("requested_formats")
        if isinstance(requested_formats, list):
            sizes = [
                cls._parse_byte_count(item.get("filesize"))
                or cls._parse_byte_count(item.get("filesize_approx"))
                for item in requested_formats
                if isinstance(item, dict)
            ]
            known_sizes = [size for size in sizes if size is not None]
            if known_sizes:
                return sum(known_sizes)

        return cls._parse_byte_count(data.get("filesize")) or cls._parse_byte_count(
            data.get("filesize_approx")
        )

    @staticmethod
    def _progress_from_bytes(
        downloaded_bytes: int | None,
        total_bytes: int | None,
    ) -> float | None:
        if not downloaded_bytes or not total_bytes or total_bytes <= 0:
            return None
        return max(0.0, min(99.9, (downloaded_bytes / total_bytes) * 100))

    async def _reset_incomplete_playlist_items(self, job_id: str) -> None:
        await self.database.execute(
            """
            UPDATE download_items
            SET status = 'queued',
                progress = 0,
                speed_bytes_per_second = NULL,
                eta_seconds = NULL,
                error_code = NULL,
                error_message = NULL
            WHERE job_id = ?
              AND status != 'completed'
            """,
            (job_id,),
        )

    async def _first_unfinished_playlist_item_index(self, job_id: str) -> int:
        row = await self.database.fetch_one(
            """
            SELECT MIN(playlist_index) AS playlist_index
            FROM download_items
            WHERE job_id = ?
              AND status != 'completed'
            """,
            (job_id,),
        )
        if row and row["playlist_index"] is not None:
            return int(row["playlist_index"])
        count_row = await self.database.fetch_one(
            "SELECT item_count FROM download_jobs WHERE id = ?",
            (job_id,),
        )
        return int((count_row or {}).get("item_count") or 0) + 1

    async def _resume_playlist_item_index(self, job: dict[str, Any]) -> int:
        item_count = int(job.get("itemCount") or 0)
        preferred_index = int(job.get("currentItemIndex") or 0)
        highest_completed = await self._highest_completed_playlist_item_index(job["id"])
        forward_resume_index = max(preferred_index, highest_completed + 1)

        if forward_resume_index > 1:
            row = await self.database.fetch_one(
                """
                SELECT MIN(playlist_index) AS playlist_index
                FROM download_items
                WHERE job_id = ?
                  AND status != 'completed'
                  AND playlist_index >= ?
                """,
                (job["id"], forward_resume_index),
            )
            if row and row["playlist_index"] is not None:
                return int(row["playlist_index"])
            return min(item_count + 1, forward_resume_index)

        if highest_completed:
            return min(item_count + 1, highest_completed + 1)

        return await self._first_unfinished_playlist_item_index(job["id"])

    async def _highest_completed_playlist_item_index(self, job_id: str) -> int:
        row = await self.database.fetch_one(
            """
            SELECT MAX(playlist_index) AS playlist_index
            FROM download_items
            WHERE job_id = ?
              AND status = 'completed'
            """,
            (job_id,),
        )
        if row and row["playlist_index"] is not None:
            return int(row["playlist_index"])
        return 0

    async def _item_counts(self, job_id: str) -> dict[str, int]:
        row = await self.database.fetch_one(
            """
            SELECT
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM download_items
            WHERE job_id = ?
            """,
            (job_id,),
        )
        return {
            "completed": int((row or {}).get("completed") or 0),
            "failed": int((row or {}).get("failed") or 0),
        }

    async def _mark_missing_playlist_items_failed(self, job_id: str) -> None:
        await self.database.execute(
            """
            UPDATE download_items
            SET status = 'failed',
                progress = 100,
                error_code = 'ITEM_NOT_DOWNLOADED',
                error_message = 'yt-dlp dokoncil playlist, ale soubor pro tuto polozku nebyl vytvoren.'
            WHERE job_id = ?
              AND status != 'completed'
            """,
            (job_id,),
        )

    async def _complete_job_from_item_counts(self, job_id: str) -> None:
        counts = await self._item_counts(job_id)
        message = None
        if counts["failed"]:
            message = "Playlist skoncil, ale nektere polozky se nepodarilo stahnout."
        await self._update_job(
            job_id,
            status="completed",
            progress=100,
            speed_bytes_per_second=None,
            eta_seconds=None,
            completed_count=counts["completed"],
            failed_count=counts["failed"],
            auto_attempts=0,
            error_code=None,
            error_message=message,
            finished_at=utc_now(),
        )

    def _download_args(self, job: dict[str, Any]) -> list[str]:
        args = [
            *self.ytdlp.command(),
            "--no-config",
            "--newline",
            "--continue",
            "--part",
            "--retries",
            "10",
            "--fragment-retries",
            "10",
            "--retry-sleep",
            "5",
            "--file-access-retries",
            "5",
            "--socket-timeout",
            "30",
            "--progress-template",
            (
                "download:__YDL_PROGRESS__%(progress._percent_str)s\t"
                "%(progress._speed_str)s\t%(progress._eta_str)s\t"
                "%(progress.downloaded_bytes)s\t%(progress.total_bytes)s\t"
                "%(progress.total_bytes_estimate)s"
            ),
            "--progress-delta",
            "0.4",
            "--windows-filenames",
            "--trim-filenames",
            "180",
            "--ignore-errors",
            "--no-overwrites",
            "--no-mtime",
            "--paths",
            f"home:{job['targetRoot']}",
        ]
        if self.ytdlp.js_runtime:
            args.extend(["--js-runtimes", self.ytdlp.js_runtime])
        if Path(self.ytdlp.ffmpeg or "").exists():
            args.extend(["--ffmpeg-location", str(Path(self.ytdlp.ffmpeg or "").parent)])

        args.extend(ytdlp_args_for_preset(job["preset"], job["quality"]))

        if job["kind"] == "playlist":
            subfolder = job["targetSubfolder"] or sanitize_filename(job["title"])
            resume_from_index = int(job.get("resumeFromIndex") or job.get("currentItemIndex") or 1)
            if resume_from_index > 1:
                args.extend(["--playlist-start", str(resume_from_index)])
            args.extend(
                [
                    "--yes-playlist",
                    "--print",
                    "before_dl:__YDL_ITEM__%(playlist_index)s\t%(id)s\t%(title)s",
                    "-o",
                    f"{subfolder}/%(playlist_index)03d - %(title).140B [%(id)s].%(ext)s",
                ]
            )
        else:
            args.extend(["--no-playlist", "-o", "%(title).150B [%(id)s].%(ext)s"])

        args.append(job["sourceUrl"])
        return args

    async def _wait_for_network(
        self,
        job_id: str,
        attempt: int,
        max_attempts: int,
        previous_error: str,
    ) -> None:
        message = (
            f"Cekam na internet. Po obnoveni pripojeni zkusim pokracovat "
            f"automaticky (pokus {attempt + 1}/{max_attempts})."
        )
        await self._update_job(
            job_id,
            status="waiting_for_network",
            auto_attempts=attempt,
            error_code="NETWORK_ERROR",
            error_message=message,
        )
        await self.events.publish(
            {
                "type": "job.waiting_for_network",
                "jobId": job_id,
                "attempt": attempt,
                "maxAttempts": max_attempts,
                "message": message,
                "previousError": previous_error[-500:],
            }
        )

        elapsed = 0
        while elapsed < NETWORK_WAIT_TIMEOUT_SECONDS:
            latest = await self.get_job(job_id)
            if latest["status"] == "cancelled":
                raise AppError("NETWORK_ERROR", "Uloha byla zrusena behem cekani na internet.")
            if await self._network_available():
                await self._update_job(
                    job_id,
                    status="queued",
                    error_message=f"Internet je zpatky, pokracuji v pokusu {attempt + 1}/{max_attempts}.",
                )
                return
            await asyncio.sleep(NETWORK_CHECK_INTERVAL_SECONDS)
            elapsed += NETWORK_CHECK_INTERVAL_SECONDS

        raise AppError("NETWORK_ERROR", "Internet se dlouho neobnovil.")

    @staticmethod
    async def _network_available() -> bool:
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
                response = await client.get("https://www.youtube.com/generate_204")
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    @staticmethod
    def _classify_failure(message: str) -> str:
        lowered = message.lower()
        if any(hint in lowered for hint in NON_RETRYABLE_HINTS):
            return "VIDEO_UNAVAILABLE"
        return "NETWORK_ERROR"

    @staticmethod
    def _parse_progress_percent(value: str) -> float | None:
        match = PROGRESS_RE.search(value.strip())
        if not match:
            return None
        return max(0.0, min(100.0, float(match.group(1))))

    @classmethod
    def _parse_speed_value(cls, value: str) -> int | None:
        match = SPEED_VALUE_RE.search(value.strip())
        if not match:
            return None
        return cls._speed_to_bytes(float(match.group(1)), match.group(2))

    @staticmethod
    def _parse_eta_value(value: str) -> int | None:
        value = value.strip()
        if not value or value.lower() == "unknown":
            return None
        parts = [int(part) for part in value.split(":") if part.isdigit()]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 1:
            return parts[0]
        return None

    @staticmethod
    def _parse_byte_count(value: Any) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"na", "none", "unknown", "null"}:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if number <= 0:
            return None
        return int(number)

    @staticmethod
    def _speed_to_bytes(value: float, unit: str) -> int:
        unit = unit.lower()
        multipliers = {
            "b": 1,
            "kb": 1000,
            "kib": 1024,
            "mb": 1000**2,
            "mib": 1024**2,
            "gb": 1000**3,
            "gib": 1024**3,
        }
        return int(value * multipliers.get(unit, 1))

    @classmethod
    def _parse_speed(cls, line: str) -> int | None:
        match = SPEED_RE.search(line)
        if not match:
            return None
        return cls._speed_to_bytes(float(match.group(1)), match.group(2))

    @classmethod
    def _parse_eta(cls, line: str) -> int | None:
        match = ETA_RE.search(line)
        if not match:
            return None
        return cls._parse_eta_value(match.group(1))

    async def _update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = ?" for key in fields)
        await self.database.execute(
            f"UPDATE download_jobs SET {assignments} WHERE id = ?",
            (*fields.values(), job_id),
        )
        try:
            job = await self.get_job(job_id)
            await self.events.publish({"type": "job.updated", "job": job})
        except AppError:
            pass

    async def _update_item(self, job_id: str, playlist_index: int, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = ?" for key in fields)
        await self.database.execute(
            f"UPDATE download_items SET {assignments} WHERE job_id = ? AND playlist_index = ?",
            (*fields.values(), job_id, playlist_index),
        )

    def _is_cancel_requested(self, job_id: str) -> bool:
        return job_id in self.cancel_requested

    async def _requeue_interrupted(self) -> None:
        await self.database.execute(
            """
            UPDATE download_jobs
            SET status = 'interrupted'
            WHERE status IN (
                'resolving',
                'downloading',
                'postprocessing',
                'paused',
                'waiting_for_network'
            )
            """
        )
        rows = await self.database.fetch_all(
            "SELECT id FROM download_jobs WHERE status = 'interrupted' ORDER BY created_at"
        )
        for row in rows:
            await self.database.execute(
                """
                UPDATE download_jobs
                SET status = 'queued',
                    error_message = 'Obnovuji prerusenou ulohu automaticky.'
                WHERE id = ?
                """,
                (row["id"],),
            )
            await self.queue.put(row["id"])

    async def _enqueue_queued_jobs(self) -> None:
        rows = await self.database.fetch_all(
            "SELECT id FROM download_jobs WHERE status = 'queued' ORDER BY created_at"
        )
        for row in rows:
            await self.queue.put(row["id"])

    @staticmethod
    def _ensure_writable_directory(path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".youdownloader-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise AppError("TARGET_NOT_WRITABLE", "Do vybrane slozky nelze zapisovat.") from exc

    @staticmethod
    def _walk_process_tree(pid: int, action) -> None:
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                action(child)
            action(parent)
        except psutil.Error:
            return

    @classmethod
    def _terminate_tree(cls, pid: int) -> None:
        cls._walk_process_tree(pid, lambda proc: proc.terminate())

    @classmethod
    def _kill_tree(cls, pid: int) -> None:
        cls._walk_process_tree(pid, lambda proc: proc.kill())
