from jm_downloader.models import AppSettings, Subscription
from jm_downloader.storage import Storage


def test_settings_persist(tmp_path):
    storage = Storage(tmp_path / "app.db")
    storage.save_settings(
        AppSettings(
            client_impl="html",
            download_dir=str(tmp_path / "downloads"),
            image_threads=7,
            photo_threads=2,
            keep_images=True,
            single_volume_folder=False,
            proxies="http://127.0.0.1:7890",
            cookies="AVS=x",
            domains="example.test",
        )
    )

    loaded = storage.get_settings("fallback")

    assert loaded.client_impl == "html"
    assert loaded.image_threads == 7
    assert loaded.keep_images is True
    assert loaded.single_volume_folder is False
    assert loaded.domains == "example.test"
    assert loaded.subscription_interval_minutes == 60


def test_subscription_persist(tmp_path):
    storage = Storage(tmp_path / "app.db")
    storage.upsert_subscription(
        Subscription(
            album_id="123",
            title="Title",
            cover_url="https://example.test/cover.jpg",
            known_photo_ids=["1", "2"],
            status="active",
        )
    )

    loaded = storage.get_subscription("123")

    assert loaded is not None
    assert loaded.title == "Title"
    assert loaded.known_photo_ids == ["1", "2"]
