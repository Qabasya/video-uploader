"""Тесты GroupResolver: точное совпадение по имени папки, регистрозависимость."""

from video_uploader.config import GroupsConfig
from video_uploader.resolving.resolver import GroupResolver


def make_config() -> GroupsConfig:
    return GroupsConfig.model_validate(
        {
            "groups": {
                "КЕГЭ-1": {
                    "slug": "kege-1",
                    "lms": {"group_id": 3, "course_id": 42, "teacher_id": 7},
                },
                "ОГЭ-1": {
                    "slug": "oge-1",
                    "lms": {"group_id": 4},
                },
            }
        }
    )


class TestResolve:
    def test_known_folder_resolves(self) -> None:
        resolver = GroupResolver(make_config())
        entry = resolver.resolve("КЕГЭ-1")
        assert entry is not None
        assert entry.slug == "kege-1"
        assert entry.lms == {"group_id": 3, "course_id": 42, "teacher_id": 7}

    def test_unknown_folder_returns_none(self) -> None:
        resolver = GroupResolver(make_config())
        assert resolver.resolve("НЕИЗВЕСТНАЯ") is None

    def test_case_sensitive_match(self) -> None:
        resolver = GroupResolver(make_config())
        assert resolver.resolve("кегэ-1") is None
