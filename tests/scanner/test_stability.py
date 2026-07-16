"""Тесты StabilityChecker: порог по mtime, читаемость, отсутствующий файл."""

import os
from pathlib import Path

import pytest

from video_uploader.scanner.stability import StabilityChecker


def make_old_file(tmp_path: Path, age_minutes: float) -> Path:
    path = tmp_path / "rec.webm"
    path.write_bytes(b"data")
    old_ts = path.stat().st_mtime - age_minutes * 60
    os.utime(path, (old_ts, old_ts))
    return path


class TestAgeThreshold:
    def test_fresh_file_is_not_stable(self, tmp_path: Path) -> None:
        path = tmp_path / "rec.webm"
        path.write_bytes(b"data")

        checker = StabilityChecker(stability_minutes=5)

        assert checker.is_stable(path) is False

    def test_old_file_is_stable(self, tmp_path: Path) -> None:
        path = make_old_file(tmp_path, age_minutes=10)

        checker = StabilityChecker(stability_minutes=5)

        assert checker.is_stable(path) is True

    def test_boundary_is_inclusive(self, tmp_path: Path) -> None:
        path = make_old_file(tmp_path, age_minutes=5)

        checker = StabilityChecker(stability_minutes=5)

        assert checker.is_stable(path) is True


class TestMissingFile:
    def test_missing_file_is_not_stable(self, tmp_path: Path) -> None:
        checker = StabilityChecker(stability_minutes=5)
        assert checker.is_stable(tmp_path / "does-not-exist.webm") is False


class TestReadability:
    def test_unopenable_file_is_not_stable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = make_old_file(tmp_path, age_minutes=10)

        def raise_on_open(self: Path, *args: object, **kwargs: object) -> None:
            raise OSError("locked (test)")

        monkeypatch.setattr(Path, "open", raise_on_open)

        checker = StabilityChecker(stability_minutes=5)

        assert checker.is_stable(path) is False
