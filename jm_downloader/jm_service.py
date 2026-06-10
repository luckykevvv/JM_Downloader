from __future__ import annotations

import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Iterable

import jmcomic
from jmcomic import JmDownloader, JmOption
from jmcomic.jm_toolkit import JmcomicText

from .comicinfo import build_comicinfo_xml
from .models import AlbumInfo, AppSettings, ChapterInfo, SearchResult
from .utils import ensure_inside, parse_cookies, parse_lines, safe_filename


class DownloadError(RuntimeError):
    pass


class SelectedPhotoDownloader(JmDownloader):
    selected_photo_ids: set[str] | None = None
    progress_callback: Callable[[str], None] | None = None

    def emit_progress(self, message: str) -> None:
        callback = type(self).progress_callback
        if callback:
            callback(message)

    def do_filter(self, detail):
        if detail.is_album() and self.selected_photo_ids:
            return [photo for photo in detail if str(photo.id) in self.selected_photo_ids]
        return detail

    def before_album(self, album):
        self.emit_progress(f"Album loaded: {album.title}")
        return super().before_album(album)

    def before_photo(self, photo):
        self.emit_progress(f"Downloading chapter {photo.index}: {photo.title}")
        return super().before_photo(photo)

    def after_photo(self, photo):
        self.emit_progress(f"Downloaded chapter {photo.index}: {photo.title}")
        return super().after_photo(photo)


class JmService:
    def __init__(self, settings_provider: Callable[[], AppSettings]):
        self.settings_provider = settings_provider
        self._album_cache: dict[str, tuple[float, object]] = {}
        self._album_info_cache: dict[str, tuple[float, AlbumInfo]] = {}
        self._cache_lock = threading.Lock()
        self.album_cache_ttl_seconds = 600

    def settings(self) -> AppSettings:
        return self.settings_provider()

    def build_option(self, download_base: Path | None = None, impl: str | None = None) -> JmOption:
        settings = self.settings()
        base_dir = str(download_base or Path(settings.download_dir).resolve())
        meta_data: dict[str, object] = {}

        cookies = parse_cookies(settings.cookies)
        if cookies:
            meta_data["cookies"] = cookies

        proxies = self._parse_proxies(settings.proxies)
        if proxies:
            meta_data["proxies"] = proxies

        domains = parse_lines(settings.domains)
        option_dict = {
            "log": True,
            "dir_rule": {
                "rule": "Bd_Atitle_Pindextitle",
                "base_dir": base_dir,
                "normalize_zh": None,
            },
            "download": {
                "cache": True,
                "image": {"decode": True, "suffix": None},
                "threading": {
                    "image": max(1, int(settings.image_threads)),
                    "photo": max(1, int(settings.photo_threads)),
                },
            },
            "client": {
                "impl": impl or settings.client_impl,
                "domain": domains,
                "cache": "level_option",
                "retry_times": 5,
                "postman": {
                    "type": "curl_cffi",
                    "meta_data": meta_data,
                },
            },
            "plugins": {"valid": "log"},
        }
        return JmOption.construct(option_dict)

    def client(self, impl: str | None = None):
        return self.build_option(impl=impl).build_jm_client()

    def detail_client(self):
        return self.client("html")

    def search(
        self,
        query: str,
        search_type: str,
        page: int = 1,
        order: str = "mr",
        time: str = "a",
    ) -> list[SearchResult]:
        query = (query or "").strip()
        if not query:
            return []

        client = self.client()
        if search_type == "id":
            album = client.get_album_detail(query)
            return [self._album_to_search_result(album)]

        methods = {
            "site": client.search_site,
            "author": client.search_author,
            "tag": client.search_tag,
            "work": client.search_work,
            "actor": client.search_actor,
        }
        method = methods.get(search_type)
        if method is None:
            raise ValueError(f"Unsupported search type: {search_type}")

        page_data = method(query, page=page, order_by=order, time=time)
        if getattr(page_data, "is_single_album", False):
            return [self._album_to_search_result(page_data.single_album)]

        return [
            SearchResult(
                album_id=str(album_id),
                title=str(info.get("name", "")),
                cover_url=self.cover_url(str(album_id)),
                author=self._search_info_author(info),
                tags=list(info.get("tags", [])),
            )
            for album_id, info in page_data.content
        ]

    def get_album(self, album_id: str) -> AlbumInfo:
        key = str(album_id)
        cached = self._get_cache(self._album_info_cache, key)
        if cached is not None:
            return cached
        album = self.get_album_entity(key)
        info = self._album_to_info(album)
        self._set_cache(self._album_info_cache, key, info)
        return info

    def get_album_entity(self, album_id: str):
        key = str(album_id)
        cached = self._get_cache(self._album_cache, key)
        if cached is not None:
            return cached
        try:
            album = self.detail_client().get_album_detail(key)
            if not self._date_is_missing(getattr(album, "pub_date", "")) or not self._date_is_missing(getattr(album, "update_date", "")):
                self._set_cache(self._album_cache, key, album)
                return album
        except Exception:
            pass
        album = self.client().get_album_detail(key)
        self._set_cache(self._album_cache, key, album)
        return album

    def download_album(
        self,
        album_id: str,
        selected_photo_ids: Iterable[str] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> Path:
        settings = self.settings()
        download_root = Path(settings.download_dir).resolve()
        download_root.mkdir(parents=True, exist_ok=True)

        selected = {str(pid) for pid in selected_photo_ids or [] if str(pid).strip()}
        with tempfile.TemporaryDirectory(prefix="jm-download-") as temp_dir:
            option = self.build_option(Path(temp_dir))

            class TaskDownloader(SelectedPhotoDownloader):
                selected_photo_ids = selected or None
                progress_callback = progress

            album, downloader = jmcomic.download_album(
                album_id,
                option=option,
                downloader=TaskDownloader,
                check_exception=True,
            )
            metadata_album = self._best_metadata_album(album)
            output_dir = self._decide_output_dir(download_root, metadata_album, album, settings.single_volume_folder)
            ensure_inside(download_root, output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            self._write_cbz_files(album, downloader, output_dir, selected, metadata_album)

            if settings.keep_images:
                self._copy_images(Path(temp_dir), output_dir)

            if progress:
                progress(f"Completed: {output_dir}")
            return output_dir

    def test_connection(self) -> list[SearchResult]:
        return self.search("1", "id", 1, "mr", "a")

    def _write_cbz_files(self, album, downloader, album_dir: Path, selected: set[str], metadata_album=None) -> None:
        metadata_album = metadata_album or album
        photo_dict = downloader.download_success_dict.get(album, {})
        if not photo_dict:
            raise DownloadError("No chapters were downloaded.")

        selected_count = len(photo_dict)
        multi_chapter = len(album) > 1
        for photo, image_list in sorted(photo_dict.items(), key=lambda item: int(item[0].index)):
            if selected and str(photo.id) not in selected:
                continue
            title = photo.title if multi_chapter else metadata_album.title
            cbz_name = safe_filename(
                f"{int(photo.index):03d} - {title}" if multi_chapter else album.title,
                f"JM{album.id}-{photo.id}",
            )
            cbz_path = album_dir / f"{cbz_name}.cbz"
            ensure_inside(album_dir, cbz_path)
            comicinfo = build_comicinfo_xml(
                album=metadata_album,
                photo=photo,
                title=title,
                number=int(photo.index),
                count=selected_count,
                page_count=len(image_list),
                web=f"https://18comic.vip/album/{album.id}",
            )
            with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("ComicInfo.xml", comicinfo)
                for path, _image in sorted(image_list, key=lambda item: item[1].index):
                    source = Path(path)
                    if source.exists():
                        archive.write(source, source.name)

    @staticmethod
    def _copy_images(temp_dir: Path, album_dir: Path) -> None:
        image_root = album_dir / "_images"
        if image_root.exists():
            shutil.rmtree(image_root)
        shutil.copytree(temp_dir, image_root)

    @staticmethod
    def _decide_output_dir(download_root: Path, metadata_album, album, single_volume_folder: bool) -> Path:
        if len(album) == 1 and not single_volume_folder:
            return download_root
        return download_root / safe_filename(metadata_album.title, f"JM{album.id}")

    @staticmethod
    def cover_url(album_id: str, size: str = "_3x4") -> str:
        return JmcomicText.get_album_cover_url(str(album_id), size=size)

    @classmethod
    def _album_to_search_result(cls, album) -> SearchResult:
        return SearchResult(
            album_id=str(album.id),
            title=str(album.title),
            cover_url=cls.cover_url(str(album.id)),
            author=str(getattr(album, "author", "") or ""),
            tags=list(getattr(album, "tags", []) or []),
        )

    @classmethod
    def _album_to_info(cls, album) -> AlbumInfo:
        chapters: list[ChapterInfo] = []
        for photo in album:
            chapters.append(ChapterInfo(photo_id=str(photo.id), index=int(photo.index), title=str(photo.title)))
        return AlbumInfo(
            album_id=str(album.id),
            title=str(album.title),
            cover_url=cls.cover_url(str(album.id)),
            author=str(getattr(album, "author", "")),
            authors=list(getattr(album, "authors", []) or []),
            tags=list(getattr(album, "tags", []) or []),
            works=list(getattr(album, "works", []) or []),
            actors=list(getattr(album, "actors", []) or []),
            description=str(getattr(album, "description", "") or ""),
            page_count=int(getattr(album, "page_count", 0) or 0),
            pub_date=str(getattr(album, "pub_date", "") or ""),
            update_date=str(getattr(album, "update_date", "") or ""),
            chapters=chapters,
        )

    def _best_metadata_album(self, album):
        if not self._date_is_missing(getattr(album, "pub_date", "")) or not self._date_is_missing(getattr(album, "update_date", "")):
            return album
        try:
            return self.detail_client().get_album_detail(album.id)
        except Exception:
            return album

    @staticmethod
    def _date_is_missing(value: object) -> bool:
        text = str(value or "").strip()
        return text == "" or text == "0"

    @staticmethod
    def _parse_proxies(value: str) -> dict[str, str] | None:
        raw = (value or "").strip()
        if not raw:
            return None
        if raw.startswith("{"):
            import json

            data = json.loads(raw)
            return {str(k): str(v) for k, v in data.items()}
        return {"http": raw, "https": raw}

    @staticmethod
    def _search_info_author(info: dict) -> str:
        authors = info.get("authors")
        if isinstance(authors, list) and authors:
            return str(authors[0])
        author = info.get("author")
        return str(author or "")

    def _get_cache(self, cache: dict[str, tuple[float, object]], key: str):
        now = time.monotonic()
        with self._cache_lock:
            item = cache.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at < now:
                cache.pop(key, None)
                return None
            return value

    def _set_cache(self, cache: dict[str, tuple[float, object]], key: str, value) -> None:
        with self._cache_lock:
            cache[key] = (time.monotonic() + self.album_cache_ttl_seconds, value)
