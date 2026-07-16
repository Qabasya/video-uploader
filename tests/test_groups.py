"""Тесты load_groups/GroupsConfig: валидный конфиг, все ветки отказа схемы."""

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from video_uploader.config import load_groups


def write_yaml(tmp_path: Path, content: str) -> Path:
    """Пишет dedent-нутый yaml во временный groups.yaml и возвращает путь к нему."""
    path = tmp_path / "groups.yaml"
    path.write_text(dedent(content), encoding="utf-8")
    return path


def test_valid_config_loads(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        """
        groups:
          "КЕГЭ-1":
            slug: kege-1
            lms:
              group_id: 3
              course_id: 42
              teacher_id: 7
        """,
    )
    config = load_groups(path)
    entry = config.groups["КЕГЭ-1"]
    assert entry.slug == "kege-1"
    assert entry.lms == {"group_id": 3, "course_id": 42, "teacher_id": 7}


def test_multiple_groups_load(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        """
        groups:
          "КЕГЭ-1":
            slug: kege-1
            lms:
              group_id: 3
          "ОГЭ-1":
            slug: oge-1
            lms:
              group_id: 4
        """,
    )
    config = load_groups(path)
    assert set(config.groups) == {"КЕГЭ-1", "ОГЭ-1"}


class TestSlugValidation:
    @pytest.mark.parametrize("bad_slug", ["KEGE-1", "-kege", "kege_1", "kege--1", ""])
    def test_invalid_slug_rejected(self, tmp_path: Path, bad_slug: str) -> None:
        path = write_yaml(
            tmp_path,
            f"""
            groups:
              "КЕГЭ-1":
                slug: {bad_slug!r}
                lms:
                  group_id: 3
            """,
        )
        with pytest.raises(ValidationError):
            load_groups(path)

    def test_duplicate_slug_rejected(self, tmp_path: Path) -> None:
        path = write_yaml(
            tmp_path,
            """
            groups:
              "КЕГЭ-1":
                slug: kege-1
                lms:
                  group_id: 3
              "КЕГЭ-2":
                slug: kege-1
                lms:
                  group_id: 4
            """,
        )
        with pytest.raises(ValueError, match="повторяющиеся slug"):
            load_groups(path)


class TestLmsValidation:
    def test_empty_lms_rejected(self, tmp_path: Path) -> None:
        path = write_yaml(
            tmp_path,
            """
            groups:
              "КЕГЭ-1":
                slug: kege-1
                lms: {}
            """,
        )
        with pytest.raises(ValidationError, match="пустым"):
            load_groups(path)

    def test_missing_lms_rejected(self, tmp_path: Path) -> None:
        path = write_yaml(
            tmp_path,
            """
            groups:
              "КЕГЭ-1":
                slug: kege-1
            """,
        )
        with pytest.raises(ValidationError):
            load_groups(path)

    def test_nested_lms_value_rejected(self, tmp_path: Path) -> None:
        path = write_yaml(
            tmp_path,
            """
            groups:
              "КЕГЭ-1":
                slug: kege-1
                lms:
                  ids:
                    group: 3
            """,
        )
        with pytest.raises(ValidationError):
            load_groups(path)

    def test_non_ascii_value_rejected(self, tmp_path: Path) -> None:
        path = write_yaml(
            tmp_path,
            """
            groups:
              "КЕГЭ-1":
                slug: kege-1
                lms:
                  teacher: Иванов
            """,
        )
        with pytest.raises(ValidationError, match="ASCII"):
            load_groups(path)

    def test_invalid_lms_key_rejected(self, tmp_path: Path) -> None:
        path = write_yaml(
            tmp_path,
            """
            groups:
              "КЕГЭ-1":
                slug: kege-1
                lms:
                  Group-ID: 3
            """,
        )
        with pytest.raises(ValidationError, match="недопустимый ключ"):
            load_groups(path)

    def test_bool_value_rejected(self, tmp_path: Path) -> None:
        path = write_yaml(
            tmp_path,
            """
            groups:
              "КЕГЭ-1":
                slug: kege-1
                lms:
                  group_id: true
            """,
        )
        with pytest.raises(ValidationError):
            load_groups(path)


def test_unknown_field_rejected(tmp_path: Path) -> None:
    """Опечатка вроде lsm: вместо lms: должна падать, а не молча игнорироваться."""
    path = write_yaml(
        tmp_path,
        """
        groups:
          "КЕГЭ-1":
            slug: kege-1
            lsm:
              group_id: 3
        """,
    )
    with pytest.raises(ValidationError):
        load_groups(path)


class TestFileErrors:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="не удалось прочитать"):
            load_groups(tmp_path / "does-not-exist.yaml")

    def test_broken_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "groups.yaml"
        path.write_text("groups: [this, is, not: valid", encoding="utf-8")
        with pytest.raises(ValueError, match="битый YAML"):
            load_groups(path)

    def test_top_level_not_a_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / "groups.yaml"
        path.write_text("- one\n- two\n", encoding="utf-8")
        with pytest.raises(ValueError, match="словарь верхнего уровня"):
            load_groups(path)
