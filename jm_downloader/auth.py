from __future__ import annotations

import hmac
from hashlib import sha256

from fastapi import HTTPException, Request, status

from .config import ADMIN_PASSWORD, SESSION_SECRET


COOKIE_NAME = "jm_session"


def _signature(value: str) -> str:
    return hmac.new(SESSION_SECRET.encode("utf-8"), value.encode("utf-8"), sha256).hexdigest()


def make_session_cookie() -> str:
    value = "admin"
    return f"{value}:{_signature(value)}"


def verify_session_cookie(cookie: str | None) -> bool:
    if not cookie or ":" not in cookie:
        return False
    value, signature = cookie.split(":", 1)
    return value == "admin" and hmac.compare_digest(signature, _signature(value))


def password_is_valid(password: str) -> bool:
    return hmac.compare_digest(password, ADMIN_PASSWORD)


def require_login(request: Request) -> None:
    if not verify_session_cookie(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})


def api_require_login(request: Request) -> None:
    if not verify_session_cookie(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
