"""Кастомный ``logging.Handler`` для Grafana Loki (HTTP push)."""


class LokiHandler:
    """Отправка записей в ``/loki/api/v1/push`` (заглушка этапа 9)."""
