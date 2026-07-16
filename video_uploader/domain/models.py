"""Доменные модели — неизменяемые dataclass'ы (поля — этап 2)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VideoFile:
    """Кандидат на обработку: файл записи занятия на шаре."""


@dataclass(frozen=True, slots=True)
class LessonMeta:
    """Метаданные занятия: группа, дата записи, блок lms."""


@dataclass(frozen=True, slots=True)
class UploadResult:
    """Результат загрузки в S3: ключи видео и манифеста, размер, sha256."""
