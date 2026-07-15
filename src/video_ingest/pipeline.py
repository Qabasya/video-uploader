"""Оркестратор обработки одного файла.

Шаги: scan → stability → dedup → metadata → resolve → upload → verify →
register → cleanup. Зависит только от Protocol-интерфейсов; на значимых
шагах публикует доменные события в ``EventBus``.
"""


class VideoPipeline:
    """Последовательность шагов обработки одного кандидата (заглушка этапа 8)."""
