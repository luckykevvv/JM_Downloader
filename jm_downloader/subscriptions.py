from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from .jm_service import JmService
from .models import Subscription
from .storage import Storage


class SubscriptionManager:
    def __init__(self, storage: Storage, service: JmService):
        self.storage = storage
        self.service = service
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.check_lock = threading.Lock()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="jm-subscription-worker", daemon=True)
        self.thread.start()

    def subscribe(self, album_id: str) -> Subscription:
        album = self.service.get_album_entity(album_id)
        photo_ids = [str(photo.id) for photo in album]
        now = datetime.now(timezone.utc).isoformat()
        subscription = Subscription(
            album_id=str(album.id),
            title=str(album.title),
            cover_url=self.service.cover_url(str(album.id)),
            known_photo_ids=photo_ids,
            status="active",
            last_checked_at=now,
            last_error="",
            created_at=now,
            updated_at=now,
        )
        self.storage.upsert_subscription(subscription)
        return subscription

    def unsubscribe(self, album_id: str) -> None:
        self.storage.delete_subscription(album_id)

    def check_all(self) -> dict[str, int]:
        if not self.check_lock.acquire(blocking=False):
            return {"checked": 0, "updated": 0, "skipped": 1}
        checked = 0
        updated = 0
        try:
            for subscription in self.storage.list_subscriptions():
                checked += 1
                if self.check_one(subscription):
                    updated += 1
        finally:
            self.check_lock.release()
        return {"checked": checked, "updated": updated, "skipped": 0}

    def check_one(self, subscription: Subscription) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        try:
            album = self.service.get_album_entity(subscription.album_id)
            current_photo_ids = [str(photo.id) for photo in album]
            known = set(subscription.known_photo_ids)
            new_photo_ids = [photo_id for photo_id in current_photo_ids if photo_id not in known]
            if new_photo_ids:
                self.storage.update_subscription(
                    subscription.album_id,
                    title=str(album.title),
                    cover_url=self.service.cover_url(str(album.id)),
                    status=f"downloading {len(new_photo_ids)} new chapter(s)",
                    last_checked_at=now,
                    last_error="",
                )
                self.service.download_album(
                    subscription.album_id,
                    new_photo_ids,
                    progress=lambda message: self.storage.update_subscription(
                        subscription.album_id,
                        status=message,
                    ),
                )
                self.storage.update_subscription(
                    subscription.album_id,
                    known_photo_ids=current_photo_ids,
                    title=str(album.title),
                    cover_url=self.service.cover_url(str(album.id)),
                    status=f"downloaded {len(new_photo_ids)} new chapter(s)",
                    last_checked_at=datetime.now(timezone.utc).isoformat(),
                    last_error="",
                )
                return True

            self.storage.update_subscription(
                subscription.album_id,
                known_photo_ids=current_photo_ids,
                title=str(album.title),
                cover_url=self.service.cover_url(str(album.id)),
                status="active",
                last_checked_at=now,
                last_error="",
            )
            return False
        except Exception as exc:
            self.storage.update_subscription(
                subscription.album_id,
                status="error",
                last_checked_at=now,
                last_error=str(exc),
            )
            return False

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            interval = max(1, int(self.storage.get_settings("").subscription_interval_minutes))
            self.stop_event.wait(interval * 60)
            if self.stop_event.is_set():
                break
            self.check_all()
