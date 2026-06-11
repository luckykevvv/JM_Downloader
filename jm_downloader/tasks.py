from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass

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

    def _worker(self) -> None:
        while True:
            request = self.queue.get()
            try:
                self._run_request(request)
            finally:
                self.queue.task_done()

    def _run_request(self, request: DownloadRequest) -> None:
        self.storage.update_task(request.task_id, status="running", progress="Starting download")

        def progress(message: str, current: int | None = None, total: int | None = None) -> None:
            changes = {"progress": message}
            if current is not None:
                changes["progress_current"] = current
            if total is not None:
                changes["progress_total"] = total
            self.storage.update_task(request.task_id, **changes)

        try:
            output = self.service.download_album(request.album_id, request.photo_ids, progress=progress)
            self.storage.update_task(
                request.task_id,
                status="completed",
                progress="Completed",
                failed_photo_ids=[],
                output_path=str(output),
                error="",
            )
        except PartialDownloadError as exc:
            self.storage.update_task(
                request.task_id,
                status="partial",
                progress="Partially completed",
                failed_photo_ids=exc.failed_photo_ids,
                output_path=str(exc.output_path),
                error=str(exc),
            )
        except Exception as exc:
            self.storage.update_task(
                request.task_id,
                status="failed",
                progress="Failed",
                failed_photo_ids=getattr(exc, "failed_photo_ids", []),
                error=str(exc),
            )
