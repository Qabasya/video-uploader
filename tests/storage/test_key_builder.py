"""Тесты KeyBuilder: формат ключа по CLAUDE.md, регистр расширения, защита charset."""

from datetime import datetime, timedelta, timezone

import pytest

from video_uploader.storage.key_builder import KeyBuilder

MOSCOW = timezone(timedelta(hours=3))


class TestVideoKey:
    def test_matches_claude_md_example(self) -> None:
        builder = KeyBuilder(prefix="videos")
        recorded_at = datetime(2026, 7, 8, 16, 4, 45, tzinfo=MOSCOW)

        key = builder.build_video_key(
            group_slug="kege-1",
            recorded_at=recorded_at,
            sha256="a1b2c3d4" + "e" * 56,
            ext=".webm",
        )

        assert key == "videos/kege-1/2026/07/2026-07-08_16-04_a1b2c3d4.webm"

    def test_extension_is_lowercased(self) -> None:
        builder = KeyBuilder(prefix="videos")
        key = builder.build_video_key(
            group_slug="kege-1",
            recorded_at=datetime(2026, 7, 8, 16, 4, 45, tzinfo=MOSCOW),
            sha256="a" * 64,
            ext=".WEBM",
        )
        assert key.endswith(".webm")

    def test_custom_prefix(self) -> None:
        builder = KeyBuilder(prefix="records")
        key = builder.build_video_key(
            group_slug="kege-1",
            recorded_at=datetime(2026, 7, 8, 16, 4, 45, tzinfo=MOSCOW),
            sha256="a" * 64,
            ext=".webm",
        )
        assert key.startswith("records/kege-1/")

    def test_invalid_characters_rejected(self) -> None:
        builder = KeyBuilder(prefix="videos")
        with pytest.raises(ValueError, match="недопустимые символы"):
            builder.build_video_key(
                group_slug="кегэ-1",  # валидация выше по стеку почему-то не сработала
                recorded_at=datetime(2026, 7, 8, 16, 4, 45, tzinfo=MOSCOW),
                sha256="a" * 64,
                ext=".webm",
            )


class TestManifestKey:
    def test_appends_json_suffix(self) -> None:
        builder = KeyBuilder(prefix="videos")
        assert builder.build_manifest_key("videos/kege-1/rec.webm") == (
            "videos/kege-1/rec.webm.json"
        )
