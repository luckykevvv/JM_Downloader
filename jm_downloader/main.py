from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .auth import COOKIE_NAME, api_require_login, make_session_cookie, password_is_valid, require_login
from .config import DATABASE_PATH, DOWNLOAD_DIR, ensure_runtime_dirs
from .jm_service import JmService
from .models import AppSettings
from .storage import Storage
from .subscriptions import SubscriptionManager
from .tasks import DownloadQueue

ensure_runtime_dirs()

app = FastAPI(title="JM Downloader")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

storage = Storage(DATABASE_PATH)


def get_settings() -> AppSettings:
    return storage.get_settings(str(DOWNLOAD_DIR))


jm_service = JmService(get_settings)
download_queue = DownloadQueue(storage, jm_service)
download_queue.start()
subscription_manager = SubscriptionManager(storage, jm_service)
subscription_manager.start()


class DownloadPayload(BaseModel):
    album_id: str
    photo_ids: list[str] | None = None


class SubscribePayload(BaseModel):
    album_id: str


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.cookies.get(COOKIE_NAME):
        try:
            require_login(request)
            return RedirectResponse("/", status_code=303)
        except HTTPException:
            pass
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/login")
def login(request: Request, password: str = Form(...)):
    if not password_is_valid(password):
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid password"}, status_code=401)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE_NAME, make_session_cookie(), httponly=True, samesite="lax")
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"subscriptions": storage.list_subscriptions()})


@app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def settings_page(request: Request, saved: str = ""):
    return templates.TemplateResponse(request, "settings.html", {"settings": get_settings(), "saved": saved})


@app.post("/settings", dependencies=[Depends(require_login)])
def save_settings(
    client_impl: str = Form("api"),
    download_dir: str = Form(str(DOWNLOAD_DIR)),
    single_download_dir: str = Form(""),
    series_download_dir: str = Form(""),
    image_threads: int = Form(30),
    photo_threads: int = Form(4),
    keep_images: bool = Form(False),
    single_volume_folder: bool = Form(False),
    subscription_interval_minutes: int = Form(60),
    proxies: str = Form(""),
    cookies: str = Form(""),
    domains: str = Form(""),
):
    storage.save_settings(
        AppSettings(
            client_impl=client_impl,
            download_dir=download_dir,
            single_download_dir=single_download_dir or download_dir,
            series_download_dir=series_download_dir or download_dir,
            image_threads=max(1, image_threads),
            photo_threads=max(1, photo_threads),
            keep_images=keep_images,
            single_volume_folder=single_volume_folder,
            subscription_interval_minutes=max(1, subscription_interval_minutes),
            proxies=proxies,
            cookies=cookies,
            domains=domains,
        )
    )
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.get("/album/{album_id}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def album_page(request: Request, album_id: str):
    return templates.TemplateResponse(request, "album.html", {"album_id": album_id})


@app.get("/tasks", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def tasks_page(request: Request):
    return templates.TemplateResponse(request, "tasks.html", {"tasks": storage.list_tasks()})


@app.get("/api/search", dependencies=[Depends(api_require_login)])
def api_search(
    query: str = Query(""),
    type: str = Query("site"),
    page: int = Query(1, ge=1),
    order: str = Query("mr"),
    time: str = Query("a"),
):
    try:
        results = jm_service.search(query, type, page, order, time)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"results": [asdict(result) for result in results]}


@app.get("/api/albums/{album_id}", dependencies=[Depends(api_require_login)])
def api_album(album_id: str):
    album = jm_service.get_album(album_id)
    return {
        "album_id": album.album_id,
        "title": album.title,
        "author": album.author,
        "authors": album.authors,
        "tags": album.tags,
        "works": album.works,
        "actors": album.actors,
        "description": album.description,
        "page_count": album.page_count,
        "pub_date": album.pub_date,
        "update_date": album.update_date,
        "cover_url": album.cover_url,
        "chapters": [asdict(chapter) for chapter in album.chapters],
    }


@app.post("/api/downloads", dependencies=[Depends(api_require_login)])
def api_create_download(payload: DownloadPayload):
    task = download_queue.enqueue(payload.album_id, payload.photo_ids or [])
    return task.as_dict()


@app.get("/api/subscriptions", dependencies=[Depends(api_require_login)])
def api_list_subscriptions():
    return {"subscriptions": [subscription.as_dict() for subscription in storage.list_subscriptions()]}


@app.post("/api/subscriptions", dependencies=[Depends(api_require_login)])
def api_subscribe(payload: SubscribePayload):
    try:
        subscription = subscription_manager.subscribe(payload.album_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return subscription.as_dict()


@app.delete("/api/subscriptions/{album_id}", dependencies=[Depends(api_require_login)])
def api_unsubscribe(album_id: str):
    subscription_manager.unsubscribe(album_id)
    return {"ok": True}


@app.post("/api/subscriptions/check", dependencies=[Depends(api_require_login)])
def api_check_subscriptions():
    thread = threading.Thread(target=subscription_manager.check_all, name="jm-subscription-manual-check", daemon=True)
    thread.start()
    return {"ok": True}


@app.get("/api/downloads/{task_id}", dependencies=[Depends(api_require_login)])
def api_get_download(task_id: str):
    task = storage.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.as_dict()


@app.get("/api/downloads/{task_id}/events", dependencies=[Depends(api_require_login)])
async def api_download_events(task_id: str):
    async def events():
        last_payload = ""
        while True:
            task = storage.get_task(task_id)
            if task is None:
                yield "event: error\ndata: Task not found\n\n"
                break
            payload = json.dumps(task.as_dict(), ensure_ascii=False)
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            if task.status in {"completed", "failed"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/settings/test", dependencies=[Depends(api_require_login)])
def api_test_settings():
    try:
        jm_service.test_connection()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return {"ok": True}
