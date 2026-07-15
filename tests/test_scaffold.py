"""Дымовые тесты каркаса: модули импортируются, версия и точка входа на месте."""

import importlib

import pytest

import video_ingest
from video_ingest.main import main

MODULES = [
    "video_ingest",
    "video_ingest.api",
    "video_ingest.api.app",
    "video_ingest.config",
    "video_ingest.domain",
    "video_ingest.domain.events",
    "video_ingest.domain.models",
    "video_ingest.lms",
    "video_ingest.lms.client",
    "video_ingest.logging_setup",
    "video_ingest.logging_setup.factory",
    "video_ingest.logging_setup.loki",
    "video_ingest.logging_setup.telegram",
    "video_ingest.main",
    "video_ingest.metadata",
    "video_ingest.metadata.base",
    "video_ingest.metadata.filename",
    "video_ingest.metadata.filestat",
    "video_ingest.notifications",
    "video_ingest.notifications.telegram",
    "video_ingest.pipeline",
    "video_ingest.resolving",
    "video_ingest.resolving.resolver",
    "video_ingest.scanner",
    "video_ingest.scanner.scanner",
    "video_ingest.scanner.stability",
    "video_ingest.state",
    "video_ingest.state.repository",
    "video_ingest.storage",
    "video_ingest.storage.key_builder",
    "video_ingest.storage.s3_gateway",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    """Каждый модуль каркаса импортируется без ошибок."""
    importlib.import_module(module_name)


def test_version() -> None:
    """Версия пакета задана и совпадает с pyproject."""
    assert video_ingest.__version__ == "0.1.0"


def test_entry_point_stub() -> None:
    """Точка входа существует и честно сообщает, что сервис ещё не реализован."""
    with pytest.raises(NotImplementedError):
        main()
