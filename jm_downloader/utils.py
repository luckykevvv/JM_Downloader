from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


WINDOWS_INVALID_CHARS = r'<>:"/\|?*'
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_filename(value: str, fallback: str = "untitled", max_length: int = 150) -> str:
    text = str(value or "").strip()
    text = "".join("_" if char in WINDOWS_INVALID_CHARS or ord(char) < 32 else char for char in text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = fallback
    if text.upper() in WINDOWS_RESERVED_NAMES:
        text = f"_{text}"
    if len(text) > max_length:
        text = text[:max_length].rstrip(" .")
    return text or fallback


def parse_lines(value: str) -> list[str]:
    return [line.strip() for line in (value or "").replace(",", "\n").splitlines() if line.strip()]


def parse_cookies(value: str) -> dict[str, str] | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items()}
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        cookies[key.strip()] = val.strip()
    return cookies or None


def ensure_inside(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if child_resolved != parent_resolved and parent_resolved not in child_resolved.parents:
        raise ValueError(f"Path escapes configured root: {child_resolved}")


def coerce_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        if value.strip() == "":
            return []
        return [str(item) for item in json.loads(value)]
    return [str(value)]
