"""Тесты LmsClient: классификация ответа, заголовок токена, сетевые ошибки."""

import json

import httpx
import pytest

from video_uploader.lms.client import LmsClient, LmsRejectedError, LmsRetryableError

PAYLOAD = {"s3_key": "videos/kege-1/rec.webm", "group_slug": "kege-1"}


def make_client(handler: httpx.MockTransport) -> LmsClient:
    return LmsClient(base_url="http://lms.local", token="secret-token", transport=handler)


class TestSuccess:
    @pytest.mark.parametrize("status_code", [200, 201])
    def test_no_exception_raised(self, status_code: int) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(status_code))
        client = make_client(transport)

        client.register(PAYLOAD)  # не должно бросать исключений

    def test_sends_correct_request(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200)

        client = make_client(httpx.MockTransport(handler))
        client.register(PAYLOAD)

        assert len(captured) == 1
        request = captured[0]
        assert request.url.path == "/wp-json/fs-lms/v1/videos"
        assert request.headers["X-FS-Uploader-Token"] == "secret-token"
        assert json.loads(request.content.decode("utf-8")) == PAYLOAD


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
    @pytest.mark.parametrize("status_code", [400, 404, 422])
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
