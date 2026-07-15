"""Доменные события и шина (Observer).

События значимых шагов: ``VideoDiscovered``, ``VideoUploaded``,
``VideoRegistered``, ``VideoArchived``, ``VideoFailed``, ``GroupUnmapped``,
``DateFallback``. Издатель — pipeline, подписчики — ``notifications/*``.
Шина — только для побочных эффектов (уведомления, метрики); критичный путь
(реестр, S3, LMS) — явные вызовы.
"""


class EventBus:
    """Шина доменных событий: ``subscribe`` / ``publish`` (заглушка этапа 2)."""
