"""Тесты доменных моделей: неизменяемость (frozen), отсутствие __dict__ (slots)."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from video_uploader.domain.models import LessonMeta, UploadResult, VideoFile


def make_video_file() -> VideoFile:
    return VideoFile(
        path=Path("/mnt/video/КЕГЭ-1/rec.webm"),
        group_folder="КЕГЭ-1",
        size_bytes=123,
        mtime=1_720_000_000.0,
    )


def make_lesson_meta() -> LessonMeta:
    return LessonMeta(
        group_slug="kege-1",
        lms={"group_id": 3, "course_id": 42},
        recorded_at=datetime(2026, 7, 8, 16, 4, 45, tzinfo=UTC),
        date_from_fallback=False,
    )


def make_upload_result() -> UploadResult:
    return UploadResult(
        s3_key="videos/kege-1/2026/07/2026-07-08_16-04_a1b2c3d4.webm",
        manifest_key="videos/kege-1/2026/07/2026-07-08_16-04_a1b2c3d4.webm.json",
        size_bytes=123456789,
        sha256="a" * 64,
        uploaded_at=datetime(2026, 7, 14, 21, 0, 5, tzinfo=UTC),
    )


class TestVideoFile:
    def test_fields_accessible(self) -> None:
        vf = make_video_file()
        assert vf.group_folder == "КЕГЭ-1"
        assert vf.size_bytes == 123

    def test_frozen(self) -> None:
        vf = make_video_file()
        with pytest.raises(FrozenInstanceError):
            vf.size_bytes = 456  # type: ignore[misc]

    def test_no_dict_slots_enforced(self) -> None:
        vf = make_video_file()
        with pytest.raises(AttributeError):
            vf.__dict__  # noqa: B018

    def test_equality_by_value(self) -> None:
        assert make_video_file() == make_video_file()


class TestLessonMeta:
    def test_fields_accessible(self) -> None:
        meta = make_lesson_meta()
        assert meta.group_slug == "kege-1"
        assert meta.lms == {"group_id": 3, "course_id": 42}

    def test_frozen(self) -> None:
        meta = make_lesson_meta()
        with pytest.raises(FrozenInstanceError):
            meta.group_slug = "other"  # type: ignore[misc]

    def test_no_dict_slots_enforced(self) -> None:
        meta = make_lesson_meta()
        with pytest.raises(AttributeError):
            meta.__dict__  # noqa: B018

    def test_equality_by_value(self) -> None:
        assert make_lesson_meta() == make_lesson_meta()


class TestUploadResult:
    def test_fields_accessible(self) -> None:
        result = make_upload_result()
        assert result.sha256 == "a" * 64
        assert result.size_bytes == 123456789

    def test_frozen(self) -> None:
        result = make_upload_result()
        with pytest.raises(FrozenInstanceError):
            result.sha256 = "b" * 64  # type: ignore[misc]

    def test_no_dict_slots_enforced(self) -> None:
        result = make_upload_result()
        with pytest.raises(AttributeError):
            result.__dict__  # noqa: B018

    def test_equality_by_value(self) -> None:
        assert make_upload_result() == make_upload_result()
