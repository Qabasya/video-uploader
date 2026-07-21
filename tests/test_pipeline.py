"""Тесты Pipeline: happy path и все ветки отказов (CLAUDE.md, раздел Testing)."""

import logging
import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from video_uploader.config import GroupsConfig
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
from video_uploader.lms.client import LmsRejectedError, LmsRetryableError
from video_uploader.metadata.filename import FilenameDateExtractor
from video_uploader.metadata.filestat import FileStatDateExtractor
from video_uploader.pipeline import Pipeline
from video_uploader.resolving.resolver import GroupResolver
from video_uploader.scanner.scanner import VideoScanner
from video_uploader.scanner.stability import StabilityChecker
from video_uploader.state.repository import StateRepository
from video_uploader.storage.key_builder import KeyBuilder

GROUPS_YAML = {
    "groups": {
        "КЕГЭ-1": {"slug": "kege-1", "lms": {"group_id": 3, "course_id": 42}},
    }
}
TZ_NAME = "Europe/Kaliningrad"


class FakeS3Gateway:
    """Фейк UploadGateway: запоминает вызовы, не трогает сеть."""

    def __init__(self) -> None:
        self.upload_calls: list[tuple[Path, str, dict[str, str]]] = []
        self.manifest_calls: list[tuple[str, dict[str, object]]] = []
        self.verify_calls: list[tuple[str, int]] = []
        self.upload_error: Exception | None = None
        self.verify_result: bool = True

    def upload_video(self, path: Path, key: str, metadata: Mapping[str, str]) -> None:
        self.upload_calls.append((path, key, dict(metadata)))
        if self.upload_error is not None:
            raise self.upload_error

    def put_manifest(self, key: str, manifest: dict[str, object]) -> None:
        self.manifest_calls.append((key, manifest))

    def verify(self, key: str, expected_size: int) -> bool:
        self.verify_calls.append((key, expected_size))
        return self.verify_result


class FakeLmsClient:
    """Фейк RegistrationClient: запоминает payload, умеет бросать заданную ошибку."""

    def __init__(self) -> None:
        self.register_calls: list[dict[str, object]] = []
        self.register_error: Exception | None = None

    def register(self, payload: dict[str, object]) -> None:
        if self.register_error is not None:
            raise self.register_error
        self.register_calls.append(payload)


def write_stable_file(path: Path, *, age_minutes: float = 10, content: bytes = b"data") -> None:
    """Файл, который StabilityChecker(stability_minutes=5) сочтёт стабильным."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    old_ts = path.stat().st_mtime - age_minutes * 60
    os.utime(path, (old_ts, old_ts))


def make_pipeline(
    video_root: Path,
    repo: StateRepository,
    *,
    s3: FakeS3Gateway,
    lms: FakeLmsClient,
    events: EventBus,
    groups: dict[str, object] | None = None,
    max_attempts: int = 3,
    skip_older_than_days: int | None = None,
    archive_after_register: bool = True,
    dry_run: bool = False,
) -> Pipeline:
    resolver = GroupResolver(
        GroupsConfig.model_validate(groups if groups is not None else GROUPS_YAML)
    )
    return Pipeline(
        scanner=VideoScanner(video_root=video_root, allowed_extensions=(".webm",)),
        stability=StabilityChecker(stability_minutes=5),
        repo=repo,
        date_extractors=[
            FilenameDateExtractor(tz_name=TZ_NAME),
            FileStatDateExtractor(tz_name=TZ_NAME),
        ],
        resolver=resolver,
        key_builder=KeyBuilder(prefix="videos"),
        s3=s3,
        lms=lms,
        events=events,
        bucket="test-bucket",
        archive_subdir="_uploaded",
        archive_after_register=archive_after_register,
        max_attempts=max_attempts,
        skip_older_than_days=skip_older_than_days,
        dry_run=dry_run,
    )


@pytest.fixture
def video_root(tmp_path: Path) -> Path:
    root = tmp_path / "video"
    root.mkdir()
    return root


@pytest.fixture
def repo(tmp_path: Path) -> StateRepository:
    return StateRepository(tmp_path / "state.db")


def only_record_id(repo: StateRepository) -> int:
    records = repo.get_recent(10)
    assert len(records) == 1
    return records[0].id


class TestHappyPath:
    def test_file_reaches_archived(
        self, video_root: Path, repo: StateRepository, caplog: pytest.LogCaptureFixture
    ) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        events = EventBus()
        published: list[object] = []
        for event_type in (VideoDiscovered, VideoUploaded, VideoRegistered, VideoArchived):
            events.subscribe(event_type, published.append)

        video_path = video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm"
        write_stable_file(video_path)
        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events)

        with caplog.at_level(logging.INFO, logger="video_uploader.pipeline"):
            pipeline.run_cycle()

        # успешные шаги должны попадать в логи (канал Loki) — не только в EventBus
        info_messages = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("обнаружено" in m for m in info_messages)
        assert any("загружено" in m for m in info_messages)
        assert any("верифицировано" in m for m in info_messages)
        assert any("зарегистрировано" in m for m in info_messages)
        assert any("архив" in m for m in info_messages)

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "archived"
        assert not video_path.exists()
        archived_path = video_root / "КЕГЭ-1" / "_uploaded" / "rec_08_07_26_16_04_45.webm"
        assert archived_path.exists()
        assert len(s3.upload_calls) == 1
        assert len(s3.manifest_calls) == 1
        assert len(lms.register_calls) == 1
        assert [type(event) for event in published] == [
            VideoDiscovered,
            VideoUploaded,
            VideoRegistered,
            VideoArchived,
        ]

        _, key, metadata = s3.upload_calls[0]
        assert key == "videos/kege-1/2026/07/2026-07-08_16-04_" + state.sha256[:8] + ".webm"
        assert metadata["group-slug"] == "kege-1"
        assert metadata["lms-group-id"] == "3"

        payload = lms.register_calls[0]
        assert payload["s3_bucket"] == "test-bucket"
        assert payload["group_slug"] == "kege-1"
        assert payload["duration_sec"] is None


class TestStability:
    def test_unstable_file_is_left_alone(
        self, video_root: Path, repo: StateRepository, caplog: pytest.LogCaptureFixture
    ) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        events = EventBus()
        discovered: list[VideoDiscovered] = []
        events.subscribe(VideoDiscovered, discovered.append)
        video_path = video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm"
        video_path.parent.mkdir(parents=True)
        video_path.write_bytes(b"data")  # свежий mtime, не состарен

        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events)
        with caplog.at_level(logging.DEBUG, logger="video_uploader.pipeline"):
            pipeline.run_cycle()
            pipeline.run_cycle()  # второй цикл: файл всё ещё нестабилен

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "discovered"
        assert s3.upload_calls == []
        # обнаружение публикуется/логируется один раз, не на каждом цикле
        assert len(discovered) == 1
        assert any(r.levelname == "DEBUG" and "дописывается" in r.message for r in caplog.records)


class TestGroupUnmapped:
    def test_rate_limited_once_per_cycle(
        self, video_root: Path, repo: StateRepository, caplog: pytest.LogCaptureFixture
    ) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        events = EventBus()
        unmapped: list[GroupUnmapped] = []
        events.subscribe(GroupUnmapped, unmapped.append)

        for name in ("a_08_07_26_16_04_45.webm", "b_08_07_26_16_04_45.webm"):
            write_stable_file(video_root / "НЕИЗВЕСТНАЯ" / name)

        pipeline = make_pipeline(
            video_root, repo, s3=s3, lms=lms, events=events, groups={"groups": {}}
        )
        with caplog.at_level(logging.WARNING, logger="video_uploader.pipeline"):
            pipeline.run_cycle()

        assert len(unmapped) == 1
        records = repo.get_recent(10)
        assert len(records) == 2
        assert all(record.status == "skipped_unmapped" for record in records)
        assert caplog.text.count("НЕИЗВЕСТНАЯ") == 1  # WARNING тоже раз за цикл на папку

    def test_reopens_after_config_fixed(self, video_root: Path, repo: StateRepository) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        events = EventBus()
        video_path = video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm"
        write_stable_file(video_path)

        before = make_pipeline(
            video_root, repo, s3=s3, lms=lms, events=events, groups={"groups": {}}
        )
        before.run_cycle()
        file_id = only_record_id(repo)
        state = repo.get_by_id(file_id)
        assert state is not None
        assert state.status == "skipped_unmapped"

        after = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events)
        after.run_cycle()

        state = repo.get_by_id(file_id)
        assert state is not None
        assert state.status == "archived"


class TestSkipOlderThanDays:
    def test_old_lesson_is_skipped(
        self, video_root: Path, repo: StateRepository, caplog: pytest.LogCaptureFixture
    ) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        events = EventBus()
        video_path = video_root / "КЕГЭ-1" / "rec_01_01_20_10_00_00.webm"  # 2020-01-01
        write_stable_file(video_path)

        pipeline = make_pipeline(
            video_root, repo, s3=s3, lms=lms, events=events, skip_older_than_days=7
        )
        with caplog.at_level(logging.INFO, logger="video_uploader.pipeline"):
            pipeline.run_cycle()

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "skipped_old"
        assert s3.upload_calls == []
        assert any("пропущено" in r.message for r in caplog.records)


class TestDateFallback:
    def test_event_published_and_date_used(
        self, video_root: Path, repo: StateRepository, caplog: pytest.LogCaptureFixture
    ) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        events = EventBus()
        fallback_events: list[DateFallback] = []
        events.subscribe(DateFallback, fallback_events.append)

        video_path = video_root / "КЕГЭ-1" / "random_name.webm"  # без блока даты
        write_stable_file(video_path)

        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events)
        with caplog.at_level(logging.WARNING, logger="video_uploader.pipeline"):
            pipeline.run_cycle()

        assert len(fallback_events) == 1
        assert fallback_events[0].path == video_path
        assert len(s3.manifest_calls) == 1
        assert "recorded_at" in s3.manifest_calls[0][1]
        assert "random_name.webm" in caplog.text
        assert any(record.levelname == "WARNING" for record in caplog.records)


class TestUploadFailure:
    def test_marks_failed(self, video_root: Path, repo: StateRepository) -> None:
        s3 = FakeS3Gateway()
        s3.upload_error = RuntimeError("boto3 boom")
        lms = FakeLmsClient()
        events = EventBus()
        write_stable_file(video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm")

        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events)
        pipeline.run_cycle()

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "failed"
        assert state.attempts == 1
        assert lms.register_calls == []


class TestVerifyFailure:
    def test_marks_failed(self, video_root: Path, repo: StateRepository) -> None:
        s3 = FakeS3Gateway()
        s3.verify_result = False
        lms = FakeLmsClient()
        events = EventBus()
        write_stable_file(video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm")

        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events)
        pipeline.run_cycle()

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "failed"
        assert state.attempts == 1
        assert lms.register_calls == []


class TestRegisterRetryable:
    def test_retries_without_reupload(self, video_root: Path, repo: StateRepository) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        lms.register_error = LmsRetryableError("503")
        events = EventBus()
        write_stable_file(video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm")

        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events, max_attempts=5)
        pipeline.run_cycle()

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "failed"
        assert state.attempts == 1
        assert len(s3.upload_calls) == 1

        lms.register_error = None
        pipeline.run_cycle()

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "archived"
        assert len(s3.upload_calls) == 1  # не перезалито повторно
        assert len(lms.register_calls) == 1


class TestRegisterRejected:
    def test_exhausts_attempts_immediately_without_retry(
        self, video_root: Path, repo: StateRepository
    ) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        lms.register_error = LmsRejectedError("400 bad payload")
        events = EventBus()
        failed_events: list[VideoFailed] = []
        events.subscribe(VideoFailed, failed_events.append)
        write_stable_file(video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm")

        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events, max_attempts=5)
        pipeline.run_cycle()

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "failed"
        assert state.attempts == 5  # сразу исчерпаны, без ретраев
        assert len(failed_events) == 1

        pipeline.run_cycle()  # следующий цикл не должен снова пытаться
        assert len(s3.upload_calls) == 1
        assert len(failed_events) == 1  # событие не публикуется повторно


class TestContentDeduplication:
    def test_second_file_with_same_content_skips_network(
        self, video_root: Path, repo: StateRepository
    ) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        events = EventBus()
        content = b"identical bytes"
        write_stable_file(video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm", content=content)
        write_stable_file(video_root / "КЕГЭ-1" / "rec_09_07_26_16_04_45.webm", content=content)

        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events)
        pipeline.run_cycle()

        assert len(s3.upload_calls) == 1
        assert len(lms.register_calls) == 1
        records = repo.get_recent(10)
        assert len(records) == 2
        assert all(record.status == "archived" for record in records)
        assert records[0].s3_key == records[1].s3_key


class TestResumeFromUploading:
    def test_does_not_raise_invalid_transition(
        self, video_root: Path, repo: StateRepository
    ) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        events = EventBus()
        video_path = video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm"
        write_stable_file(video_path)

        file_id, _ = repo.discover(
            video_path, "КЕГЭ-1", video_path.stat().st_size, video_path.stat().st_mtime
        )
        repo.mark_uploading(file_id)  # симуляция крэша между mark_uploading и mark_uploaded

        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events)
        pipeline.run_cycle()

        state = repo.get_by_id(file_id)
        assert state is not None
        assert state.status == "archived"


class TestArchiveAfterRegisterDisabled:
    def test_file_stays_in_place(self, video_root: Path, repo: StateRepository) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        events = EventBus()
        archived_events: list[VideoArchived] = []
        events.subscribe(VideoArchived, archived_events.append)
        video_path = video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm"
        write_stable_file(video_path)

        pipeline = make_pipeline(
            video_root, repo, s3=s3, lms=lms, events=events, archive_after_register=False
        )
        pipeline.run_cycle()

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "registered"
        assert video_path.exists()
        assert archived_events == []


class TestDryRun:
    def test_archive_step_is_skipped(self, video_root: Path, repo: StateRepository) -> None:
        s3 = FakeS3Gateway()
        lms = FakeLmsClient()
        events = EventBus()
        archived_events: list[VideoArchived] = []
        events.subscribe(VideoArchived, archived_events.append)
        video_path = video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm"
        write_stable_file(video_path)

        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events, dry_run=True)
        pipeline.run_cycle()

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "registered"
        assert video_path.exists()
        assert archived_events == []


class TestMaxAttemptsExhausted:
    def test_video_failed_published_once_and_stops_retrying(
        self, video_root: Path, repo: StateRepository
    ) -> None:
        s3 = FakeS3Gateway()
        s3.upload_error = RuntimeError("persistent failure")
        lms = FakeLmsClient()
        events = EventBus()
        failed_events: list[VideoFailed] = []
        events.subscribe(VideoFailed, failed_events.append)
        write_stable_file(video_root / "КЕГЭ-1" / "rec_08_07_26_16_04_45.webm")

        pipeline = make_pipeline(video_root, repo, s3=s3, lms=lms, events=events, max_attempts=3)

        for _ in range(3):
            pipeline.run_cycle()

        state = repo.get_by_id(only_record_id(repo))
        assert state is not None
        assert state.status == "failed"
        assert state.attempts == 3
        assert len(failed_events) == 1
        assert len(s3.upload_calls) == 3

        pipeline.run_cycle()  # четвёртый цикл — попыток больше нет

        assert len(s3.upload_calls) == 3  # не выросло
        assert len(failed_events) == 1  # событие не повторилось
