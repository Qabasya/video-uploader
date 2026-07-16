"""Тесты VideoScanner: глубина 1, фильтры имени/расширения, сортировка, изоляция ошибок."""

import logging
import os
from pathlib import Path

import pytest

from video_uploader.scanner.scanner import VideoScanner


def make_scanner(video_root: Path, extensions: tuple[str, ...] = (".webm",)) -> VideoScanner:
    return VideoScanner(video_root=video_root, allowed_extensions=extensions)


def touch(path: Path, content: bytes = b"data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class TestBasicDiscovery:
    def test_finds_files_in_group_folders(self, tmp_path: Path) -> None:
        touch(tmp_path / "КЕГЭ-1" / "rec.webm")
        touch(tmp_path / "ОГЭ-1" / "rec2.webm")

        result = make_scanner(tmp_path).scan()

        found = {(vf.group_folder, vf.path.name) for vf in result}
        assert found == {("КЕГЭ-1", "rec.webm"), ("ОГЭ-1", "rec2.webm")}

    def test_size_and_mtime_populated(self, tmp_path: Path) -> None:
        path = tmp_path / "КЕГЭ-1" / "rec.webm"
        touch(path, content=b"x" * 100)

        result = make_scanner(tmp_path).scan()

        assert len(result) == 1
        assert result[0].size_bytes == 100
        assert result[0].mtime == pytest.approx(path.stat().st_mtime)


class TestFiltering:
    def test_disallowed_extension_excluded(self, tmp_path: Path) -> None:
        touch(tmp_path / "КЕГЭ-1" / "audio.mp3")
        assert make_scanner(tmp_path).scan() == []

    def test_extension_case_insensitive(self, tmp_path: Path) -> None:
        touch(tmp_path / "КЕГЭ-1" / "REC.WEBM")
        result = make_scanner(tmp_path).scan()
        assert len(result) == 1

    @pytest.mark.parametrize("name", [".DS_Store.webm", "~temp.webm"])
    def test_hidden_and_temp_names_excluded(self, tmp_path: Path, name: str) -> None:
        touch(tmp_path / "КЕГЭ-1" / name)
        assert make_scanner(tmp_path).scan() == []

    def test_file_directly_in_video_root_excluded(self, tmp_path: Path) -> None:
        touch(tmp_path / "stray.webm")
        assert make_scanner(tmp_path).scan() == []

    def test_nested_archive_folder_excluded(self, tmp_path: Path) -> None:
        touch(tmp_path / "КЕГЭ-1" / "_uploaded" / "old.webm")
        assert make_scanner(tmp_path).scan() == []

    def test_empty_group_folder_yields_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "КЕГЭ-1").mkdir()
        assert make_scanner(tmp_path).scan() == []


class TestOrdering:
    def test_sorted_by_mtime_ascending(self, tmp_path: Path) -> None:
        paths = [tmp_path / "КЕГЭ-1" / f"{i}.webm" for i in range(3)]
        for path in paths:
            touch(path)

        base = 1_720_000_000
        # Пишем mtime в обратном порядке создания, чтобы проверить именно сортировку.
        os.utime(paths[0], (base + 300, base + 300))
        os.utime(paths[1], (base + 100, base + 100))
        os.utime(paths[2], (base + 200, base + 200))

        result = make_scanner(tmp_path).scan()

        assert [vf.path.name for vf in result] == ["1.webm", "2.webm", "0.webm"]


class TestErrorIsolation:
    def test_unreadable_group_folder_does_not_block_others(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        broken = tmp_path / "СЛОМАННАЯ"
        broken.mkdir()
        touch(tmp_path / "КЕГЭ-1" / "rec.webm")

        original_iterdir = Path.iterdir

        def fake_iterdir(self: Path):  # type: ignore[no-untyped-def]
            if self == broken:
                raise OSError("permission denied (test)")
            return original_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", fake_iterdir)

        with caplog.at_level(logging.WARNING, logger="video_uploader.scanner.scanner"):
            result = make_scanner(tmp_path).scan()

        assert [vf.path.name for vf in result] == ["rec.webm"]
        assert "СЛОМАННАЯ" in caplog.text
