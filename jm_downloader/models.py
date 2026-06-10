from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


SearchType = Literal["id", "site", "author", "tag", "work", "actor"]
TaskStatus = Literal["queued", "running", "completed", "failed"]


@dataclass(slots=True)
class AppSettings:
    client_impl: str = "api"
    download_dir: str = ""
    image_threads: int = 30
    photo_threads: int = 4
    keep_images: bool = False
    single_volume_folder: bool = True
    proxies: str = ""
    cookies: str = ""
    domains: str = ""
    subscription_interval_minutes: int = 60


@dataclass(slots=True)
class SearchResult:
    album_id: str
    title: str
    cover_url: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ChapterInfo:
    photo_id: str
    index: int
    title: str


@dataclass(slots=True)
class AlbumInfo:
    album_id: str
    title: str
    cover_url: str
    author: str
    authors: list[str]
    tags: list[str]
    works: list[str]
    actors: list[str]
    description: str
    page_count: int
    pub_date: str
    update_date: str
    chapters: list[ChapterInfo]


@dataclass(slots=True)
class Subscription:
    album_id: str
    title: str
    cover_url: str
    known_photo_ids: list[str]
    status: str = "active"
    last_checked_at: str = ""
    last_error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "album_id": self.album_id,
            "title": self.title,
            "cover_url": self.cover_url,
            "known_photo_ids": self.known_photo_ids,
            "status": self.status,
            "last_checked_at": self.last_checked_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class DownloadTask:
    id: str
    album_id: str
    photo_ids: list[str]
    status: TaskStatus = "queued"
    progress: str = "Queued"
    output_path: str = ""
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "album_id": self.album_id,
            "photo_ids": self.photo_ids,
            "status": self.status,
            "progress": self.progress,
            "output_path": self.output_path,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
