from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


ERROR_MESSAGES = {
    "INVALID_URL": "Vlozte platny odkaz na YouTube.",
    "VIDEO_UNAVAILABLE": "Video neni dostupne.",
    "PRIVATE_VIDEO": "Video je soukrome.",
    "AGE_OR_LOGIN_REQUIRED": "Obsah vyzaduje prihlaseni a aplikace jej nestahuje.",
    "DRM_PROTECTED": "Obsah je technicky chraneny a nelze jej stahnout.",
    "NO_COMPATIBLE_FORMAT": "Pro zvoleny format nebyla nalezena vhodna stopa.",
    "TARGET_NOT_WRITABLE": "Do vybrane slozky nelze zapisovat.",
    "NETWORK_ERROR": "Pripojeni bylo preruseno.",
    "PROCESS_NOT_FOUND": "Stahovaci proces uz nebezi.",
    "YTDLP_MISSING": "Program yt-dlp nebyl nalezen.",
    "JOB_NOT_FOUND": "Uloha nebyla nalezena.",
}


def message_for(code: str, fallback: str = "Nastala neocekavana chyba.") -> str:
    return ERROR_MESSAGES.get(code, fallback)

