"""Тесты LokiHandler: формат push-запроса, устойчивость к сетевым ошибкам."""

import logging

import httpx
import pytest

from video_uploader.logging_setup.loki import LokiHandler


def make_record(
    message: str = "тестовое сообщение", level: int = logging.INFO
) -> logging.LogRecord:
    return logging.getLogger("video_uploader.some.module").makeRecord(
        "video_uploader.some.module", level, __file__, 1, message, (), None
    )


class TestPushFormat:
    def test_sends_expected_body_shape(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(204)

        loki_handler = LokiHandler("http://loki.local", transport=httpx.MockTransport(handler))
        loki_handler.emit(make_record("привет"))

        assert len(captured) == 1
        request = captured[0]
        assert request.url.path == "/loki/api/v1/push"

        import json

        body = json.loads(request.content.decode("utf-8"))
        stream = body["streams"][0]
        assert stream["stream"]["service"] == "fs-video-uploader"
        assert stream["stream"]["level"] == "info"  # lowercase — единый вид с fs-adsync
        assert stream["stream"]["logger"] == "video_uploader.some.module"
        assert len(stream["values"]) == 1
        timestamp_ns, line = stream["values"][0]
        assert timestamp_ns.isdigit()
        assert "привет" in line

    def test_uses_attached_formatter(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(204)

        loki_handler = LokiHandler("http://loki.local", transport=httpx.MockTransport(handler))
        loki_handler.setFormatter(logging.Formatter("PREFIX: %(message)s"))
        loki_handler.emit(make_record("текст"))

        import json

        body = json.loads(captured[0].content.decode("utf-8"))
        assert body["streams"][0]["values"][0][1] == "PREFIX: текст"

    def test_custom_service_label(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(204)

        loki_handler = LokiHandler(
            "http://loki.local", service="fs-adsync", transport=httpx.MockTransport(handler)
        )
        loki_handler.emit(make_record())

        import json

        body = json.loads(captured[0].content.decode("utf-8"))
        assert body["streams"][0]["stream"]["service"] == "fs-adsync"


class TestNetworkErrors:
    def test_connection_error_does_not_raise(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        loki_handler = LokiHandler("http://loki.local", transport=httpx.MockTransport(handler))
        loki_handler.raiseExceptions = False  # handleError не должен печатать в stderr в тесте

        loki_handler.emit(make_record())  # не должно бросать исключений

    def test_connection_error_calls_handle_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        loki_handler = LokiHandler("http://loki.local", transport=httpx.MockTransport(handler))

        calls: list[logging.LogRecord] = []
        monkeypatch.setattr(loki_handler, "handleError", calls.append)

        record = make_record()
        loki_handler.emit(record)

        assert calls == [record]

    def test_non_2xx_loki_response_calls_handle_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Раньше ответ Loki не проверялся (не было raise_for_status()) — 5xx терялись молча."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        loki_handler = LokiHandler("http://loki.local", transport=httpx.MockTransport(handler))

        calls: list[logging.LogRecord] = []
        monkeypatch.setattr(loki_handler, "handleError", calls.append)

        record = make_record()
        loki_handler.emit(record)

        assert calls == [record]

    def test_emit_after_close_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Регрессия: RuntimeError('client has been closed') раньше не ловился —
        ``except httpx.HTTPError`` его не покрывал, и хендлер ронял вызывающий поток
        (пайплайн падал целиком при попытке залогировать после закрытия клиента)."""
        loki_handler = LokiHandler(
            "http://loki.local", transport=httpx.MockTransport(lambda request: httpx.Response(204))
        )
        loki_handler.close()

        calls: list[logging.LogRecord] = []
        monkeypatch.setattr(loki_handler, "handleError", calls.append)

        record = make_record()
        loki_handler.emit(record)  # не должно бросать RuntimeError

        assert calls == [record]


class TestClose:
    def test_close_closes_underlying_client(self) -> None:
        loki_handler = LokiHandler(
            "http://loki.local", transport=httpx.MockTransport(lambda request: httpx.Response(204))
        )

        loki_handler.close()

        assert loki_handler._client.is_closed
