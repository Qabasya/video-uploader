"""Доменные события и шина (Observer).

События значимых шагов: ``VideoDiscovered``, ``VideoUploaded``,
``VideoRegistered``, ``VideoArchived``, ``VideoFailed``, ``GroupUnmapped``,
``DateFallback``. Издатель — pipeline, подписчики — ``notifications/*``.
Шина — только для побочных эффектов (уведомления, метрики); критичный путь
(реестр, S3, LMS) — явные вызовы.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, cast

logger = logging.getLogger(__name__)

E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class VideoDiscovered:
    """Сканер нашёл кандидата, прошедшего фильтр расширений и имени."""

    path: Path


@dataclass(frozen=True, slots=True)
class VideoUploaded:
    """Файл успешно загружен и верифицирован в S3."""

    path: Path
    s3_key: str


@dataclass(frozen=True, slots=True)
class VideoRegistered:
    """Видео зарегистрировано в LMS (или засчитано в режиме ``DRY_RUN``)."""

    path: Path
    s3_key: str


@dataclass(frozen=True, slots=True)
class VideoArchived:
    """Исходник перемещён в архивную подпапку своей группы."""

    path: Path
    archived_path: Path


@dataclass(frozen=True, slots=True)
class VideoFailed:
    """Обработка файла завершилась ошибкой после исчерпания попыток."""

    path: Path
    error: str
    attempts: int


@dataclass(frozen=True, slots=True)
class GroupUnmapped:
    """Папка на шаре отсутствует в ``groups.yaml`` — файлы пропускаются."""

    group_folder: str


@dataclass(frozen=True, slots=True)
class DateFallback:
    """Дата занятия не извлечена из имени файла, использован mtime."""

    path: Path


class EventBus:
    """Синхронная шина доменных событий: ``subscribe`` / ``publish``.

    Хендлеры хранятся под ``Any`` только внутри реализации: приведение типа
    возвращает точную сигнатуру ``Callable[[E], None]`` там, где это видит
    вызывающий код (``subscribe``/``publish`` типизированы через ``TypeVar``
    без утечки ``Any`` наружу). Экземпляр создаётся в composition root —
    глобального синглтона нет.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Any], list[Callable[[Any], None]]] = {}

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Регистрирует ``handler`` на события типа ``event_type``."""
        self._handlers.setdefault(event_type, []).append(cast("Callable[[Any], None]", handler))

    def publish(self, event: E) -> None:
        """Синхронно вызывает всех подписчиков ``type(event)``.

        Ошибка в одном подписчике логируется и не мешает ни остальным
        подписчикам, ни публикующему коду — шина только для побочных эффектов.
        """
        for handler in self._handlers.get(type(event), []):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "подписчик %r упал на событии %r",
                    handler,
                    event,
                    extra={"event": "event_subscriber_error"},
                )
