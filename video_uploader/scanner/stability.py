"""Проверка «файл дописан» перед обработкой."""

from datetime import UTC, datetime, timedelta
from pathlib import Path


class StabilityChecker:
    """Файл считается стабильным, если с последней записи прошло >= stability_minutes."""

    def __init__(self, stability_minutes: int) -> None:
        self._threshold = timedelta(minutes=stability_minutes)

    def is_stable(self, path: Path) -> bool:
        """True, если mtime не моложе порога и файл открывается на чтение."""
        try:
            stat = path.stat()
        except OSError:
            return False

        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        if datetime.now(UTC) - modified_at < self._threshold:
            return False

        try:
            with path.open("rb"):
                pass
        except OSError:
            return False

        return True
