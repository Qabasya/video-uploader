"""REST-клиент fs-lms (httpx): регистрация видео."""

import logging

import httpx

logger = logging.getLogger(__name__)

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
    """REST-клиент fs-lms: ``POST /wp-json/fs-lms/v1/videos`` с токеном в заголовке."""

    def __init__(
        self, base_url: str, token: str, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"X-FS-Uploader-Token": token},
            timeout=_TIMEOUT_SECONDS,
            transport=transport,
        )

    def register(self, payload: dict[str, object]) -> None:
        """Один POST-запрос; успех — ``return``, иначе — типизированное исключение."""
        try:
            response = self._client.post(_ENDPOINT_PATH, json=payload)
        except httpx.HTTPError as exc:
            raise LmsRetryableError(f"сетевая ошибка LMS: {exc}") from exc

        if response.status_code in (200, 201):
            return

        detail = f"LMS {response.status_code}: {response.text[:_RESPONSE_TEXT_LIMIT]}"
        if response.status_code >= 500:
            raise LmsRetryableError(detail)
        raise LmsRejectedError(detail)

    def close(self) -> None:
        """Закрывает внутренний ``httpx.Client`` (graceful shutdown)."""
        self._client.close()
