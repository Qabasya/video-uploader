"""Единственный источник соглашения о ключах S3 (видео и манифест).

Формат: ``{prefix}/{group_slug}/{yyyy}/{mm}/{yyyy-mm-dd}_{hh-mm}_{sha8}{ext}``;
в ключах допустимы только ``[a-z0-9./_-]``.
"""

import re
from datetime import datetime

_ALLOWED_KEY_CHARS = re.compile(r"[a-z0-9./_-]+")


class KeyBuilder:
    """Сборка ключей видео и манифеста по соглашению (единственный источник)."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def build_video_key(self, group_slug: str, recorded_at: datetime, sha256: str, ext: str) -> str:
        """``{prefix}/{group_slug}/{yyyy}/{mm}/{yyyy-mm-dd}_{hh-mm}_{sha8}{ext}``."""
        key = (
            f"{self._prefix}/{group_slug}/{recorded_at:%Y}/{recorded_at:%m}/"
            f"{recorded_at:%Y-%m-%d}_{recorded_at:%H-%M}_{sha256[:8]}{ext.lower()}"
        )
        self._validate(key)
        return key

    def build_manifest_key(self, video_key: str) -> str:
        """``{video_key}.json`` — манифест лежит рядом с видео."""
        return f"{video_key}.json"

    @staticmethod
    def _validate(key: str) -> None:
        if not _ALLOWED_KEY_CHARS.fullmatch(key):
            raise ValueError(f"ключ S3 содержит недопустимые символы: {key!r}")
