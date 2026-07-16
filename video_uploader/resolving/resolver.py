"""``GroupResolver``: имя подпапки → ``slug`` + блок ``lms`` из groups.yaml."""

from video_uploader.config import GroupEntry, GroupsConfig


class GroupResolver:
    """Точное сопоставление ``group_folder`` -> ``GroupEntry`` по уже загруженному конфигу."""

    def __init__(self, groups_config: GroupsConfig) -> None:
        self._groups = groups_config.groups

    def resolve(self, group_folder: str) -> GroupEntry | None:
        """``None`` — папка не описана в groups.yaml (регистрозависимое точное имя)."""
        return self._groups.get(group_folder)
