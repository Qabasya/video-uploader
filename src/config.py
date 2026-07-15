"""Конфигурация сервиса (pydantic-settings; источник — env/.env)."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки сервиса (заглушка этапа 1; поля и валидация — этап 2)."""
