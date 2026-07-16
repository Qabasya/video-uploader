"""Тесты FileStatDateExtractor: дата из mtime, отсутствующий файл, инвариантность момента."""

import os
from pathlib import Path

from video_uploader.metadata.filestat import FileStatDateExtractor


class TestExtractFromMtime:
    def test_matches_file_mtime(self, tmp_path: Path) -> None:
        path = tmp_path / "rec.webm"
        path.write_bytes(b"data")
        os.utime(path, (1_720_000_000, 1_720_000_000))

        extractor = FileStatDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(path)

        assert result is not None
        assert result.timestamp() == 1_720_000_000
        assert result.utcoffset() is not None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        extractor = FileStatDateExtractor(tz_name="Europe/Kaliningrad")
        assert extractor.extract(tmp_path / "does-not-exist.webm") is None


class TestMomentIsTimezoneIndependent:
    def test_same_instant_different_wall_clock(self, tmp_path: Path) -> None:
        path = tmp_path / "rec.webm"
        path.write_bytes(b"data")
        os.utime(path, (1_720_000_000, 1_720_000_000))

        kaliningrad = FileStatDateExtractor(tz_name="Europe/Kaliningrad").extract(path)
        tokyo = FileStatDateExtractor(tz_name="Asia/Tokyo").extract(path)

        assert kaliningrad is not None
        assert tokyo is not None
        assert kaliningrad.timestamp() == tokyo.timestamp()
        assert kaliningrad.hour != tokyo.hour
