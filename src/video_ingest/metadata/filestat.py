"""Резервная стратегия даты: mtime файла (с событием ``DateFallback``)."""


class FileStatDateExtractor:
    """Стратегия-fallback: дата из ``st_mtime`` (заглушка этапа 5)."""
