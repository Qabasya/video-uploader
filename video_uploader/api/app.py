"""FastAPI-приложение: ``/health``, ``/status``, ``/rescan`` — без бизнес-логики."""

from datetime import datetime
from typing import Protocol

from fastapi import FastAPI

from video_uploader.state.repository import StateRepository

_RECENT_LIMIT = 20


class ScanWorkerLike(Protocol):
    """Узкий интерфейс воркера, нужный API — не импортирует ``ScanWorker`` из ``main.py``."""

    last_scan_at: datetime | None

    def request_rescan(self) -> None: ...


def create_app(*, repo: StateRepository, worker: ScanWorkerLike) -> FastAPI:
    """Тонкий слой над репозиторием/воркером; вся логика — прямые вызовы, без правил."""
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, object]:
        last_scan_at = worker.last_scan_at
        return {"status": "ok", "last_scan_at": last_scan_at.isoformat() if last_scan_at else None}

    @app.get("/status")
    def status() -> dict[str, object]:
        return {
            "counts": repo.count_by_status(),
            "recent": repo.get_recent(_RECENT_LIMIT),
        }

    @app.post("/rescan")
    def rescan() -> dict[str, str]:
        worker.request_rescan()
        return {"status": "triggered"}

    return app
