from __future__ import annotations

import queue
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from .jm_service import JmService, PartialDownloadError
from .models import DownloadTask
from .storage import Storage


@dataclass(slots=True)
class DownloadRequest:
    task_id: str
    album_id: str
    photo_ids: list[str]


class DownloadQueue:
    def __init__(self, storage: Storage, service: JmService):
        self.storage = storage
        self.service = service
        self.queue: queue.Queue[DownloadRequest] = queue.Queue()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.deleted_task_ids: set[str] = set()

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._worker, name="jm-download-worker", daemon=True)
            self.thread.start()

    def enqueue(self, album_id: str, photo_ids: list[str] | None = None) -> DownloadTask:
        task = DownloadTask(id=uuid.uuid4().hex, album_id=str(album_id), photo_ids=photo_ids or [])
        self.storage.create_task(task)
        self.queue.put(DownloadRequest(task.id, task.album_id, task.photo_ids))
        self.start()
        return task

    def retry_failed(self, task_id: str) -> DownloadTask:
        task = self.storage.get_task(task_id)
        if task is None:
            raise ValueError("Task not found")
        if not task.failed_photo_ids:
            raise ValueError("Task has no failed chapters to retry")
        return self.enqueue(task.album_id, task.failed_photo_ids)

    def delete_task(self, task_id: str) -> DownloadTask:
        task = self.storage.get_task(task_id)
        if task is None:
            raise ValueError("Task not found")
        with self.lock:
            self.deleted_task_ids.add(task_id)
        self._cleanup_task_output(task)
        self.storage.delete_task(task_id)
        return task

    def _worker(self) -> None:
        while True:
            request = self.queue.get()
            try:
                self._run_request(request)
            finally:
                self.queue.task_done()

    def _run_request(self, request: DownloadRequest) -> None:
        if self._is_deleted(request.task_id):
            self._discard_deleted(request.task_id)
            return

        self.storage.update_task(request.task_id, status="running", progress="Starting download")

        def progress(message: str, current: int | None = None, total: int | None = None) -> None:
            changes = {"progress": message}
            if current is not None:
                changes["progress_current"] = current
            if total is not None:
                changes["progress_total"] = total
            self.storage.update_task(request.task_id, **changes)

        try:
            output = self.service.download_album(
                request.album_id,
                request.photo_ids,
                progress=progress,
                cancel=lambda: self._is_deleted(request.task_id),
            )
            if self._is_deleted(request.task_id):
                self._cleanup_output_path(output)
                return
            self.storage.update_task(
                request.task_id,
                status="completed",
                progress="Completed",
                failed_photo_ids=[],
                output_path=str(output),
                error="",
            )
        except PartialDownloadError as exc:
            if self._is_deleted(request.task_id):
                self._cleanup_output_path(exc.output_path)
                return
            self.storage.update_task(
                request.task_id,
                status="partial",
                progress="Partially completed",
                failed_photo_ids=exc.failed_photo_ids,
                output_path=str(exc.output_path),
                error=str(exc),
            )
        except Exception as exc:
            if self._is_deleted(request.task_id):
                return
            self.storage.update_task(
                request.task_id,
                status="failed",
                progress="Failed",
                failed_photo_ids=getattr(exc, "failed_photo_ids", []),
                error=str(exc),
            )
        finally:
            if self._is_deleted(request.task_id):
                self._discard_deleted(request.task_id)

    def _is_deleted(self, task_id: str) -> bool:
        with self.lock:
            return task_id in self.deleted_task_ids

    def _discard_deleted(self, task_id: str) -> None:
        with self.lock:
            self.deleted_task_ids.discard(task_id)

    def _cleanup_task_output(self, task: DownloadTask) -> None:
        self._cleanup_output_path(task.output_path)

    def _cleanup_output_path(self, output_path: str | Path) -> None:
        if not output_path:
            return
        path = Path(output_path).resolve()
        roots = self._download_roots()
        if not any(path == root or root in path.parents for root in roots):
            return
        if path in roots:
            return
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()

    def _download_roots(self) -> set[Path]:
        settings = self.service.settings()
        candidates = {
            settings.download_dir,
            settings.single_download_dir or settings.download_dir,
            settings.series_download_dir or settings.download_dir,
        }
        return {Path(candidate).resolve() for candidate in candidates if candidate}
