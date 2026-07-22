"""Кастомный ``logging.Handler`` для Grafana Loki (HTTP push).

Формат/лейблы и обработка ошибок унифицированы с ``fs-adsync`` (второй сервис,
пушащий в тот же Loki) — см. его ``src/logging_setup.py``: lowercase ``level``,
широкий ``except Exception`` вокруг всего push (не только ``httpx.HTTPError`` —
падение хендлера логирования не должно ронять сервис ни при какой причине сбоя),
``response.raise_for_status()``, чтобы 4xx/5xx от самого Loki тоже уходили в
``handleError``, а не терялись молча.

Помимо ``service``/``level``/``logger``, при наличии ``record.event`` (передаётся через
``extra={"event": "..."}`` на вызывающей стороне) добавляется четвёртый лейбл ``event`` —
низкая кардинальность (десяток-два фиксированных значений), нужен для счётчиков и алертов
в Grafana без regexp-парсинга текста строки (см. ``.docs/Events-Logging.md``).
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
        self._url = url
        self._service = service
        self._transport = transport
        self._client = self._build_client()

    def _build_client(self) -> httpx.Client:
        return httpx.Client(base_url=self._url, timeout=_TIMEOUT_SECONDS, transport=self._transport)

    def emit(self, record: logging.LogRecord) -> None:
        """Формирует один stream с одной парой (timestamp_ns, formatted_line)."""
        try:
            if self._client.is_closed:
                # На проде клиент периодически оказывается закрытым не через явный
                # close() этого хендлера (см. .docs/Tasks.md — источник не
                # локализован статическим анализом, несмотря на разбор). Тихая
                # потеря ВСЕЙ доставки в Loki до конца жизни процесса хуже, чем
                # прозрачно пересобрать клиент и продолжить попытки push.
                self._client = self._build_client()
            stream_labels: dict[str, str] = {
                "service": self._service,
                "level": record.levelname.lower(),
                "logger": record.name,
            }
            event = getattr(record, "event", None)
            if event is not None:
                stream_labels["event"] = str(event)
            body = {
                "streams": [
                    {
                        "stream": stream_labels,
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
