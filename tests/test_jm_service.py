import zipfile
from pathlib import Path
from types import SimpleNamespace

from jm_downloader.jm_service import COVER_SIZE, JmService, SelectedPhotoDownloader
from jm_downloader.models import AppSettings


class FakeSearchPage:
    is_single_album = False

    def __init__(self):
        self.content = [("123", {"name": "Title", "tags": ["tag"]})]


class FakeClient:
    def __init__(self):
        self.called = []

    def search_site(self, *args, **kwargs):
        self.called.append(("site", args, kwargs))
        return FakeSearchPage()

    def search_author(self, *args, **kwargs):
        self.called.append(("author", args, kwargs))
        return FakeSearchPage()

    def search_tag(self, *args, **kwargs):
        self.called.append(("tag", args, kwargs))
        return FakeSearchPage()

    def search_work(self, *args, **kwargs):
        self.called.append(("work", args, kwargs))
        return FakeSearchPage()

    def search_actor(self, *args, **kwargs):
        self.called.append(("actor", args, kwargs))
        return FakeSearchPage()

    def get_album_detail(self, album_id):
        return SimpleNamespace(id=album_id, title="Album", tags=["idtag"])


def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(download_dir=str(tmp_path))


def test_search_type_dispatch(monkeypatch, tmp_path):
    service = JmService(lambda: settings(tmp_path))
    client = FakeClient()
    monkeypatch.setattr(service, "client", lambda: client)

    service.search("abc", "author", page=2, order="mv", time="w")

    name, args, kwargs = client.called[0]
    assert name == "author"
    assert args == ("abc",)
    assert kwargs == {"page": 2, "order_by": "mv", "time": "w"}


def test_id_search_fetches_album(monkeypatch, tmp_path):
    service = JmService(lambda: settings(tmp_path))
    monkeypatch.setattr(service, "client", lambda: FakeClient())

    results = service.search("123", "id")

    assert results[0].album_id == "123"
    assert results[0].title == "Album"
    assert results[0].cover_url


def test_selected_photo_downloader_filters_album():
    photos = [
        SimpleNamespace(id="1"),
        SimpleNamespace(id="2"),
        SimpleNamespace(id="3"),
    ]
    album = FakeAlbum(photos)

    downloader = object.__new__(SelectedPhotoDownloader)
    downloader.selected_photo_ids = {"2", "3"}

    assert [photo.id for photo in downloader.do_filter(album)] == ["2", "3"]


def test_selected_photo_downloader_progress_callback_is_not_bound():
    messages = []

    def progress(message):
        messages.append(message)

    class TaskDownloader(SelectedPhotoDownloader):
        progress_callback = progress

    downloader = object.__new__(TaskDownloader)
    downloader.emit_progress("ok")

    assert messages == ["ok"]


def test_get_album_prefers_html_metadata_when_dates_are_present(monkeypatch, tmp_path):
    service = JmService(lambda: settings(tmp_path))
    html_album = FakeAlbum([FakePhoto("10", 1, "Chapter 1")])
    html_album.pub_date = "2024-02-03"
    api_album = FakeAlbum([FakePhoto("10", 1, "Chapter 1")])
    api_album.pub_date = "0"

    class HtmlClient:
        def get_album_detail(self, album_id):
            return html_album

    class ApiClient:
        def get_album_detail(self, album_id):
            return api_album

    monkeypatch.setattr(service, "detail_client", lambda: HtmlClient())
    monkeypatch.setattr(service, "client", lambda: ApiClient())

    album = service.get_album("999")

    assert album.pub_date == "2024-02-03"


def test_get_album_uses_cache(monkeypatch, tmp_path):
    service = JmService(lambda: settings(tmp_path))
    calls = []
    html_album = FakeAlbum([FakePhoto("10", 1, "Chapter 1")])
    html_album.pub_date = "2024-02-03"

    class HtmlClient:
        def get_album_detail(self, album_id):
            calls.append(album_id)
            return html_album

    monkeypatch.setattr(service, "detail_client", lambda: HtmlClient())

    first = service.get_album("999")
    second = service.get_album("999")

    assert first is second
    assert calls == ["999"]


def test_write_cbz_files_contains_comicinfo_and_images(tmp_path):
    service = JmService(lambda: settings(tmp_path))
    album = FakeAlbum([FakePhoto("10", 1, "Chapter 1")])
    image_path = tmp_path / "001.jpg"
    image_path.write_bytes(b"img")
    cover_path = tmp_path / "cover.jpg"
    cover_path.write_bytes(b"cover")
    photo = album.photos[0]
    downloader = SimpleNamespace(download_success_dict={album: {photo: [(str(image_path), SimpleNamespace(index=1))]}})
    out_dir = tmp_path / "Album"
    out_dir.mkdir()

    service._write_cbz_files(album, downloader, out_dir, set(), cover_path=cover_path)

    cbz = out_dir / "Album.cbz"
    assert cbz.exists()
    with zipfile.ZipFile(cbz) as archive:
        assert "ComicInfo.xml" in archive.namelist()
        assert "cover.jpg" in archive.namelist()
        assert "001.jpg" in archive.namelist()
    assert (out_dir / "Album.jpg").read_bytes() == b"cover"
    assert (out_dir / "cover.jpg").read_bytes() == b"cover"


def test_write_cbz_files_uses_komga_book_art_without_root_series_cover(tmp_path):
    service = JmService(lambda: settings(tmp_path))
    album = FakeAlbum([FakePhoto("10", 1, "Chapter 1")])
    image_path = tmp_path / "001.jpg"
    image_path.write_bytes(b"img")
    cover_path = tmp_path / "cover-source.jpg"
    cover_path.write_bytes(b"cover")
    photo = album.photos[0]
    downloader = SimpleNamespace(download_success_dict={album: {photo: [(str(image_path), SimpleNamespace(index=1))]}})
    out_dir = tmp_path / "downloads"
    out_dir.mkdir()

    service._write_cbz_files(album, downloader, out_dir, set(), cover_path=cover_path)

    assert (out_dir / "Album.cbz").exists()
    assert (out_dir / "Album.jpg").read_bytes() == b"cover"
    assert not (out_dir / "cover.jpg").exists()


def test_write_cbz_files_uses_komga_series_art_for_multichapter(tmp_path):
    service = JmService(lambda: settings(tmp_path))
    album = FakeAlbum([FakePhoto("10", 1, "Chapter 1"), FakePhoto("11", 2, "Chapter 2")])
    first_image = tmp_path / "001.jpg"
    second_image = tmp_path / "002.jpg"
    first_image.write_bytes(b"img1")
    second_image.write_bytes(b"img2")
    cover_path = tmp_path / "cover-source.jpg"
    cover_path.write_bytes(b"cover")
    downloader = SimpleNamespace(
        download_success_dict={
            album: {
                album.photos[0]: [(str(first_image), SimpleNamespace(index=1))],
                album.photos[1]: [(str(second_image), SimpleNamespace(index=1))],
            }
        }
    )
    out_dir = tmp_path / "Album"
    out_dir.mkdir()

    service._write_cbz_files(album, downloader, out_dir, set(), cover_path=cover_path)

    assert (out_dir / "001 - Chapter 1.cbz").exists()
    assert (out_dir / "001 - Chapter 1.jpg").read_bytes() == b"cover"
    assert (out_dir / "002 - Chapter 2.jpg").read_bytes() == b"cover"
    assert (out_dir / "cover.jpg").read_bytes() == b"cover"


def test_write_cbz_files_skips_empty_failed_chapters(tmp_path):
    service = JmService(lambda: settings(tmp_path))
    album = FakeAlbum([FakePhoto("10", 1, "Chapter 1"), FakePhoto("11", 2, "Chapter 2")])
    image_path = tmp_path / "001.jpg"
    image_path.write_bytes(b"img")
    cover_path = tmp_path / "cover-source.jpg"
    cover_path.write_bytes(b"cover")
    downloader = SimpleNamespace(
        download_success_dict={
            album: {
                album.photos[0]: [(str(image_path), SimpleNamespace(index=1))],
                album.photos[1]: [],
            }
        }
    )
    out_dir = tmp_path / "Album"
    out_dir.mkdir()

    service._write_cbz_files(album, downloader, out_dir, set(), cover_path=cover_path)

    assert (out_dir / "001 - Chapter 1.cbz").exists()
    assert not (out_dir / "002 - Chapter 2.cbz").exists()


def test_write_cbz_files_skips_chapters_with_failed_images(tmp_path):
    service = JmService(lambda: settings(tmp_path))
    album = FakeAlbum([FakePhoto("10", 1, "Chapter 1"), FakePhoto("11", 2, "Chapter 2")])
    first_image = tmp_path / "001.jpg"
    second_image = tmp_path / "002.jpg"
    first_image.write_bytes(b"img1")
    second_image.write_bytes(b"img2")
    failed_image = SimpleNamespace(from_photo=album.photos[1], download_url="https://example.test/002.jpg")
    downloader = SimpleNamespace(
        download_success_dict={
            album: {
                album.photos[0]: [(str(first_image), SimpleNamespace(index=1))],
                album.photos[1]: [(str(second_image), SimpleNamespace(index=1))],
            }
        },
        download_failed_image=[(failed_image, ValueError("broken"))],
        download_failed_photo=[],
    )
    out_dir = tmp_path / "Album"
    out_dir.mkdir()

    service._write_cbz_files(album, downloader, out_dir, set())

    assert (out_dir / "001 - Chapter 1.cbz").exists()
    assert not (out_dir / "002 - Chapter 2.cbz").exists()


def test_download_album_cover_uses_web_cover_size(monkeypatch, tmp_path):
    service = JmService(lambda: settings(tmp_path))
    calls = []

    class FakeCoverClient:
        def download_album_cover(self, album_id, save_path, size=""):
            calls.append((album_id, size))
            Path(save_path).write_bytes(b"cover")

    monkeypatch.setattr(service, "client", lambda: FakeCoverClient())

    cover_path = service._download_album_cover(SimpleNamespace(id="123"), tmp_path)

    assert cover_path is not None
    assert cover_path.read_bytes() == b"cover"
    assert calls == [("123", COVER_SIZE)]


def test_decide_output_dir_can_skip_single_volume_folder(tmp_path):
    album = FakeAlbum([FakePhoto("10", 1, "Chapter 1")])
    out = JmService._decide_output_dir(tmp_path, album, album, single_volume_folder=False)

    assert out == tmp_path


def test_decide_output_dir_keeps_multichapter_folder(tmp_path):
    album = FakeAlbum([FakePhoto("10", 1, "Chapter 1"), FakePhoto("11", 2, "Chapter 2")])
    out = JmService._decide_output_dir(tmp_path, album, album, single_volume_folder=False)

    assert out == tmp_path / "Album"


def test_decide_download_root_uses_separate_single_and_series_dirs(tmp_path):
    single = tmp_path / "single"
    series = tmp_path / "series"
    settings_obj = AppSettings(
        download_dir=str(tmp_path / "default"),
        single_download_dir=str(single),
        series_download_dir=str(series),
    )
    single_album = FakeAlbum([FakePhoto("10", 1, "Chapter 1")])
    series_album = FakeAlbum([FakePhoto("10", 1, "Chapter 1"), FakePhoto("11", 2, "Chapter 2")])

    assert JmService._decide_download_root(settings_obj, single_album) == single.resolve()
    assert JmService._decide_download_root(settings_obj, series_album) == series.resolve()


class FakeAlbum:
    id = "999"
    title = "Album"
    authors = ["Author"]
    tags = ["tag"]
    works = []
    actors = []
    description = ""
    pub_date = "2024-01-02"
    update_date = "2024-01-03"

    def __init__(self, photos):
        self.photos = photos
        for photo in photos:
            photo.from_album = self

    def __iter__(self):
        return iter(self.photos)

    def __len__(self):
        return len(self.photos)

    def is_album(self):
        return True


class FakePhoto:
    def __init__(self, photo_id, index, title):
        self.id = photo_id
        self.index = index
        self.title = title
        self.from_album = None
