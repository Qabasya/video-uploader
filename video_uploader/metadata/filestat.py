"""Резервная стратегия даты: mtime файла (с событием ``DateFallback``)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class FileStatDateExtractor:
    """Стратегия-fallback: дата из ``st_mtime``, локализованная в ``tz_name``."""

    def __init__(self, tz_name: str) -> None:
        self._tz = ZoneInfo(tz_name)

    def extract(self, path: Path) -> datetime | None:
        """mtime — абсолютный момент; локализация в tz_name не меняет сам момент."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        return datetime.fromtimestamp(mtime, tz=self._tz)
