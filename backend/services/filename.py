from __future__ import annotations

import re

WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(value: str, fallback: str = "download", max_length: int = 120) -> str:
    cleaned = INVALID_CHARS.sub("_", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED:
        cleaned = f"{cleaned}_"
    return cleaned[:max_length].rstrip(" .") or fallback

