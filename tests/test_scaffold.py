"""Дымовые тесты каркаса: модули импортируются, версия и точка входа на месте."""

import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError

import video_uploader
from video_uploader.main import main

MODULES = [
    "video_uploader",
    "video_uploader.api",
    "video_uploader.api.app",
    "video_uploader.config",
    "video_uploader.domain",
    "video_uploader.domain.events",
    "video_uploader.domain.models",
    "video_uploader.lms",
    "video_uploader.lms.client",
    "video_uploader.logging_setup",
    "video_uploader.logging_setup.factory",
    "video_uploader.logging_setup.loki",
    "video_uploader.logging_setup.telegram",
    "video_uploader.main",
    "video_uploader.metadata",
    "video_uploader.metadata.base",
    "video_uploader.metadata.filename",
    "video_uploader.metadata.filestat",
    "video_uploader.notifications",
    "video_uploader.notifications.telegram",
    "video_uploader.pipeline",
    "video_uploader.resolving",
    "video_uploader.resolving.resolver",
    "video_uploader.scanner",
    "video_uploader.scanner.scanner",
    "video_uploader.scanner.stability",
    "video_uploader.state",
    "video_uploader.state.repository",
    "video_uploader.storage",
    "video_uploader.storage.key_builder",
    "video_uploader.storage.s3_gateway",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    """Каждый модуль каркаса импортируется без ошибок."""
    importlib.import_module(module_name)


def test_version() -> None:
    """Версия пакета задана и совпадает с pyproject."""
    assert video_uploader.__version__ == "0.1.0"


def test_main_fails_fast_without_required_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``Settings()`` — первая строка ``main()``: без обязательных переменных падает сразу,
    не успевая тронуть сеть/потоки/uvicorn."""
    monkeypatch.chdir(tmp_path)  # не подхватить случайный .env из рабочей директории
    for name in ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY", "LMS_BASE_URL", "LMS_HMAC_SECRET"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError):
        main()
