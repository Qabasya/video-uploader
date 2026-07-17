"""Фабрика лог-хендлеров из ``Settings`` (Factory + Strategy).

file (RotatingFileHandler, всегда), loki (при ``LOKI_URL``). Telegram-хендлер
отложен 2026-07-17 — Telegram-уведомления обслуживает отдельный aiogram-сервис
пользователя (см. logging_setup/telegram.py, notifications/telegram.py).
"""

import logging
from logging.handlers import RotatingFileHandler

from video_uploader.config import Settings
from video_uploader.logging_setup.loki import LokiHandler

_LOGGER_NAME = "video_uploader"
_LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
_LOG_FILE_BACKUP_COUNT = 5
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(settings: Settings) -> None:
    """Настраивает логгер ``"video_uploader"``: file всегда, loki — по наличию ``LOKI_URL``."""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter(_FORMAT)

    logs_dir = settings.data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        logs_dir / "uploader.log",
        maxBytes=_LOG_FILE_MAX_BYTES,
        backupCount=_LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if settings.loki_url is not None:
        loki_handler = LokiHandler(settings.loki_url)
        loki_handler.setFormatter(formatter)
        logger.addHandler(loki_handler)
