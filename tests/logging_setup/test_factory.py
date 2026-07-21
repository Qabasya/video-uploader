"""Тесты configure_logging: набор хендлеров по конфигу, идемпотентность, доставка сообщения."""

import logging
import logging.handlers
from collections.abc import Iterator
from pathlib import Path

import pytest

from video_uploader.config import Settings
from video_uploader.logging_setup.factory import configure_logging
from video_uploader.logging_setup.loki import LokiHandler

REQUIRED = {
    "s3_bucket": "bucket",
    "s3_access_key": "access-key",
    "s3_secret_key": "top-secret",
    "lms_base_url": "http://lms.local",
    "lms_hmac_secret": "hmac-secret",
}


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, **{**REQUIRED, **overrides})


@pytest.fixture(autouse=True)
def reset_logger() -> Iterator[None]:
    """Логгер video_uploader — общий на процесс; чистим хендлеры до и после каждого теста."""
    logger = logging.getLogger("video_uploader")
    logger.handlers.clear()
    yield
    logger.handlers.clear()


class TestHandlerSelection:
    def test_file_handler_always_present(self, tmp_path: Path) -> None:
        configure_logging(make_settings(tmp_path))
        logger = logging.getLogger("video_uploader")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.handlers.RotatingFileHandler)

    def test_loki_handler_added_when_configured(self, tmp_path: Path) -> None:
        configure_logging(make_settings(tmp_path, loki_url="http://loki.local"))
        logger = logging.getLogger("video_uploader")
        assert any(isinstance(h, LokiHandler) for h in logger.handlers)
        assert len(logger.handlers) == 2

    def test_repeated_calls_do_not_duplicate_handlers(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, loki_url="http://loki.local")
        configure_logging(settings)
        configure_logging(settings)
        logger = logging.getLogger("video_uploader")
        assert len(logger.handlers) == 2


class TestLoggerConfig:
    def test_propagate_disabled(self, tmp_path: Path) -> None:
        configure_logging(make_settings(tmp_path))
        assert logging.getLogger("video_uploader").propagate is False

    def test_message_reaches_log_file(self, tmp_path: Path) -> None:
        configure_logging(make_settings(tmp_path))
        logger = logging.getLogger("video_uploader.some.module")

        logger.info("тестовое сообщение для проверки доставки")

        log_file = tmp_path / "logs" / "uploader.log"
        assert log_file.exists()
        assert "тестовое сообщение для проверки доставки" in log_file.read_text(encoding="utf-8")

    def test_loki_formatter_omits_asctime(self, tmp_path: Path) -> None:
        """Loki хранит свою метку времени (record.created в timestamp_ns) — в тексте
        строки дублировать её не нужно (в отличие от файлового лога); см. fs-adsync."""
        configure_logging(make_settings(tmp_path, loki_url="http://loki.local"))
        logger = logging.getLogger("video_uploader")
        loki_handler = next(h for h in logger.handlers if isinstance(h, LokiHandler))
        file_handler = next(
            h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
        )
        record = logger.makeRecord("video_uploader", logging.INFO, __file__, 1, "msg", (), None)
        assert file_handler.format(record) != loki_handler.format(record)
        assert "msg" in loki_handler.format(record)
