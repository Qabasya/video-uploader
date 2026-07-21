"""Тесты LmsClient: HMAC-подпись, классификация ответа, поле matched, сетевые ошибки."""

import hashlib
import hmac
import json
import time

import httpx
import pytest

from video_uploader.lms.client import LmsClient, LmsRejectedError, LmsRetryableError

PAYLOAD = {"s3_key": "videos/kege-1/rec.webm", "group_slug": "kege-1"}
SECRET = "test-hmac-secret"


def make_client(handler: httpx.MockTransport) -> LmsClient:
    return LmsClient(base_url="http://lms.local", hmac_secret=SECRET, transport=handler)


def make_capturing_client() -> tuple[LmsClient, list[httpx.Request]]:
    """Клиент с транспортом, который отвечает 200 и запоминает каждый запрос."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    return make_client(httpx.MockTransport(handler)), captured


def expected_signature(timestamp: str, raw_body: bytes) -> str:
    """Независимый (от кода LmsClient) пересчёт подписи — так тест не спишет с реализации."""
    message = f"{timestamp}.".encode("ascii") + raw_body
    return hmac.new(SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


class TestHmacSigning:
    def test_headers_present_with_fresh_timestamp(self) -> None:
        client, captured = make_capturing_client()

        client.register(PAYLOAD)

        request = captured[0]
        assert "X-Fs-Timestamp" in request.headers
        assert "X-Fs-Signature" in request.headers
        assert abs(int(request.headers["X-Fs-Timestamp"]) - time.time()) < 5

    def test_signature_matches_independent_computation(self) -> None:
        client, captured = make_capturing_client()

        client.register(PAYLOAD)

        request = captured[0]
        expected = expected_signature(request.headers["X-Fs-Timestamp"], request.content)
        assert request.headers["X-Fs-Signature"] == expected

    def test_content_type_header(self) -> None:
        client, captured = make_capturing_client()

        client.register(PAYLOAD)

        assert captured[0].headers["Content-Type"] == "application/json"

    def test_body_bytes_match_payload(self) -> None:
        client, captured = make_capturing_client()

        client.register(PAYLOAD)

        assert json.loads(captured[0].content.decode("utf-8")) == PAYLOAD


class TestSuccess:
    @pytest.mark.parametrize("status_code", [200, 201])
    def test_no_exception_raised(self, status_code: int) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(status_code))
        client = make_client(transport)

        client.register(PAYLOAD)  # не должно бросать исключений

    def test_returns_true_when_no_body(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        client = make_client(transport)

        assert client.register(PAYLOAD) is True

    def test_sends_correct_path(self) -> None:
        client, captured = make_capturing_client()

        client.register(PAYLOAD)

        assert captured[0].url.path == "/wp-json/fs-lms/v1/videos"


class TestMatchedField:
    """С 2026-07-21 клиент только возвращает ``matched``; логирование — забота pipeline.py."""

    def test_matched_true_returns_true(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True, "matched": True})
        )
        client = make_client(transport)

        assert client.register(PAYLOAD) is True

    def test_matched_false_returns_false(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True, "matched": False})
        )
        client = make_client(transport)

        assert client.register(PAYLOAD) is False  # не должно бросать

    def test_invalid_json_body_returns_true(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"not json at all")
        )
        client = make_client(transport)

        # успех уже по статусу, парсинг matched — best-effort: неразбираемое тело не считаем отказом
        assert client.register(PAYLOAD) is True


class TestRetryable:
    @pytest.mark.parametrize("status_code", [500, 502, 503])
    def test_5xx_raises_retryable(self, status_code: int) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(status_code, text="oops"))
        client = make_client(transport)

        with pytest.raises(LmsRetryableError, match=str(status_code)):
            client.register(PAYLOAD)

    def test_network_error_raises_retryable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = make_client(httpx.MockTransport(handler))

        with pytest.raises(LmsRetryableError, match="сетевая ошибка"):
            client.register(PAYLOAD)

    def test_error_message_contains_body_fragment(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(503, text="database is unavailable")
        )
        client = make_client(transport)

        with pytest.raises(LmsRetryableError, match="database is unavailable"):
            client.register(PAYLOAD)


class TestRejected:
    @pytest.mark.parametrize("status_code", [400, 401, 404, 422])
    def test_other_4xx_raises_rejected(self, status_code: int) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(status_code, text="bad"))
        client = make_client(transport)

        with pytest.raises(LmsRejectedError, match=str(status_code)):
            client.register(PAYLOAD)

    def test_rejected_is_not_retryable(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(400))
        client = make_client(transport)

        with pytest.raises(LmsRejectedError):
            try:
                client.register(PAYLOAD)
            except LmsRetryableError:
                pytest.fail("400 не должен классифицироваться как retryable")


class TestClose:
    def test_close_marks_client_closed(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        client = make_client(transport)

        client.close()

        with pytest.raises(RuntimeError):
            client.register(PAYLOAD)
