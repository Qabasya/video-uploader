"""Тесты faststart: разбор порядка атомов и перепаковка (без реального ffmpeg)."""

import struct
import subprocess
from pathlib import Path

import pytest

from video_uploader.storage import faststart
from video_uploader.storage.faststart import faststart_copy, needs_faststart


def _box(box_type: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type) + payload


def _mp4(order: tuple[bytes, ...], tmp_path: Path, name: str = "rec.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(_box(b"ftyp", b"isom0000") + b"".join(_box(t, b"x" * 32) for t in order))
    return path


class TestNeedsFaststart:
    def test_moov_after_mdat(self, tmp_path: Path) -> None:
        assert needs_faststart(_mp4((b"mdat", b"moov"), tmp_path)) is True

    def test_moov_before_mdat(self, tmp_path: Path) -> None:
        assert needs_faststart(_mp4((b"moov", b"mdat"), tmp_path)) is False

    def test_other_extension_ignored(self, tmp_path: Path) -> None:
        assert needs_faststart(_mp4((b"mdat", b"moov"), tmp_path, "rec.webm")) is False

    def test_garbage_is_not_remuxed(self, tmp_path: Path) -> None:
        path = tmp_path / "rec.mp4"
        path.write_bytes(b"\x00\x00")
        assert needs_faststart(path) is False


class TestFaststartCopy:
    def test_no_copy_when_not_needed(self, tmp_path: Path) -> None:
        path = _mp4((b"moov", b"mdat"), tmp_path)
        with faststart_copy(path, tmp_path / "work") as copy:
            assert copy is None

    def test_no_ffmpeg_falls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(faststart.shutil, "which", lambda _: None)
        with faststart_copy(_mp4((b"mdat", b"moov"), tmp_path), tmp_path / "work") as copy:
            assert copy is None

    def test_ffmpeg_failure_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(faststart.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        def boom(*args: object, **kwargs: object) -> None:
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr=b"bad")

        monkeypatch.setattr(faststart.subprocess, "run", boom)
        with faststart_copy(_mp4((b"mdat", b"moov"), tmp_path), tmp_path / "work") as copy:
            assert copy is None

    def test_copy_is_removed_after_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(faststart.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        def fake_run(command: list[str], **kwargs: object) -> None:
            Path(command[-1]).write_bytes(b"remuxed")

        monkeypatch.setattr(faststart.subprocess, "run", fake_run)
        with faststart_copy(_mp4((b"mdat", b"moov"), tmp_path), tmp_path / "work") as copy:
            assert copy is not None
            assert copy.read_bytes() == b"remuxed"
        assert not copy.exists()
