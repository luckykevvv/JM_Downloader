from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("JM_DATA_DIR", BASE_DIR / "data")).resolve()
DOWNLOAD_DIR = Path(os.getenv("JM_DOWNLOAD_DIR", BASE_DIR / "downloads")).resolve()
DATABASE_PATH = Path(os.getenv("JM_DATABASE_PATH", DATA_DIR / "app.db")).resolve()
ADMIN_PASSWORD = os.getenv("JM_ADMIN_PASSWORD", "admin")
SESSION_SECRET = os.getenv("JM_SESSION_SECRET", "change-me-in-production")


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
