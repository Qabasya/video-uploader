"""Тесты StateRepository: переходы статусов, кэш sha256, WAL, персистентность."""

import sqlite3
from pathlib import Path

import pytest

from video_uploader.state.repository import InvalidTransitionError, StateRepository


@pytest.fixture
def repo(tmp_path: Path) -> StateRepository:
    return StateRepository(tmp_path / "state.db")


def discover_one(repo: StateRepository, path: Path = Path("/mnt/video/КЕГЭ-1/rec.webm")) -> int:
    return repo.discover(path, group_name="КЕГЭ-1", size_bytes=1000, mtime=1_720_000_000.0)


class TestDiscover:
    def test_creates_record_with_discovered_status(self, repo: StateRepository) -> None:
        file_id = discover_one(repo)
        state = repo.get_by_id(file_id)
        assert state is not None
        assert state.status == "discovered"
        assert state.group_name == "КЕГЭ-1"
        assert state.attempts == 0
        assert state.sha256 is None

    def test_repeated_discover_same_path_is_idempotent(self, repo: StateRepository) -> None:
        path = Path("/mnt/video/КЕГЭ-1/rec.webm")
        first_id = discover_one(repo, path)
        second_id = discover_one(repo, path)
        assert first_id == second_id
        assert len(repo.get_recent(limit=10)) == 1


class TestCachedSha256:
    def test_none_before_set(self, repo: StateRepository) -> None:
        discover_one(repo)
        assert (
            repo.get_cached_sha256(Path("/mnt/video/КЕГЭ-1/rec.webm"), 1000, 1_720_000_000.0)
            is None
        )

    def test_returns_value_after_set(self, repo: StateRepository) -> None:
        file_id = discover_one(repo)
        repo.set_sha256(file_id, "a" * 64)
        cached = repo.get_cached_sha256(Path("/mnt/video/КЕГЭ-1/rec.webm"), 1000, 1_720_000_000.0)
        assert cached == "a" * 64

    def test_miss_when_size_or_mtime_changed(self, repo: StateRepository) -> None:
        file_id = discover_one(repo)
        repo.set_sha256(file_id, "a" * 64)
        path = Path("/mnt/video/КЕГЭ-1/rec.webm")
        assert repo.get_cached_sha256(path, 2000, 1_720_000_000.0) is None
        assert repo.get_cached_sha256(path, 1000, 1_720_000_001.0) is None


class TestHappyPath:
    def test_full_status_chain(self, repo: StateRepository) -> None:
        file_id = discover_one(repo)
        after_discover = repo.get_by_id(file_id)
        assert after_discover is not None

        repo.mark_uploading(file_id)
        after_uploading = repo.get_by_id(file_id)
        assert after_uploading is not None
        assert after_uploading.status == "uploading"
        assert after_uploading.updated_at >= after_discover.updated_at

        repo.mark_uploaded(file_id, s3_key="videos/kege-1/2026/07/rec.webm")
        after_uploaded = repo.get_by_id(file_id)
        assert after_uploaded is not None
        assert after_uploaded.status == "uploaded"
        assert after_uploaded.s3_key == "videos/kege-1/2026/07/rec.webm"

        repo.mark_registered(file_id)
        after_registered = repo.get_by_id(file_id)
        assert after_registered is not None
        assert after_registered.status == "registered"

        repo.mark_archived(file_id, archived_path=Path("/mnt/video/КЕГЭ-1/_uploaded/rec.webm"))
        after_archived = repo.get_by_id(file_id)
        assert after_archived is not None
        assert after_archived.status == "archived"
        assert after_archived.archived_path == "/mnt/video/КЕГЭ-1/_uploaded/rec.webm"


class TestMarkFailed:
    def test_increments_attempts_and_records_error(self, repo: StateRepository) -> None:
        file_id = discover_one(repo)
        repo.mark_failed(file_id, "connection timeout")
        state = repo.get_by_id(file_id)
        assert state is not None
        assert state.status == "failed"
        assert state.attempts == 1
        assert state.last_error == "connection timeout"

    def test_repeated_failure_keeps_incrementing(self, repo: StateRepository) -> None:
        file_id = discover_one(repo)
        repo.mark_failed(file_id, "timeout 1")
        repo.mark_failed(file_id, "timeout 2")
        state = repo.get_by_id(file_id)
        assert state is not None
        assert state.attempts == 2
        assert state.last_error == "timeout 2"


class TestMarkSkipped:
    @pytest.mark.parametrize("status", ["skipped_old", "skipped_unmapped"])
    def test_sets_terminal_status(self, repo: StateRepository, status: str) -> None:
        file_id = discover_one(repo)
        repo.mark_skipped(file_id, status)  # type: ignore[arg-type]
        state = repo.get_by_id(file_id)
        assert state is not None
        assert state.status == status


class TestInvalidTransitions:
    def test_register_without_upload_rejected(self, repo: StateRepository) -> None:
        file_id = discover_one(repo)
        with pytest.raises(InvalidTransitionError):
            repo.mark_registered(file_id)

    def test_transition_from_terminal_archived_rejected(self, repo: StateRepository) -> None:
        file_id = discover_one(repo)
        repo.mark_uploading(file_id)
        repo.mark_uploaded(file_id, s3_key="videos/kege-1/rec.webm")
        repo.mark_registered(file_id)
        repo.mark_archived(file_id, archived_path=Path("/archive/rec.webm"))
        with pytest.raises(InvalidTransitionError):
            repo.mark_uploading(file_id)


class TestGetBySha256:
    def test_finds_registered_record(self, repo: StateRepository) -> None:
        file_id = discover_one(repo)
        repo.set_sha256(file_id, "b" * 64)
        repo.mark_uploading(file_id)
        repo.mark_uploaded(file_id, s3_key="videos/kege-1/rec.webm")
        repo.mark_registered(file_id)

        found = repo.get_by_sha256("b" * 64)
        assert found is not None
        assert found.id == file_id
        assert found.status == "registered"

    def test_returns_none_for_unknown_hash(self, repo: StateRepository) -> None:
        assert repo.get_by_sha256("c" * 64) is None


class TestWalMode:
    def test_journal_mode_is_wal(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state.db"
        StateRepository(db_path)
        connection = sqlite3.connect(db_path)
        try:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            connection.close()
        assert mode.lower() == "wal"


class TestPersistence:
    def test_reopening_repository_sees_previous_data(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state.db"
        first = StateRepository(db_path)
        file_id = first.discover(
            Path("/mnt/video/КЕГЭ-1/rec.webm"), group_name="КЕГЭ-1", size_bytes=1000, mtime=1.0
        )

        second = StateRepository(db_path)
        state = second.get_by_id(file_id)
        assert state is not None
        assert state.group_name == "КЕГЭ-1"


class TestCountByStatus:
    def test_counts_records_per_status(self, repo: StateRepository) -> None:
        first_id = discover_one(repo, Path("/mnt/video/КЕГЭ-1/a.webm"))
        discover_one(repo, Path("/mnt/video/КЕГЭ-1/b.webm"))
        repo.mark_failed(first_id, "boom")

        counts = repo.count_by_status()
        assert counts == {"discovered": 1, "failed": 1}


class TestGetRecent:
    def test_respects_limit(self, repo: StateRepository) -> None:
        for i in range(3):
            discover_one(repo, Path(f"/mnt/video/КЕГЭ-1/{i}.webm"))
        assert len(repo.get_recent(limit=2)) == 2
