"""Дата из имени файла по ``DATE_REGEX`` (default — записи Телемоста)."""

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_DEFAULT_PATTERN = (
    r"(?P<day>\d{2})_(?P<month>\d{2})_(?P<year>\d{2})"
    r"_(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})"
)


class FilenameDateExtractor:
    """Стратегия: блок ``ДД_ММ_ГГ_ЧЧ_ММ_СС`` (или кастомный DATE_REGEX) в имени файла."""

    def __init__(self, tz_name: str, pattern: str | None = None) -> None:
        self._tz = ZoneInfo(tz_name)
        self._pattern = re.compile(pattern or _DEFAULT_PATTERN)

    def extract(self, path: Path) -> datetime | None:
        """Ищет блок даты в имени файла; ``None``, если не нашла или дата невалидна."""
        match = self._pattern.search(path.name)
        if match is None:
            return None

        groups = match.groupdict()
        year = self._normalize_year(groups["year"])

        try:
            return datetime(
                year=year,
                month=int(groups["month"]),
                day=int(groups["day"]),
                hour=int(groups["hour"]),
                minute=int(groups["minute"]),
                second=int(groups["second"]),
                tzinfo=self._tz,
            )
        except ValueError:
            return None

    @staticmethod
    def _normalize_year(raw: str) -> int:
        year = int(raw)
        if len(raw) == 2:  # ГГ из имени Телемоста -> 20ГГ
            year += 2000
        return year
