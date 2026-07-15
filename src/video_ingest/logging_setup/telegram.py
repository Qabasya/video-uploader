"""Кастомный ``logging.Handler`` для Telegram (ERROR+, антифлуд)."""


class TelegramLogHandler:
    """Логи уровня ERROR+ в Telegram, одинаковый текст не чаще раза в 30 с (заглушка этапа 9)."""
