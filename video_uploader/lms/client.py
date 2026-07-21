"""REST-клиент fs-lms (httpx): регистрация видео."""

import hashlib
import hmac
import json
import time

import httpx

_TIMEOUT_SECONDS = 30.0
_ENDPOINT_PATH = "/wp-json/fs-lms/v1/videos"
_RESPONSE_TEXT_LIMIT = 500


class LmsRegistrationError(Exception):
    """Базовое исключение при регистрации видео в LMS."""


class LmsRetryableError(LmsRegistrationError):
    """5xx или сетевая ошибка — стоит повторить в следующем цикле сканирования."""


class LmsRejectedError(LmsRegistrationError):
    """Прочие 4xx — LMS отвергла payload содержательно, повторять бессмысленно."""


class LmsClient:
    """REST-клиент fs-lms: ``POST /wp-json/fs-lms/v1/videos`` с HMAC-подписью запроса."""

    def __init__(
        self,
        base_url: str,
        hmac_secret: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._hmac_secret = hmac_secret.encode("utf-8")
        self._client = httpx.Client(
            base_url=base_url,
            timeout=_TIMEOUT_SECONDS,
            transport=transport,
        )

    def register(self, payload: dict[str, object]) -> bool:
        """Один POST-запрос с HMAC-подписью; успех — ``matched``-флаг, иначе исключение.

        ``matched`` — не ошибка, а диагностика: плагин зарегистрировал видео, но не
        нашёл занятие по дате/времени. Логирует это (с полным контекстом файла)
        вызывающий код (``pipeline.py``), не этот транспортный слой.
        """
        raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        timestamp = int(time.time())
        headers = {
            "X-Fs-Timestamp": str(timestamp),
            "X-Fs-Signature": self._sign(timestamp, raw_body),
            "Content-Type": "application/json",
        }

        try:
            response = self._client.post(_ENDPOINT_PATH, content=raw_body, headers=headers)
        except httpx.HTTPError as exc:
            raise LmsRetryableError(f"сетевая ошибка LMS: {exc}") from exc

        if response.status_code in (200, 201):
            return self._extract_matched(response)

        detail = f"LMS {response.status_code}: {response.text[:_RESPONSE_TEXT_LIMIT]}"
        if response.status_code >= 500:
            raise LmsRetryableError(detail)
        raise LmsRejectedError(detail)

    def _sign(self, timestamp: int, raw_body: bytes) -> str:
        """``hex(hmac_sha256(f"{timestamp}." + raw_body, hmac_secret))``."""
        message = f"{timestamp}.".encode("ascii") + raw_body
        return hmac.new(self._hmac_secret, message, hashlib.sha256).hexdigest()

    @staticmethod
    def _extract_matched(response: httpx.Response) -> bool:
        """``False`` только при явном ``matched: false``; иначе — True (в т.ч. пустое тело)."""
        try:
            data = response.json()
        except ValueError:
            return True
        if isinstance(data, dict) and data.get("matched") is False:
            return False
        return True

    def close(self) -> None:
        """Закрывает внутренний ``httpx.Client`` (graceful shutdown)."""
        self._client.close()
