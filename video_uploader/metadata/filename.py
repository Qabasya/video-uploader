"""Дата из имени файла по ``DATE_REGEX`` (default — записи Телемоста)."""

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_DEFAULT_PATTERN = (
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"_(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})"
)


class FilenameDateExtractor:
    """Стратегия: блок ``ГГГГ-ММ-ДД_ЧЧ-ММ-СС``в имени файла.
    Важно выставить в OBS пункт 'Формировать имя без пробелов'"""

    def __init__(self, tz_name: str, pattern: str | None = None) -> None:
        self._tz = ZoneInfo(tz_name)
        self._pattern = re.compile(pattern or _DEFAULT_PATTERN)

    def extract(self, path: Path) -> datetime | None:
        """Ищет блок даты в имени файла; ``None``, если не нашла или дата невалидна."""
        match = self._pattern.search(path.name)
        if match is None:
            return None

        groups = match.groupdict()
        try:
            return datetime(
                year=int(groups["year"]),
                month=int(groups["month"]),
                day=int(groups["day"]),
                hour=int(groups["hour"]),
                minute=int(groups["minute"]),
                second=int(groups["second"]),
                tzinfo=self._tz,
            )
        except ValueError:
            return None
