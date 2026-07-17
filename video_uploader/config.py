"""Конфигурация сервиса (pydantic-settings; источник — env/.env) и маппинг групп."""

import re
from pathlib import Path
from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_REQUIRED_DATE_GROUPS = frozenset({"day", "month", "year", "hour", "minute", "second"})
_SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_LMS_KEY_PATTERN = re.compile(r"[a-z0-9_]+")


class Settings(BaseSettings):
    """Настройки сервиса из переменных окружения и ``.env``.

    Создаётся только в composition root (``main.py``); глобального экземпляра нет.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Пути
    video_root: Path = Path("/mnt/video")
    data_dir: Path = Path("/data")
    groups_file: Path = Path("/app/config/groups.yaml")

    # Числа с ограничениями
    scan_interval_seconds: int = Field(default=300, ge=1)
    stability_minutes: int = Field(default=5, ge=1)
    max_attempts: int = Field(default=5, ge=1)
    api_port: int = Field(default=8090, ge=1, le=65535)

    # Опциональные числа
    skip_older_than_days: int | None = Field(default=None, ge=1)

    # Флаги
    archive_after_register: bool = Field(default=True)
    dry_run: bool = Field(default=False)

    # Строки с default
    archive_subdir: str = Field(default="_uploaded")
    tz_name: str = Field(default="Europe/Kaliningrad")
    s3_endpoint_url: str = Field(default="https://s3.ru1.storage.beget.cloud")
    s3_region: str = Field(default="ru-1")
    s3_key_prefix: str = Field(default="videos")

    # Обязательные строки
    s3_bucket: str
    s3_access_key: str
    lms_base_url: str

    # Секреты
    s3_secret_key: SecretStr
    lms_hmac_secret: SecretStr
    telegram_bot_token: SecretStr | None = None

    # Опциональные строки
    loki_url: str | None = None
    telegram_chat_id: str | None = None
    date_regex: str | None = None

    # Расширения файлов
    allowed_extensions: Annotated[tuple[str, ...], NoDecode] = (".webm", ".mp4", ".mkv")

    @field_validator(
        "skip_older_than_days",
        "loki_url",
        "telegram_chat_id",
        "date_regex",
        mode="before",
    )
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        """Пустая строка в env (``LOKI_URL=``) означает «не задано», а не значение."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def _parse_extensions(cls, value: object) -> object:
        """Строка ``.webm,.mp4`` из env → нормализованный кортеж расширений."""
        if not isinstance(value, str):
            return value
        items = [part.strip().lower() for part in value.split(",") if part.strip()]
        if not items:
            raise ValueError("ALLOWED_EXTENSIONS: список расширений пуст")
        return tuple(ext if ext.startswith(".") else f".{ext}" for ext in items)

    @field_validator("tz_name")
    @classmethod
    def _check_tz(cls, value: str) -> str:
        """Часовой пояс должен существовать в базе zoneinfo."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"TZ_NAME: неизвестный часовой пояс {value!r}") from exc
        return value

    @field_validator("date_regex")
    @classmethod
    def _check_date_regex(cls, value: str | None) -> str | None:
        """Пользовательский DATE_REGEX обязан компилироваться и содержать все группы даты."""
        if value is None:
            return value
        try:
            pattern = re.compile(value)
        except re.error as exc:
            raise ValueError(f"DATE_REGEX: не компилируется: {exc}") from exc
        missing = _REQUIRED_DATE_GROUPS - set(pattern.groupindex)
        if missing:
            raise ValueError(f"DATE_REGEX: нет именованных групп: {', '.join(sorted(missing))}")
        return value


class GroupEntry(BaseModel):
    """Одна учебная группа из ``groups.yaml``: slug для ключей S3 и блок ID для LMS."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: str = Field(pattern=_SLUG_PATTERN)
    lms: dict[str, int | str]

    @field_validator("lms", mode="before")
    @classmethod
    def _check_lms(cls, value: object) -> object:
        """Плоский непустой словарь: ключи ``[a-z0-9_]+``, значения int или ASCII-строка.

        ``mode="before"`` — проверка идёт до приведения типов pydantic, иначе
        ``bool`` (подкласс ``int``) успевает превратиться в обычный ``int`` и
        проверка ``isinstance(item, bool)`` ниже перестаёт что-либо ловить.
        """
        if not isinstance(value, dict):
            return value
        if not value:
            raise ValueError("блок lms не может быть пустым")
        for key, item in value.items():
            if not isinstance(key, str) or not _LMS_KEY_PATTERN.fullmatch(key):
                raise ValueError(f"lms: недопустимый ключ {key!r}")
            if isinstance(item, bool):
                raise ValueError(f"lms.{key}: bool не допускается, нужен int или ASCII-строка")
            if isinstance(item, str) and not item.isascii():
                raise ValueError(f"lms.{key}: значение должно быть ASCII, получено {item!r}")
        return value


class GroupsConfig(BaseModel):
    """Содержимое ``groups.yaml``: имя подпапки в ``VIDEO_ROOT`` → :class:`GroupEntry`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    groups: dict[str, GroupEntry]

    @model_validator(mode="after")
    def _check_unique_slugs(self) -> Self:
        """slug должен однозначно определять группу — иначе не различить ключи S3."""
        folders_by_slug: dict[str, list[str]] = {}
        for folder, entry in self.groups.items():
            folders_by_slug.setdefault(entry.slug, []).append(folder)
        duplicates = {
            slug: folders for slug, folders in folders_by_slug.items() if len(folders) > 1
        }
        if duplicates:
            details = "; ".join(
                f"{slug!r} используют {folders}" for slug, folders in sorted(duplicates.items())
            )
            raise ValueError(f"groups.yaml: повторяющиеся slug: {details}")
        return self


def load_groups(path: Path) -> GroupsConfig:
    """Читает и валидирует ``groups.yaml``; любая проблема — ``ValueError`` с путём к файлу."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"groups.yaml: не удалось прочитать {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"groups.yaml: битый YAML в {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"groups.yaml: ожидался словарь верхнего уровня в {path}, "
            f"получено {type(data).__name__}"
        )
    return GroupsConfig.model_validate(data)
