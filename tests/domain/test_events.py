"""Тесты EventBus: доставка подписчикам, изоляция ошибок; поля событий."""

import logging
from pathlib import Path

import pytest

from video_uploader.domain.events import (
    DateFallback,
    EventBus,
    GroupUnmapped,
    VideoArchived,
    VideoDiscovered,
    VideoFailed,
    VideoRegistered,
    VideoUploaded,
)


class TestDelivery:
    def test_single_subscriber_receives_event(self) -> None:
        bus = EventBus()
        received: list[VideoDiscovered] = []
        bus.subscribe(VideoDiscovered, received.append)

        event = VideoDiscovered(path=Path("/mnt/video/КЕГЭ-1/rec.webm"))
        bus.publish(event)

        assert received == [event]

    def test_multiple_subscribers_all_receive(self) -> None:
        bus = EventBus()
        first: list[VideoDiscovered] = []
        second: list[VideoDiscovered] = []
        bus.subscribe(VideoDiscovered, first.append)
        bus.subscribe(VideoDiscovered, second.append)

        event = VideoDiscovered(path=Path("/rec.webm"))
        bus.publish(event)

        assert first == [event]
        assert second == [event]

    def test_subscriber_of_other_type_not_called(self) -> None:
        bus = EventBus()
        video_events: list[VideoDiscovered] = []
        fallback_events: list[DateFallback] = []
        bus.subscribe(VideoDiscovered, video_events.append)
        bus.subscribe(DateFallback, fallback_events.append)

        bus.publish(VideoDiscovered(path=Path("/rec.webm")))

        assert len(video_events) == 1
        assert fallback_events == []

    def test_publish_without_subscribers_does_not_raise(self) -> None:
        bus = EventBus()
        bus.publish(VideoDiscovered(path=Path("/rec.webm")))


class TestErrorIsolation:
    def test_failing_subscriber_does_not_block_others(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        bus = EventBus()
        received: list[VideoDiscovered] = []

        def failing_handler(event: VideoDiscovered) -> None:
            raise RuntimeError("подписчик сломан")

        bus.subscribe(VideoDiscovered, failing_handler)
        bus.subscribe(VideoDiscovered, received.append)

        with caplog.at_level(logging.ERROR, logger="video_uploader.domain.events"):
            bus.publish(VideoDiscovered(path=Path("/rec.webm")))

        assert received
        assert "подписчик сломан" in caplog.text

    def test_failing_subscriber_does_not_propagate_to_publisher(self) -> None:
        bus = EventBus()

        def failing_handler(event: VideoDiscovered) -> None:
            raise RuntimeError("boom")

        bus.subscribe(VideoDiscovered, failing_handler)

        bus.publish(VideoDiscovered(path=Path("/rec.webm")))


class TestEventPayloads:
    """По инстанс-тесту на событие: поля доступны."""

    def test_video_uploaded_fields(self) -> None:
        event = VideoUploaded(path=Path("/rec.webm"), s3_key="videos/kege-1/rec.webm")
        assert event.s3_key == "videos/kege-1/rec.webm"

    def test_video_registered_fields(self) -> None:
        event = VideoRegistered(path=Path("/rec.webm"), s3_key="videos/kege-1/rec.webm")
        assert event.s3_key == "videos/kege-1/rec.webm"

    def test_video_archived_fields(self) -> None:
        event = VideoArchived(
            path=Path("/rec.webm"), archived_path=Path("/КЕГЭ-1/_uploaded/rec.webm")
        )
        assert event.archived_path.name == "rec.webm"

    def test_video_failed_fields(self) -> None:
        event = VideoFailed(path=Path("/rec.webm"), error="timeout", attempts=3)
        assert event.attempts == 3

    def test_group_unmapped_fields(self) -> None:
        event = GroupUnmapped(group_folder="НЕИЗВЕСТНАЯ")
        assert event.group_folder == "НЕИЗВЕСТНАЯ"

    def test_date_fallback_fields(self) -> None:
        event = DateFallback(path=Path("/rec.webm"))
        assert event.path.name == "rec.webm"
