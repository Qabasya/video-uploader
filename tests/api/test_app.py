"""Тесты create_app: /health, /status, /rescan — тонкий слой над repo/worker."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from video_uploader.api.app import create_app
from video_uploader.state.repository import StateRepository


class FakeWorker:
    """Лёгкий дубль ScanWorker для теста API — не настоящий фоновый поток."""

    def __init__(self) -> None:
        self.last_scan_at: datetime | None = None
        self.rescan_calls = 0

    def request_rescan(self) -> None:
        self.rescan_calls += 1


def make_client(tmp_path: Path, worker: FakeWorker) -> tuple[TestClient, StateRepository]:
    repo = StateRepository(tmp_path / "state.db")
    app = create_app(repo=repo, worker=worker)
    return TestClient(app), repo


class TestHealth:
    def test_no_scan_yet_returns_null(self, tmp_path: Path) -> None:
        client, _ = make_client(tmp_path, FakeWorker())

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "last_scan_at": None}

    def test_returns_isoformat_after_scan(self, tmp_path: Path) -> None:
        worker = FakeWorker()
        worker.last_scan_at = datetime(2026, 7, 17, 12, 0, 0, tzinfo=UTC)
        client, _ = make_client(tmp_path, worker)

        response = client.get("/health")

        assert response.json() == {
            "status": "ok",
            "last_scan_at": "2026-07-17T12:00:00+00:00",
        }


class TestStatus:
    def test_reflects_repository_state(self, tmp_path: Path) -> None:
        client, repo = make_client(tmp_path, FakeWorker())

        first_id, _ = repo.discover(Path("/mnt/video/КЕГЭ-1/a.webm"), "КЕГЭ-1", 100, 1.0)
        repo.discover(Path("/mnt/video/КЕГЭ-1/b.webm"), "КЕГЭ-1", 100, 2.0)
        repo.mark_failed(first_id, "boom")

        response = client.get("/status")

        assert response.status_code == 200
        body = response.json()
        assert body["counts"] == {"discovered": 1, "failed": 1}
        assert len(body["recent"]) == 2
        assert {record["status"] for record in body["recent"]} == {"discovered", "failed"}

    def test_recent_limited_to_twenty(self, tmp_path: Path) -> None:
        client, repo = make_client(tmp_path, FakeWorker())
        for i in range(25):
            repo.discover(Path(f"/mnt/video/КЕГЭ-1/{i}.webm"), "КЕГЭ-1", 100, float(i))

        response = client.get("/status")

        assert len(response.json()["recent"]) == 20


class TestRescan:
    def test_triggers_worker_and_returns_immediately(self, tmp_path: Path) -> None:
        worker = FakeWorker()
        client, _ = make_client(tmp_path, worker)

        response = client.post("/rescan")

        assert response.status_code == 200
        assert response.json() == {"status": "triggered"}
        assert worker.rescan_calls == 1
