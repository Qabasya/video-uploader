"""Кастомный ``logging.Handler`` для Grafana Loki (HTTP push).

Формат/лейблы и обработка ошибок унифицированы с ``fs-adsync`` (второй сервис,
пушащий в тот же Loki) — см. его ``src/logging_setup.py``: lowercase ``level``,
широкий ``except Exception`` вокруг всего push (не только ``httpx.HTTPError`` —
падение хендлера логирования не должно ронять сервис ни при какой причине сбоя),
``response.raise_for_status()``, чтобы 4xx/5xx от самого Loki тоже уходили в
``handleError``, а не терялись молча.
"""

import logging

import httpx

_PUSH_PATH = "/loki/api/v1/push"
_TIMEOUT_SECONDS = 5.0
_DEFAULT_SERVICE_LABEL = "fs-video-uploader"


class LokiHandler(logging.Handler):
    """Отправляет каждую запись отдельным push-запросом в ``/loki/api/v1/push``."""

    def __init__(
        self,
        url: str,
        *,
        service: str = _DEFAULT_SERVICE_LABEL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._client = httpx.Client(base_url=url, timeout=_TIMEOUT_SECONDS, transport=transport)

    def emit(self, record: logging.LogRecord) -> None:
        """Формирует один stream с одной парой (timestamp_ns, formatted_line)."""
        try:
            body = {
                "streams": [
                    {
                        "stream": {
                            "service": self._service,
                            "level": record.levelname.lower(),
                            "logger": record.name,
                        },
                        "values": [[str(int(record.created * 1e9)), self.format(record)]],
                    }
                ]
            }
            response = self._client.post(_PUSH_PATH, json=body)
            response.raise_for_status()
        except Exception:
            # Не только httpx.HTTPError: например RuntimeError у httpx.Client,
            # закрытого во время shutdown, тоже не должен ронять вызывающий код —
            # это и есть контракт logging.Handler.emit() (см. handleError).
            self.handleError(record)

    def close(self) -> None:
        """Закрывает внутренний ``httpx.Client``, затем стандартную очистку хендлера."""
        self._client.close()
        super().close()
