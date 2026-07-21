"""Repository над SQLite (SQLAlchemy 2.0): единственная точка доступа к ``state.db``.

Все переходы статусов файла — методами этого класса; сырых UPDATE извне нет
(см. CLAUDE.md, раздел State). Схема таблицы и допустимые переходы статусов
живут здесь же — Repository-пакет достаточно мал, чтобы не заводить под них
отдельный ``models.py``.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import Index, create_engine, event, select
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

logger = logging.getLogger(__name__)

Status = Literal[
    "discovered",
    "uploading",
    "uploaded",
    "registered",
    "archived",
    "failed",
    "skipped_old",
    "skipped_unmapped",
]

# Допустимые переходы: текущий статус -> множество статусов, в которые можно перейти.
# Терминальные статусы (archived, skipped_old, skipped_unmapped) — пустые множества,
# кроме failed: из failed разрешён повторный заход в uploading (ретрай).
# Тип ключа/значений — plain str (не Status): статус текущей записи из БД приходит
# как обычный str, а Literal-типизация здесь дала бы только type: ignore на .get().
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "discovered": frozenset({"uploading", "failed", "skipped_old", "skipped_unmapped"}),
    "uploading": frozenset({"uploaded", "failed"}),
    "uploaded": frozenset({"registered", "failed"}),
    "registered": frozenset({"archived", "failed"}),
    "archived": frozenset(),
    "failed": frozenset({"uploading", "failed"}),
    "skipped_old": frozenset(),
    # В отличие от skipped_old (старение необратимо), дыра в groups.yaml может
    # быть закрыта админом между циклами — файл должен получить шанс на обработку.
    # "failed" тоже разрешён: если что-то упадёт при повторной попытке resolve
    # ДО mark_uploading (например, ошибка извлечения даты), pipeline должен
    # суметь записать mark_failed, а не наткнуться на InvalidTransitionError.
    "skipped_unmapped": frozenset({"uploading", "failed"}),
}


class Base(DeclarativeBase):
    """Базовый класс декларативных моделей репозитория."""


class FileRecord(Base):
    """Строка реестра: один файл на шаре и его текущий статус обработки."""

    __tablename__ = "files"
    __table_args__ = (Index("ix_files_path_size_mtime", "path", "size_bytes", "mtime"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(unique=True)
    group_name: Mapped[str]
    size_bytes: Mapped[int]
    mtime: Mapped[float]
    sha256: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="discovered")
    s3_key: Mapped[str | None] = mapped_column(default=None)
    archived_path: Mapped[str | None] = mapped_column(default=None)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[str]
    updated_at: Mapped[str]


@dataclass(frozen=True, slots=True)
class FileState:
    """Detached-снимок строки реестра — безопасен после закрытия сессии."""

    id: int
    path: str
    group_name: str
    size_bytes: int
    mtime: float
    sha256: str | None
    status: str
    s3_key: str | None
    archived_path: str | None
    attempts: int
    last_error: str | None
    created_at: str
    updated_at: str


class InvalidTransitionError(Exception):
    """Попытка перевести запись в статус, недопустимый из текущего."""


def _to_state(record: FileRecord) -> FileState:
    return FileState(
        id=record.id,
        path=record.path,
        group_name=record.group_name,
        size_bytes=record.size_bytes,
        mtime=record.mtime,
        sha256=record.sha256,
        status=record.status,
        s3_key=record.s3_key,
        archived_path=record.archived_path,
        attempts=record.attempts,
        last_error=record.last_error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


class StateRepository:
    """Реестр файлов и переходы статусов; хранилище — SQLite в режиме WAL."""

    def __init__(self, db_path: Path) -> None:
        self._engine = create_engine(f"sqlite:///{db_path}")
        event.listen(self._engine, "connect", _enable_wal)
        Base.metadata.create_all(self._engine)

    def discover(
        self, path: Path, group_name: str, size_bytes: int, mtime: float
    ) -> tuple[int, bool]:
        """Заводит запись со статусом ``discovered``; повторный вызов идемпотентен.

        Возвращает ``(file_id, is_new)`` — ``is_new`` истинен только при первом
        обнаружении файла (нужно вызывающему коду, чтобы не логировать/публиковать
        событие обнаружения повторно на каждом цикле сканирования).
        """
        path_str = str(path)
        with Session(self._engine) as session:
            existing = session.scalar(select(FileRecord).where(FileRecord.path == path_str))
            if existing is not None:
                return existing.id, False
            now = _now()
            record = FileRecord(
                path=path_str,
                group_name=group_name,
                size_bytes=size_bytes,
                mtime=mtime,
                status="discovered",
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.commit()
            return record.id, True

    def get_cached_sha256(self, path: Path, size_bytes: int, mtime: float) -> str | None:
        """``sha256`` из реестра для точного ``(path, size, mtime)`` либо ``None``."""
        with Session(self._engine) as session:
            record = session.scalar(
                select(FileRecord).where(
                    FileRecord.path == str(path),
                    FileRecord.size_bytes == size_bytes,
                    FileRecord.mtime == mtime,
                )
            )
            return record.sha256 if record is not None else None

    def set_sha256(self, file_id: int, sha256: str) -> None:
        """Кэширует посчитанный ``sha256`` для записи."""
        with Session(self._engine) as session:
            record = self._require(session, file_id)
            record.sha256 = sha256
            record.updated_at = _now()
            session.commit()

    def mark_uploading(self, file_id: int) -> None:
        """Переводит запись в статус ``uploading``."""
        self._transition(file_id, "uploading")

    def mark_uploaded(self, file_id: int, s3_key: str) -> None:
        """Переводит запись в статус ``uploaded`` и сохраняет ключ S3."""
        self._transition(file_id, "uploaded", s3_key=s3_key)

    def mark_registered(self, file_id: int) -> None:
        """Переводит запись в статус ``registered``."""
        self._transition(file_id, "registered")

    def mark_archived(self, file_id: int, archived_path: Path) -> None:
        """Переводит запись в статус ``archived`` и сохраняет путь в архиве."""
        self._transition(file_id, "archived", archived_path=str(archived_path))

    def mark_failed(self, file_id: int, error: str) -> None:
        """Переводит запись в статус ``failed``, инкрементирует ``attempts``."""
        with Session(self._engine) as session:
            record = self._require(session, file_id)
            self._ensure_allowed(record.status, "failed")
            record.status = "failed"
            record.last_error = error
            record.attempts += 1
            record.updated_at = _now()
            session.commit()

    def mark_skipped(
        self, file_id: int, status: Literal["skipped_old", "skipped_unmapped"]
    ) -> None:
        """Переводит запись в один из терминальных skipped-статусов."""
        self._transition(file_id, status)

    def get_by_id(self, file_id: int) -> FileState | None:
        """Снимок записи по её ``id`` либо ``None``, если такой записи нет."""
        with Session(self._engine) as session:
            record = session.get(FileRecord, file_id)
            return _to_state(record) if record is not None else None

    def get_by_sha256(self, sha256: str) -> FileState | None:
        """Снимок записи с данным ``sha256`` либо ``None`` — основа идемпотентности."""
        with Session(self._engine) as session:
            record = session.scalar(select(FileRecord).where(FileRecord.sha256 == sha256))
            return _to_state(record) if record is not None else None

    def count_by_status(self) -> dict[str, int]:
        """Количество записей на каждый встречающийся статус (для ``GET /status``)."""
        with Session(self._engine) as session:
            records: Iterable[FileRecord] = session.scalars(select(FileRecord))
            counts: dict[str, int] = {}
            for record in records:
                counts[record.status] = counts.get(record.status, 0) + 1
            return counts

    def get_recent(self, limit: int) -> list[FileState]:
        """Последние ``limit`` записей по времени обновления (для ``GET /status``)."""
        with Session(self._engine) as session:
            records = session.scalars(
                select(FileRecord).order_by(FileRecord.updated_at.desc()).limit(limit)
            )
            return [_to_state(record) for record in records]

    def _transition(self, file_id: int, new_status: Status, **fields: str) -> None:
        with Session(self._engine) as session:
            record = self._require(session, file_id)
            self._ensure_allowed(record.status, new_status)
            record.status = new_status
            for name, value in fields.items():
                setattr(record, name, value)
            record.updated_at = _now()
            session.commit()

    @staticmethod
    def _ensure_allowed(current: str, new_status: str) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(current)
        if allowed is None or new_status not in allowed:
            raise InvalidTransitionError(
                f"недопустимый переход статуса: {current!r} -> {new_status!r}"
            )

    @staticmethod
    def _require(session: Session, file_id: int) -> FileRecord:
        record = session.get(FileRecord, file_id)
        if record is None:
            raise ValueError(f"запись реестра не найдена: id={file_id}")
        return record


def _enable_wal(dbapi_connection: DBAPIConnection, _connection_record: object) -> None:
    """Включает WAL сразу после установления соединения (``event.listen``)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


__all__ = ["FileRecord", "FileState", "InvalidTransitionError", "StateRepository"]
