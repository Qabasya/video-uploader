"""Доменные модели — неизменяемые dataclass'ы."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VideoFile:
    """Кандидат на обработку: файл записи занятия на шаре."""

    path: Path
    group_folder: str  # сырое имя подпапки VIDEO_ROOT, ДО резолвинга в slug
    size_bytes: int
    mtime: float  # os.stat().st_mtime — эпоха, UTC по определению POSIX


@dataclass(frozen=True, slots=True)
class LessonMeta:
    """Результат metadata + resolve: группа, дата занятия, блок ID для LMS.

    ``recorded_at`` обязан быть tz-aware (часовой пояс — ``TZ_NAME``).
    """

    group_slug: str
    lms: dict[str, int | str]
    recorded_at: datetime
    date_from_fallback: bool  # True, если дата взята из fallback (mtime), не из имени файла


@dataclass(frozen=True, slots=True)
class UploadResult:
    """Результат загрузки в S3: ключи видео и манифеста, размер, sha256.

    ``uploaded_at`` — в UTC.
    """

    s3_key: str
    manifest_key: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
