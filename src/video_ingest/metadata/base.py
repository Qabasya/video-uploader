"""Protocol-интерфейсы стратегий извлечения даты занятия."""

from datetime import datetime
from pathlib import Path
from typing import Protocol


class DateExtractor(Protocol):
    """Strategy: извлечение даты записи занятия из файла."""

    def extract(self, path: Path) -> datetime | None:
        """Возвращает дату записи или ``None``, если стратегия неприменима."""
        ...
