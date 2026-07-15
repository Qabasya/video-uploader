"""Фабрика лог-хендлеров из ``Settings`` (Factory + Strategy).

Этап 9: file (RotatingFileHandler, всегда), loki (при ``LOKI_URL``),
telegram (ERROR+, при ``TELEGRAM_*``).
"""
