"""Тесты ScanWorker и dry-run заглушек: фоновый цикл, rescan-триггер, изоляция ошибок."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

from video_uploader.config import Settings
from video_uploader.lms.client import LmsClient
from video_uploader.main import (
    DryRunLmsClient,
    DryRunS3Gateway,
    ScanWorker,
    _build_lms_client,
    _build_s3_gateway,
)
from video_uploader.storage.s3_gateway import S3Gateway

REQUIRED_SETTINGS: dict[str, object] = {
    "s3_bucket": "bucket",
    "s3_access_key": "access-key",
    "s3_secret_key": "top-secret",
    "lms_base_url": "http://lms.local",
    "lms_hmac_secret": "hmac-secret",
}


def make_settings(**overrides: object) -> Settings:
    """Settings с заполненными обязательными полями; локальный .env не читается."""
    return Settings(_env_file=None, **{**REQUIRED_SETTINGS, **overrides})


class FakePipeline:
    """Фейк Pipeline: считает вызовы run_cycle(), может бросать на первых N вызовах."""

    def __init__(self, fail_first_n: int = 0) -> None:
        self.call_count = 0
        self._fail_first_n = fail_first_n

    def run_cycle(self) -> None:
        self.call_count += 1
        if self.call_count <= self._fail_first_n:
            raise RuntimeError(f"boom #{self.call_count}")


def wait_until(
    predicate: Callable[[], bool], *, timeout: float = 2.0, interval: float = 0.01
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def start(worker: ScanWorker) -> threading.Thread:
    thread = threading.Thread(target=worker.run)
    thread.start()
    return thread


class TestLifecycle:
    def test_stop_terminates_thread(self) -> None:
        pipeline = FakePipeline()
        worker = ScanWorker(pipeline, scan_interval_seconds=60)
        thread = start(worker)

        assert wait_until(lambda: pipeline.call_count >= 1)
        worker.stop()
        thread.join(timeout=2.0)

        assert not thread.is_alive()

    def test_last_scan_at_updates_after_each_cycle(self) -> None:
        pipeline = FakePipeline()
        worker = ScanWorker(pipeline, scan_interval_seconds=60)
        thread = start(worker)

        assert wait_until(lambda: worker.last_scan_at is not None)
        first = worker.last_scan_at

        worker.request_rescan()
        assert wait_until(lambda: pipeline.call_count >= 2)
        assert wait_until(lambda: worker.last_scan_at != first)

        worker.stop()
        thread.join(timeout=2.0)


class TestRequestRescan:
    def test_wakes_up_immediately_without_waiting_full_interval(self) -> None:
        pipeline = FakePipeline()
        worker = ScanWorker(pipeline, scan_interval_seconds=60)
        thread = start(worker)

        assert wait_until(lambda: pipeline.call_count >= 1)
        started_at = time.monotonic()
        worker.request_rescan()

        assert wait_until(lambda: pipeline.call_count >= 2, timeout=1.0)
        elapsed = time.monotonic() - started_at

        worker.stop()
        thread.join(timeout=2.0)

        assert elapsed < 1.0  # точно меньше scan_interval_seconds=60


class TestErrorIsolation:
    def test_exception_in_run_cycle_does_not_kill_thread(self) -> None:
        pipeline = FakePipeline(fail_first_n=1)
        worker = ScanWorker(pipeline, scan_interval_seconds=60)
        thread = start(worker)

        assert wait_until(lambda: pipeline.call_count >= 1)
        worker.request_rescan()
        assert wait_until(lambda: pipeline.call_count >= 2)

        assert thread.is_alive()
        worker.stop()
        thread.join(timeout=2.0)
        assert not thread.is_alive()


class TestDryRunS3Gateway:
    def test_methods_do_not_raise(self, tmp_path: Path) -> None:
        gateway = DryRunS3Gateway()
        video_path = tmp_path / "rec.webm"
        video_path.write_bytes(b"data")

        gateway.upload_video(video_path, "videos/kege-1/rec.webm", {"group-slug": "kege-1"})
        gateway.put_manifest("videos/kege-1/rec.webm.json", {"schema": 2})
        assert gateway.verify("videos/kege-1/rec.webm", 4) is True
        gateway.close()


class TestDryRunLmsClient:
    def test_register_does_not_raise(self) -> None:
        client = DryRunLmsClient()
        client.register({"s3_key": "videos/kege-1/rec.webm"})
        client.close()


class TestBuildGateways:
    def test_live_run_always_real_regardless_of_lms_live_flag(self) -> None:
        settings = make_settings(dry_run=False, dry_run_lms_live=False)
        assert isinstance(_build_s3_gateway(settings), S3Gateway)
        assert isinstance(_build_lms_client(settings), LmsClient)

        settings = make_settings(dry_run=False, dry_run_lms_live=True)
        assert isinstance(_build_s3_gateway(settings), S3Gateway)
        assert isinstance(_build_lms_client(settings), LmsClient)

    def test_dry_run_default_fakes_both(self) -> None:
        settings = make_settings(dry_run=True, dry_run_lms_live=False)
        assert isinstance(_build_s3_gateway(settings), DryRunS3Gateway)
        assert isinstance(_build_lms_client(settings), DryRunLmsClient)

    def test_dry_run_lms_live_fakes_only_s3(self) -> None:
        settings = make_settings(dry_run=True, dry_run_lms_live=True)
        assert isinstance(_build_s3_gateway(settings), DryRunS3Gateway)
        assert isinstance(_build_lms_client(settings), LmsClient)
