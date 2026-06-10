from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AppSettings, DownloadTask, Subscription


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def init_db(self) -> None:
        with self.connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    album_id TEXT NOT NULL,
                    photo_ids TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    album_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    cover_url TEXT NOT NULL,
                    known_photo_ids TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_checked_at TEXT NOT NULL,
                    last_error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get_settings(self, default_download_dir: str) -> AppSettings:
        with self.connect() as con:
            rows = con.execute("SELECT key, value FROM settings").fetchall()
        values: dict[str, str] = {row["key"]: row["value"] for row in rows}
        return AppSettings(
            client_impl=values.get("client_impl", "api"),
            download_dir=values.get("download_dir", default_download_dir),
            image_threads=int(values.get("image_threads", "30") or 30),
            photo_threads=int(values.get("photo_threads", "4") or 4),
            keep_images=values.get("keep_images", "false") == "true",
            single_volume_folder=values.get("single_volume_folder", "true") == "true",
            proxies=values.get("proxies", ""),
            cookies=values.get("cookies", ""),
            domains=values.get("domains", ""),
            subscription_interval_minutes=int(values.get("subscription_interval_minutes", "60") or 60),
        )

    def save_settings(self, settings: AppSettings) -> None:
        data = {
            "client_impl": settings.client_impl,
            "download_dir": settings.download_dir,
            "image_threads": str(settings.image_threads),
            "photo_threads": str(settings.photo_threads),
            "keep_images": "true" if settings.keep_images else "false",
            "single_volume_folder": "true" if settings.single_volume_folder else "false",
            "proxies": settings.proxies,
            "cookies": settings.cookies,
            "domains": settings.domains,
            "subscription_interval_minutes": str(settings.subscription_interval_minutes),
        }
        with self.connect() as con:
            con.executemany(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                data.items(),
            )

    def create_task(self, task: DownloadTask) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO tasks(id, album_id, photo_ids, status, progress, output_path, error, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.album_id,
                    json.dumps(task.photo_ids),
                    task.status,
                    task.progress,
                    task.output_path,
                    task.error,
                    task.created_at,
                    task.updated_at,
                ),
            )

    def update_task(self, task_id: str, **changes: Any) -> None:
        if not changes:
            return
        changes["updated_at"] = datetime.now(timezone.utc).isoformat()
        assignments = ", ".join(f"{key} = ?" for key in changes)
        values = [json.dumps(value) if key == "photo_ids" else value for key, value in changes.items()]
        values.append(task_id)
        with self.connect() as con:
            con.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", values)

    def get_task(self, task_id: str) -> DownloadTask | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self, limit: int = 100) -> list[DownloadTask]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_task(row) for row in rows]

    def upsert_subscription(self, subscription: Subscription) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO subscriptions(
                    album_id, title, cover_url, known_photo_ids, status, last_checked_at, last_error, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(album_id) DO UPDATE SET
                    title = excluded.title,
                    cover_url = excluded.cover_url,
                    known_photo_ids = excluded.known_photo_ids,
                    status = excluded.status,
                    last_checked_at = excluded.last_checked_at,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    subscription.album_id,
                    subscription.title,
                    subscription.cover_url,
                    json.dumps(subscription.known_photo_ids),
                    subscription.status,
                    subscription.last_checked_at,
                    subscription.last_error,
                    subscription.created_at,
                    subscription.updated_at,
                ),
            )

    def get_subscription(self, album_id: str) -> Subscription | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM subscriptions WHERE album_id = ?", (album_id,)).fetchone()
        return self._row_to_subscription(row) if row else None

    def list_subscriptions(self) -> list[Subscription]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM subscriptions ORDER BY updated_at DESC").fetchall()
        return [self._row_to_subscription(row) for row in rows]

    def delete_subscription(self, album_id: str) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM subscriptions WHERE album_id = ?", (album_id,))

    def update_subscription(self, album_id: str, **changes: Any) -> None:
        if not changes:
            return
        changes["updated_at"] = datetime.now(timezone.utc).isoformat()
        assignments = ", ".join(f"{key} = ?" for key in changes)
        values = [json.dumps(value) if key == "known_photo_ids" else value for key, value in changes.items()]
        values.append(album_id)
        with self.connect() as con:
            con.execute(f"UPDATE subscriptions SET {assignments} WHERE album_id = ?", values)

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> DownloadTask:
        return DownloadTask(
            id=row["id"],
            album_id=row["album_id"],
            photo_ids=json.loads(row["photo_ids"]),
            status=row["status"],
            progress=row["progress"],
            output_path=row["output_path"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_subscription(row: sqlite3.Row) -> Subscription:
        return Subscription(
            album_id=row["album_id"],
            title=row["title"],
            cover_url=row["cover_url"],
            known_photo_ids=json.loads(row["known_photo_ids"]),
            status=row["status"],
            last_checked_at=row["last_checked_at"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
