"""Кастомный ``logging.Handler`` для Grafana Loki (HTTP push)."""

import logging

import httpx

_PUSH_PATH = "/loki/api/v1/push"
_TIMEOUT_SECONDS = 5.0
_SERVICE_LABEL = "fs-video-uploader"


class LokiHandler(logging.Handler):
    """Отправляет каждую запись отдельным push-запросом в ``/loki/api/v1/push``."""

    def __init__(self, url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__()
        self._client = httpx.Client(base_url=url, timeout=_TIMEOUT_SECONDS, transport=transport)

    def emit(self, record: logging.LogRecord) -> None:
        """Формирует один stream с одной парой (timestamp_ns, formatted_line)."""
        body = {
            "streams": [
                {
                    "stream": {
                        "service": _SERVICE_LABEL,
                        "level": record.levelname,
                        "logger": record.name,
                    },
                    "values": [[str(int(record.created * 1e9)), self.format(record)]],
                }
            ]
        }
        try:
            self._client.post(_PUSH_PATH, json=body)
        except httpx.HTTPError:
            self.handleError(record)

    def close(self) -> None:
        """Закрывает внутренний ``httpx.Client``, затем стандартную очистку хендлера."""
        self._client.close()
        super().close()
