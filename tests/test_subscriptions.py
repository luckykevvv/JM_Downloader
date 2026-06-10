from types import SimpleNamespace

from jm_downloader.models import AppSettings
from jm_downloader.storage import Storage
from jm_downloader.subscriptions import SubscriptionManager


class FakeService:
    def __init__(self):
        self.albums = {}
        self.downloads = []

    def get_album_entity(self, album_id):
        return self.albums[album_id]

    def cover_url(self, album_id):
        return f"https://example.test/{album_id}.jpg"

    def download_album(self, album_id, photo_ids, progress=None):
        self.downloads.append((album_id, list(photo_ids)))
        if progress:
            progress("downloaded")
        return "/tmp/out"


def fake_album(album_id, photo_ids):
    photos = [SimpleNamespace(id=photo_id) for photo_id in photo_ids]
    return FakeAlbum(album_id, photos)


class FakeAlbum:
    def __init__(self, album_id, photos):
        self.id = album_id
        self.title = f"Album {album_id}"
        self.photos = photos

    def __iter__(self):
        return iter(self.photos)


def test_subscribe_records_current_chapters(tmp_path):
    storage = Storage(tmp_path / "app.db")
    service = FakeService()
    service.albums["123"] = fake_album("123", ["1", "2"])
    manager = SubscriptionManager(storage, service)

    subscription = manager.subscribe("123")

    assert subscription.known_photo_ids == ["1", "2"]
    assert storage.get_subscription("123").title == "Album 123"


def test_check_downloads_new_chapters_and_updates_known_ids(tmp_path):
    storage = Storage(tmp_path / "app.db")
    storage.save_settings(AppSettings(download_dir=str(tmp_path), subscription_interval_minutes=60))
    service = FakeService()
    service.albums["123"] = fake_album("123", ["1", "2"])
    manager = SubscriptionManager(storage, service)
    manager.subscribe("123")
    service.albums["123"] = fake_album("123", ["1", "2", "3"])

    result = manager.check_all()

    assert result["checked"] == 1
    assert result["updated"] == 1
    assert service.downloads == [("123", ["3"])]
    assert storage.get_subscription("123").known_photo_ids == ["1", "2", "3"]
