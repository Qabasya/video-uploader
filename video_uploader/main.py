"""Composition root сервиса.

Сборка зависимостей из ``Settings``, фоновый воркер сканирования, uvicorn для
HTTP-API и graceful shutdown по SIGTERM/SIGINT.
"""

import logging
import signal
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Protocol

import uvicorn

from video_uploader.api.app import create_app
from video_uploader.config import Settings, load_groups
from video_uploader.domain.events import EventBus
from video_uploader.lms.client import LmsClient
from video_uploader.logging_setup.factory import configure_logging
from video_uploader.metadata.base import DateExtractor
from video_uploader.metadata.filename import FilenameDateExtractor
from video_uploader.metadata.filestat import FileStatDateExtractor
from video_uploader.pipeline import Pipeline
from video_uploader.resolving.resolver import GroupResolver
from video_uploader.scanner.scanner import VideoScanner
from video_uploader.scanner.stability import StabilityChecker
from video_uploader.state.repository import StateRepository
from video_uploader.storage.key_builder import KeyBuilder
from video_uploader.storage.s3_gateway import S3Gateway

logger = logging.getLogger(__name__)

_SHUTDOWN_JOIN_TIMEOUT_SECONDS = 10.0


class RegistryCounts(Protocol):
    """Узкий интерфейс реестра, нужный только для сводки в heartbeat-логе."""

    def count_by_status(self) -> dict[str, int]: ...


class ScanWorker:
    """Периодический запуск ``Pipeline.run_cycle()`` в фоновом потоке + внеочередной триггер.

    Заодно раз в ``heartbeat_interval_seconds`` пишет в лог «сервис жив» со сводкой
    реестра — единственный сигнал того, что фоновый цикл сканирования не умер молча
    (см. `.docs/Tasks.md`, доп. правка про краш ``LokiHandler`` — HTTP API мог отвечать
    ``ok`` даже когда этот поток уже не работал).
    """

    def __init__(
        self,
        pipeline: Pipeline,
        scan_interval_seconds: int,
        *,
        repo: RegistryCounts,
        heartbeat_interval_seconds: int,
    ) -> None:
        self._pipeline = pipeline
        self._scan_interval_seconds = scan_interval_seconds
        self._repo = repo
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self.last_scan_at: datetime | None = None
        # Не None и не «сейчас минус интервал»: первый heartbeat ждёт полный интервал,
        # как и первый тик scan/reconcile-циклов в fs-adsync (`_loop`) — единообразно.
        self._last_heartbeat_at = datetime.now(UTC)

    def run(self) -> None:
        """Тело потока: цикл до ``stop()``, прерываемый досрочно через ``request_rescan()``."""
        while not self._stop_event.is_set():
            try:
                self._pipeline.run_cycle()
            except Exception:
                logger.exception(
                    "необработанная ошибка цикла сканирования",
                    extra={"event": "scan_cycle_error"},
                )
            self.last_scan_at = datetime.now(UTC)
            self._maybe_heartbeat()
            self._wake_event.wait(timeout=self._scan_interval_seconds)
            self._wake_event.clear()

    def _maybe_heartbeat(self) -> None:
        now = datetime.now(UTC)
        elapsed = (now - self._last_heartbeat_at).total_seconds()
        if elapsed < self._heartbeat_interval_seconds:
            return
        self._last_heartbeat_at = now
        logger.info(
            "сервис жив: реестр=%s", self._repo.count_by_status(), extra={"event": "heartbeat"}
        )

    def request_rescan(self) -> None:
        """Будит поток немедленно, не дожидаясь ``SCAN_INTERVAL_SECONDS``."""
        self._wake_event.set()

    def stop(self) -> None:
        """Просит поток завершиться на следующей проверке; тоже будит его."""
        self._stop_event.set()
        self._wake_event.set()


class DryRunS3Gateway:
    """``DRY_RUN=true``: не трогает сеть, логирует и притворяется успехом."""

    def upload_video(self, path: Path, key: str, metadata: Mapping[str, str]) -> None:
        logger.info("dry-run: upload_video пропущен: %s -> %s", path, key)

    def put_manifest(self, key: str, manifest: dict[str, object]) -> None:
        logger.info("dry-run: put_manifest пропущен: %s", key)

    def verify(self, key: str, expected_size: int) -> bool:
        logger.info("dry-run: verify пропущен (успех): %s", key)
        return True

    def close(self) -> None:
        pass


class DryRunLmsClient:
    """``DRY_RUN=true``: не трогает сеть, логирует и притворяется успехом."""

    def register(self, payload: dict[str, object]) -> bool:
        logger.info("dry-run: register пропущен (успех): s3_key=%s", payload.get("s3_key"))
        return True

    def close(self) -> None:
        pass


def _build_s3_gateway(settings: Settings) -> DryRunS3Gateway | S3Gateway:
    """``DRY_RUN=true`` → заглушка; иначе ``S3Gateway`` (``DRY_RUN_LMS_LIVE`` тут не влияет)."""
    if settings.dry_run:
        return DryRunS3Gateway()
    return S3Gateway(
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        bucket=settings.s3_bucket,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key.get_secret_value(),
    )


def _build_lms_client(settings: Settings) -> DryRunLmsClient | LmsClient:
    """Заглушка только при ``DRY_RUN=true`` и ``DRY_RUN_LMS_LIVE=false``; иначе настоящий клиент."""
    if settings.dry_run and not settings.dry_run_lms_live:
        return DryRunLmsClient()
    return LmsClient(settings.lms_base_url, settings.lms_hmac_secret.get_secret_value())


def main() -> None:
    """Точка входа CLI ``video-uploader``."""
    settings = Settings()
    configure_logging(settings)  # до StateRepository — создаёт settings.data_dir попутно
    logger.info(
        "fs-video-uploader запускается (dry_run=%s, dry_run_lms_live=%s)",
        settings.dry_run,
        settings.dry_run_lms_live,
        extra={"event": "service_started"},
    )
    groups_config = load_groups(settings.groups_file)

    repo = StateRepository(settings.data_dir / "state.db")
    events = EventBus()

    scanner = VideoScanner(
        video_root=settings.video_root, allowed_extensions=settings.allowed_extensions
    )
    stability = StabilityChecker(stability_minutes=settings.stability_minutes)
    date_extractors: list[DateExtractor] = [
        FilenameDateExtractor(tz_name=settings.tz_name, pattern=settings.date_regex),
        FileStatDateExtractor(tz_name=settings.tz_name),
    ]
    resolver = GroupResolver(groups_config)
    key_builder = KeyBuilder(prefix=settings.s3_key_prefix)

    s3 = _build_s3_gateway(settings)
    lms = _build_lms_client(settings)

    pipeline = Pipeline(
        scanner=scanner,
        stability=stability,
        repo=repo,
        date_extractors=date_extractors,
        resolver=resolver,
        key_builder=key_builder,
        s3=s3,
        lms=lms,
        events=events,
        bucket=settings.s3_bucket,
        archive_subdir=settings.archive_subdir,
        archive_after_register=settings.archive_after_register,
        max_attempts=settings.max_attempts,
        skip_older_than_days=settings.skip_older_than_days,
        dry_run=settings.dry_run,
    )

    worker = ScanWorker(
        pipeline,
        settings.scan_interval_seconds,
        repo=repo,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
    )
    worker_thread = threading.Thread(target=worker.run, name="scan-worker", daemon=True)

    app = create_app(repo=repo, worker=worker)
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=settings.api_port))
    # uvicorn пропускает установку своих обработчиков сигналов, если запущен не из
    # главного потока (`Server.capture_signals`) — сигналами управляет только main(),
    # без конфликта. Тот же приём, что в fs-adsync: раньше uvicorn.run() из главного
    # потока сам ставил обработчики SIGTERM/SIGINT параллельно нашему graceful
    # shutdown — расследование конкретного сбоя из-за этого см. `.docs/Tasks.md`.
    api_thread = threading.Thread(target=server.run, name="api", daemon=True)

    stop = threading.Event()

    def handle_signal(signum: int, _frame: FrameType | None) -> None:
        logger.info(
            "получен сигнал %s, начинаю остановку",
            signum,
            extra={"event": "shutdown_signal_received"},
        )
        stop.set()
        worker.stop()
        server.should_exit = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    worker_thread.start()
    api_thread.start()

    stop.wait()
    worker_thread.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_SECONDS)
    api_thread.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_SECONDS)

    s3.close()
    lms.close()
    logger.info("fs-video-uploader остановлен", extra={"event": "service_stopped"})
