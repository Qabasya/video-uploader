"""Оркестратор обработки файлов: scan → stability → dedup → metadata → resolve →
upload → verify → register → cleanup.

Зависит только от Protocol-интерфейсов там, где нужна подмена (S3, LMS — из-за
``DRY_RUN``, см. CLAUDE.md); на значимых шагах публикует доменные события в
``EventBus``.
"""

import hashlib
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from video_uploader import __version__
from video_uploader.domain.events import (
    DateFallback,
    EventBus,
    GroupUnmapped,
    VideoArchived,
    VideoDiscovered,
    VideoFailed,
    VideoRegistered,
    VideoUploaded,
)
from video_uploader.domain.models import LessonMeta, VideoFile
from video_uploader.lms.client import LmsRejectedError
from video_uploader.metadata.base import DateExtractor
from video_uploader.resolving.resolver import GroupResolver
from video_uploader.scanner.scanner import VideoScanner
from video_uploader.scanner.stability import StabilityChecker
from video_uploader.state.repository import FileState, StateRepository
from video_uploader.storage.key_builder import KeyBuilder

logger = logging.getLogger(__name__)

_HASH_CHUNK_SIZE = 1024 * 1024
_DUPLICATE_TERMINAL_STATUSES = ("registered", "archived")
_DEDUP_ELIGIBLE_STATUSES = ("discovered", "failed", "skipped_unmapped")


class UploadGateway(Protocol):
    """Узкий интерфейс побочных эффектов S3, которые использует pipeline."""

    def upload_video(self, path: Path, key: str, metadata: Mapping[str, str]) -> None: ...

    def put_manifest(self, key: str, manifest: dict[str, object]) -> None: ...

    def verify(self, key: str, expected_size: int) -> bool: ...


class RegistrationClient(Protocol):
    """Узкий интерфейс регистрации в LMS, который использует pipeline."""

    def register(self, payload: dict[str, object]) -> bool: ...


def _compute_sha256(path: Path) -> str:
    """Потоковый sha256, чанк 1 MiB (CLAUDE.md, Processing Rules)."""
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_HASH_CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


def _build_object_metadata(lesson: LessonMeta, sha256: str) -> dict[str, str]:
    """``x-amz-meta-*`` без префикса (его добавляет boto3): group-slug/recorded-at/sha256/lms-*."""
    metadata = {
        "group-slug": lesson.group_slug,
        "recorded-at": lesson.recorded_at.isoformat(),
        "sha256": sha256,
    }
    for key, value in lesson.lms.items():
        metadata[f"lms-{key.replace('_', '-')}"] = str(value)
    return metadata


def _build_manifest(
    video_file: VideoFile, lesson: LessonMeta, sha256: str, uploaded_at: datetime
) -> dict[str, object]:
    """Манифест schema 2 — состав полей по примеру CLAUDE.md."""
    return {
        "schema": 2,
        "group_slug": lesson.group_slug,
        "source_folder": video_file.group_folder,
        "lms": lesson.lms,
        "recorded_at": lesson.recorded_at.isoformat(),
        "original_name": video_file.path.name,
        "size_bytes": video_file.size_bytes,
        "sha256": sha256,
        "uploaded_at": uploaded_at.isoformat(),
        "service": {"name": "fs-video-uploader", "version": __version__},
    }


def _build_lms_payload(
    bucket: str,
    s3_key: str,
    manifest_key: str,
    lesson: LessonMeta,
    video_file: VideoFile,
    sha256: str,
) -> dict[str, object]:
    """REST-payload по контракту CLAUDE.md; ``duration_sec`` не извлекается — всегда None."""
    return {
        "s3_bucket": bucket,
        "s3_key": s3_key,
        "manifest_key": manifest_key,
        "group_slug": lesson.group_slug,
        "lms": lesson.lms,
        "recorded_at": lesson.recorded_at.isoformat(),
        "size_bytes": video_file.size_bytes,
        "sha256": sha256,
        "duration_sec": None,
    }


class Pipeline:
    """Оркестратор одного цикла сканирования: от `scan()` до архивации файла."""

    def __init__(
        self,
        *,
        scanner: VideoScanner,
        stability: StabilityChecker,
        repo: StateRepository,
        date_extractors: Sequence[DateExtractor],
        resolver: GroupResolver,
        key_builder: KeyBuilder,
        s3: UploadGateway,
        lms: RegistrationClient,
        events: EventBus,
        bucket: str,
        archive_subdir: str,
        archive_after_register: bool,
        max_attempts: int,
        skip_older_than_days: int | None,
        dry_run: bool,
    ) -> None:
        self._scanner = scanner
        self._stability = stability
        self._repo = repo
        self._date_extractors = date_extractors
        self._resolver = resolver
        self._key_builder = key_builder
        self._s3 = s3
        self._lms = lms
        self._events = events
        self._bucket = bucket
        self._archive_subdir = archive_subdir
        self._archive_after_register = archive_after_register
        self._max_attempts = max_attempts
        self._skip_older_than_days = skip_older_than_days
        self._dry_run = dry_run
        # Один раз на file_id — иначе файл, окончательно исчерпавший MAX_ATTEMPTS,
        # молча пропускался бы каждый цикл сканирования без единого следа в логе.
        self._warned_exhausted_ids: set[int] = set()

    def run_cycle(self) -> None:
        """Один проход по шаре: сканирует, обрабатывает каждый файл изолированно."""
        warned_folders: set[str] = set()
        for video_file in self._scanner.scan():
            try:
                file_id, is_new = self._repo.discover(
                    video_file.path,
                    video_file.group_folder,
                    video_file.size_bytes,
                    video_file.mtime,
                )
            except Exception:
                logger.exception(
                    "не удалось завести запись реестра для %s",
                    video_file.path,
                    extra={"event": "registry_error"},
                )
                continue

            if is_new:
                logger.info(
                    "видео обнаружено: %s", video_file.path, extra={"event": "video_discovered"}
                )
                self._events.publish(VideoDiscovered(path=video_file.path))

            try:
                self._process(file_id, video_file, warned_folders)
            except LmsRejectedError as exc:
                self._fail(file_id, video_file, exc, permanent=True)
            except Exception as exc:
                self._fail(file_id, video_file, exc, permanent=False)

    def _process(self, file_id: int, video_file: VideoFile, warned_folders: set[str]) -> None:
        state = self._repo.get_by_id(file_id)
        assert state is not None

        if state.status in ("archived", "skipped_old"):
            return
        if state.status == "failed" and state.attempts >= self._max_attempts:
            if file_id not in self._warned_exhausted_ids:
                self._warned_exhausted_ids.add(file_id)
                logger.warning(
                    "видео больше не будет обработано — исчерпаны попытки (%d), "
                    "нужно вмешательство администратора: %s",
                    state.attempts,
                    video_file.path,
                    extra={"event": "video_attempts_exhausted"},
                )
            return
        if state.status == "registered":
            assert state.sha256 is not None
            self._cleanup(file_id, video_file, state.sha256)
            return

        if not self._stability.is_stable(video_file.path):
            logger.debug("файл ещё дописывается, ждём стабильности: %s", video_file.path)
            return

        sha256 = self._resolve_sha256(file_id, video_file)

        if state.status in _DEDUP_ELIGIBLE_STATUSES:
            duplicate = self._repo.get_by_sha256(sha256)
            if (
                duplicate is not None
                and duplicate.id != file_id
                and duplicate.status in _DUPLICATE_TERMINAL_STATUSES
            ):
                self._replay_duplicate(file_id, video_file, duplicate)
                return

        recorded_at, from_fallback = self._extract_date(video_file.path)
        if from_fallback:
            logger.warning(
                "дата занятия не найдена в имени файла, взят mtime: %s",
                video_file.path,
                extra={"event": "date_fallback"},
            )
            self._events.publish(DateFallback(path=video_file.path))

        if self._skip_older_than_days is not None:
            age_days = (datetime.now(recorded_at.tzinfo) - recorded_at).days
            if age_days > self._skip_older_than_days:
                logger.info(
                    "видео пропущено (старше %s дней): %s",
                    self._skip_older_than_days,
                    video_file.path,
                    extra={"event": "video_skipped_old"},
                )
                self._repo.mark_skipped(file_id, "skipped_old")
                return

        group_entry = self._resolver.resolve(video_file.group_folder)
        if group_entry is None:
            if video_file.group_folder not in warned_folders:
                warned_folders.add(video_file.group_folder)
                logger.warning(
                    "папка отсутствует в groups.yaml: %s",
                    video_file.group_folder,
                    extra={"event": "group_unmapped"},
                )
                self._events.publish(GroupUnmapped(group_folder=video_file.group_folder))
            if state.status != "skipped_unmapped":
                self._repo.mark_skipped(file_id, "skipped_unmapped")
            return

        lesson = LessonMeta(
            group_slug=group_entry.slug,
            lms=group_entry.lms,
            recorded_at=recorded_at,
            date_from_fallback=from_fallback,
        )

        s3_key = self._key_builder.build_video_key(
            lesson.group_slug, lesson.recorded_at, sha256, video_file.path.suffix
        )

        if state.s3_key is None:
            # Не state.status == "uploaded": если упасть позже (на register/cleanup),
            # mark_failed перезатрёт статус на "failed", а s3_key останется —
            # это и есть надёжный сигнал «загрузка уже случилась», в отличие от status.
            if state.status != "uploading":
                self._repo.mark_uploading(file_id)
            metadata = _build_object_metadata(lesson, sha256)
            self._s3.upload_video(video_file.path, s3_key, metadata)
            manifest = _build_manifest(video_file, lesson, sha256, datetime.now(UTC))
            self._s3.put_manifest(self._key_builder.build_manifest_key(s3_key), manifest)
            self._repo.mark_uploaded(file_id, s3_key)
            logger.info(
                "видео загружено: %s -> %s",
                video_file.path,
                s3_key,
                extra={"event": "video_uploaded"},
            )
            self._events.publish(VideoUploaded(path=video_file.path, s3_key=s3_key))
        else:
            s3_key = state.s3_key
            if state.status == "failed":
                # Раз s3_key уже есть, а мы не в "uploaded"/"registered"/"archived" (те
                # отсечены ранними выходами) — упало на более позднем шаге (verify/
                # register/cleanup). Восстанавливаем "uploaded" без сетевых вызовов,
                # чтобы mark_registered ниже увидел допустимый переход.
                self._repo.mark_uploading(file_id)
                self._repo.mark_uploaded(file_id, s3_key)

        if not self._s3.verify(s3_key, video_file.size_bytes):
            raise RuntimeError(f"верификация S3 не прошла: {s3_key}")
        logger.info("видео верифицировано в S3: %s", s3_key, extra={"event": "video_verified"})

        if state.status != "registered":
            manifest_key = self._key_builder.build_manifest_key(s3_key)
            payload = _build_lms_payload(
                self._bucket, s3_key, manifest_key, lesson, video_file, sha256
            )
            matched = self._lms.register(payload)
            self._repo.mark_registered(file_id)
            if matched:
                logger.info(
                    "видео полностью обработано: %s -> %s (занятие найдено)",
                    video_file.path,
                    s3_key,
                    extra={"event": "video_registered"},
                )
            else:
                logger.warning(
                    "видео зарегистрировано, но занятие не найдено по дате/времени — "
                    "нужна ручная привязка: %s -> %s",
                    video_file.path,
                    s3_key,
                    extra={"event": "video_registered"},
                )
            self._events.publish(VideoRegistered(path=video_file.path, s3_key=s3_key))

        self._cleanup(file_id, video_file, sha256)

    def _resolve_sha256(self, file_id: int, video_file: VideoFile) -> str:
        cached = self._repo.get_cached_sha256(
            video_file.path, video_file.size_bytes, video_file.mtime
        )
        if cached is not None:
            return cached
        sha256 = _compute_sha256(video_file.path)
        self._repo.set_sha256(file_id, sha256)
        return sha256

    def _extract_date(self, path: Path) -> tuple[datetime, bool]:
        for index, extractor in enumerate(self._date_extractors):
            result = extractor.extract(path)
            if result is not None:
                return result, index > 0
        raise RuntimeError(f"ни одна стратегия не определила дату для {path}")

    def _replay_duplicate(self, file_id: int, video_file: VideoFile, duplicate: FileState) -> None:
        """Контент уже загружен под другим path — переиспользуем s3_key без сети."""
        assert duplicate.s3_key is not None
        state = self._repo.get_by_id(file_id)
        assert state is not None
        if state.status != "uploading":
            self._repo.mark_uploading(file_id)
        self._repo.mark_uploaded(file_id, duplicate.s3_key)
        logger.info(
            "видео загружено (дубликат по контенту): %s -> %s",
            video_file.path,
            duplicate.s3_key,
            extra={"event": "video_uploaded"},
        )
        self._events.publish(VideoUploaded(path=video_file.path, s3_key=duplicate.s3_key))
        self._repo.mark_registered(file_id)
        logger.info(
            "видео полностью обработано (дубликат по контенту, занятие уже привязано ранее): "
            "%s -> %s",
            video_file.path,
            duplicate.s3_key,
            extra={"event": "video_registered"},
        )
        self._events.publish(VideoRegistered(path=video_file.path, s3_key=duplicate.s3_key))
        assert duplicate.sha256 is not None
        self._cleanup(file_id, video_file, duplicate.sha256)

    def _cleanup(self, file_id: int, video_file: VideoFile, sha256: str) -> None:
        if not self._archive_after_register:
            return
        if self._dry_run:
            logger.info("dry-run: архивация %s пропущена", video_file.path)
            return

        archive_dir = video_file.path.parent / self._archive_subdir
        archive_dir.mkdir(exist_ok=True)
        target = archive_dir / video_file.path.name
        if target.exists():
            target = archive_dir / f"{video_file.path.stem}_{sha256[:8]}{video_file.path.suffix}"

        video_file.path.rename(target)
        self._repo.mark_archived(file_id, target)
        logger.info(
            "исходник перемещён в архив: %s -> %s",
            video_file.path,
            target,
            extra={"event": "video_archived"},
        )
        self._events.publish(VideoArchived(path=video_file.path, archived_path=target))

    def _fail(
        self, file_id: int, video_file: VideoFile, exc: Exception, *, permanent: bool
    ) -> None:
        logger.exception(
            "ошибка обработки %s", video_file.path, extra={"event": "video_processing_error"}
        )
        self._repo.mark_failed(file_id, str(exc))
        state = self._repo.get_by_id(file_id)
        assert state is not None
        attempts = state.attempts
        if permanent:
            while attempts < self._max_attempts:
                self._repo.mark_failed(file_id, str(exc))
                attempts += 1
        if attempts == self._max_attempts:
            logger.error(
                "видео окончательно не обработано после %d попыток, повторных попыток не будет: %s",
                attempts,
                video_file.path,
                extra={"event": "video_failed"},
            )
            self._events.publish(
                VideoFailed(path=video_file.path, error=str(exc), attempts=attempts)
            )
