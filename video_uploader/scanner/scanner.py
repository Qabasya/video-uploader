"""Обход ``VIDEO_ROOT/<группа>/*`` (глубина ровно 1) и отбор кандидатов."""

import logging
from pathlib import Path

from video_uploader.domain.models import VideoFile

logger = logging.getLogger(__name__)


class VideoScanner:
    """Сканер шары: подпапка = группа, архив и скрытые файлы игнорируются."""

    def __init__(self, video_root: Path, allowed_extensions: tuple[str, ...]) -> None:
        self._video_root = video_root
        self._allowed_extensions = allowed_extensions

    def scan(self) -> list[VideoFile]:
        """Кандидаты из всех папок групп, отсортированные по mtime (старые первыми)."""
        candidates: list[VideoFile] = []
        for group_dir in self._video_root.iterdir():
            if not group_dir.is_dir():
                continue
            candidates.extend(self._scan_group(group_dir))
        return sorted(candidates, key=lambda video_file: video_file.mtime)

    def _scan_group(self, group_dir: Path) -> list[VideoFile]:
        try:
            entries = list(group_dir.iterdir())
        except OSError as exc:
            logger.warning(
                "не удалось прочитать папку группы %s: %s",
                group_dir,
                exc,
                extra={"event": "group_folder_read_error"},
            )
            return []

        candidates: list[VideoFile] = []
        for entry in entries:
            if self._is_candidate(entry):
                candidates.append(self._to_video_file(entry, group_dir.name))
        return candidates

    def _is_candidate(self, path: Path) -> bool:
        if not path.is_file():
            return False
        if path.name.startswith(".") or path.name.startswith("~"):
            return False
        return path.suffix.lower() in self._allowed_extensions

    @staticmethod
    def _to_video_file(path: Path, group_folder: str) -> VideoFile:
        stat = path.stat()
        return VideoFile(
            path=path,
            group_folder=group_folder,
            size_bytes=stat.st_size,
            mtime=stat.st_mtime,
        )
