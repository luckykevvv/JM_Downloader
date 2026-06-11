from pathlib import Path

from jm_downloader.jm_service import PartialDownloadError
from jm_downloader.models import AppSettings, DownloadTask
from jm_downloader.storage import Storage
from jm_downloader.tasks import DownloadQueue, DownloadRequest


class PartialService:
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.calls = []

    def settings(self):
        return AppSettings(download_dir=str(self.output_path.parent))

    def download_album(self, album_id, photo_ids, progress=None, cancel=None):
        self.calls.append((album_id, photo_ids))
        if progress:
            progress("Packaged successful chapters", 2, 3)
        raise PartialDownloadError("部分下载失败，共2个图片下载失败", self.output_path, ["11"])


def test_download_queue_marks_partial_download_and_keeps_output_path(tmp_path):
    storage = Storage(tmp_path / "app.db")
    output_path = tmp_path / "downloads" / "Album"
    storage.create_task(DownloadTask(id="task-1", album_id="123", photo_ids=[]))
    queue = DownloadQueue(storage, PartialService(output_path))

    queue._run_request(DownloadRequest("task-1", "123", []))

    task = storage.get_task("task-1")

    assert task is not None
    assert task.status == "partial"
    assert task.progress == "Partially completed"
    assert task.progress_current == 2
    assert task.progress_total == 3
    assert task.output_path == str(output_path)
    assert task.failed_photo_ids == ["11"]
    assert "部分下载失败" in task.error


def test_download_queue_retries_failed_chapters_only(tmp_path):
    storage = Storage(tmp_path / "app.db")
    service = PartialService(tmp_path / "downloads" / "Album")
    storage.create_task(
        DownloadTask(
            id="task-1",
            album_id="123",
            photo_ids=[],
            status="partial",
            failed_photo_ids=["11", "12"],
        )
    )
    queue = DownloadQueue(storage, service)
    queue.start = lambda: None

    retry = queue.retry_failed("task-1")

    assert retry.album_id == "123"
    assert retry.photo_ids == ["11", "12"]
    assert storage.get_task(retry.id) is not None


def test_download_queue_delete_task_removes_record_and_output_dir(tmp_path):
    storage = Storage(tmp_path / "app.db")
    output_path = tmp_path / "downloads" / "Album"
    output_path.mkdir(parents=True)
    (output_path / "001.cbz").write_bytes(b"cbz")
    storage.create_task(
        DownloadTask(
            id="task-1",
            album_id="123",
            photo_ids=[],
            status="completed",
            output_path=str(output_path),
        )
    )
    queue = DownloadQueue(storage, PartialService(output_path))

    queue.delete_task("task-1")

    assert storage.get_task("task-1") is None
    assert not output_path.exists()


def test_download_queue_delete_task_does_not_remove_download_root(tmp_path):
    storage = Storage(tmp_path / "app.db")
    download_root = tmp_path / "downloads"
    download_root.mkdir()
    storage.create_task(
        DownloadTask(
            id="task-1",
            album_id="123",
            photo_ids=[],
            status="completed",
            output_path=str(download_root),
        )
    )
    queue = DownloadQueue(storage, PartialService(download_root / "Album"))

    queue.delete_task("task-1")

    assert storage.get_task("task-1") is None
    assert download_root.exists()
