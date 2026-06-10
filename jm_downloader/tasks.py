from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass

from .jm_service import JmService
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

    def _worker(self) -> None:
        while True:
            request = self.queue.get()
            try:
                self.storage.update_task(request.task_id, status="running", progress="Starting download")

                def progress(message: str) -> None:
                    self.storage.update_task(request.task_id, progress=message)

                output = self.service.download_album(request.album_id, request.photo_ids, progress=progress)
                self.storage.update_task(
                    request.task_id,
                    status="completed",
                    progress="Completed",
                    output_path=str(output),
                    error="",
                )
            except Exception as exc:
                self.storage.update_task(
                    request.task_id,
                    status="failed",
                    progress="Failed",
                    error=str(exc),
                )
            finally:
                self.queue.task_done()
