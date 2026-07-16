# Tasks — fs-video-uploader

Формат работы: Claude расписывает задачи очередного шага здесь, Даниил пишет код сам, Claude проверяет результат.
Правило завершения этапа: `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто; коммит и PR — после подтверждения.

---

## Этап 1 — Каркас проекта (scaffold)

**Цель:** репозиторий собирается uv, все модули-заглушки на месте (без логики — только докстринги, пустые классы и Protocol), инструменты качества настроены, CI описан. По итогу `uv sync` работает, все проверки зелёные.

### 1.1 Git и служебные файлы

- [x] Ветка этапа `stage-1` от `main`.
- [x] `.gitignore`: `.venv/`, `.env`, `__pycache__/`, `.idea/`, кеши инструментов (`.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`), `data/`.
- [x] `.python-version` = `3.12.13` (одна версия для локали, CI и Docker).

### 1.2 pyproject.toml

- [x] `[project]`: name `fs-video-uploader`, version `0.1.0`, `requires-python = ">=3.12"`.
- [x] Зависимости добавлены **только через `uv add`**: boto3, fastapi, httpx, pydantic, pydantic-settings, pyyaml, uvicorn; dev (`uv add --dev`): pytest, ruff, mypy. `uv.lock` коммитится.
- [x] Entry point: `video-uploader = "video_uploader.main:main"`.
- [x] Build backend `uv_build`; `module-name = "video_uploader"`, `module-root = ""` — **flat layout**: пакет `video_uploader/` лежит в корне репозитория (решение 2026-07-16).
- [x] `[tool.ruff]` line-length 100, `src = ["."]`; `[tool.ruff.lint]` select E, W, F, I, N, UP, B.
- [x] `[tool.mypy]` strict, python_version 3.12; `[tool.pytest.ini_options]` testpaths `tests`.

### 1.3 Пакет `video_uploader/` — заглушки модулей

Каждый файл: докстринг (Google style) + минимальная заглушка, никакой логики.

- [x] `__init__.py` — докстринг пакета + `__version__ = "0.1.0"` (должен совпадать с pyproject).
- [x] `main.py` — `def main() -> None`, поднимает `NotImplementedError` (composition root — этап 10).
- [x] `config.py` — `class Settings(BaseSettings)` (поля — этап 2).
- [x] `pipeline.py` — класс-оркестратор (шаги — этап 8).
- [x] `domain/models.py`, `domain/events.py` — заглушки моделей и EventBus (этап 2).
- [x] `scanner/scanner.py`, `scanner/stability.py` — VideoScanner, StabilityChecker (этап 4).
- [x] `metadata/base.py` (Protocol `DateExtractor`), `metadata/filename.py`, `metadata/filestat.py` (этап 5).
- [x] `resolving/resolver.py` — GroupResolver (этап 5).
- [x] `storage/key_builder.py`, `storage/s3_gateway.py` (этап 6).
- [x] `lms/client.py` (этап 7).
- [x] `state/repository.py` — StateRepository (этап 3, SQLAlchemy 2.0).
- [x] `notifications/telegram.py` (этап 9).
- [x] `logging_setup/factory.py`, `logging_setup/loki.py`, `logging_setup/telegram.py` (этап 9).
- [x] `api/app.py` — FastAPI-заглушка (этап 10).
- [x] `__init__.py` во всех подпакетах.

### 1.4 Шаблоны конфигурации

- [x] `.env.example` — все переменные из таблицы Configuration CLAUDE.md, с комментариями и default'ами; секреты пустые. Единый регистр: `LMS_UPLOADER_TOKEN`.
- [x] `config/groups.yaml.example` — пара примерных групп со `slug` и плоским блоком `lms`.

### 1.5 Тесты каркаса

- [x] `tests/test_scaffold.py`:
  - параметризованный импорт всех 31 модуля пакета;
  - `video_uploader.__version__ == "0.1.0"`;
  - `main()` поднимает `NotImplementedError`.

### 1.6 CI

- [x] `.github/workflows/ci.yml`: триггеры PR/push в `main`; джоба: checkout → `astral-sh/setup-uv` (enable-cache) → `uv sync --frozen` → `ruff format --check .` → `ruff check .` → `mypy video_uploader` → `pytest`.

### Definition of Done

- [x] `uv sync` собирает пакет без ошибок (flat layout работает).
- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 33/33 теста.
- [x] Изменения 2026-07-16 закоммичены в `stage-1` (коммит 55906bd).
- [ ] Мердж `stage-1 → main` (PR с зелёным CI; локальный `main` пока не содержит этап 1).

---

## Этап 2 — Конфигурация и домен ← ТЕКУЩИЙ

**Цель:** сервис умеет читать и валидировать всю свою конфигурацию (env + `groups.yaml`) и имеет доменный словарь — модели и события с работающим `EventBus`. Никакого I/O, кроме чтения yaml; S3/LMS/SQLite не трогаем.

**Затрагиваемые файлы:** `video_uploader/config.py`, `video_uploader/domain/models.py`, `video_uploader/domain/events.py`, тесты `tests/test_config.py`, `tests/test_groups.py`, `tests/domain/test_models.py`, `tests/domain/test_events.py`, плюс правки `.env.example` и таблицы Configuration в CLAUDE.md (DRY_RUN).

### Решения, принятые в постановке (если не согласны — обсуждаем до кода)

1. **Единый `DRY_RUN`** (решение от 2026-07-15) — один флаг вместо `LMS_DRY_RUN`: `DRY_RUN=true` означает «шаги с внешними побочными эффектами (S3, LMS, архивация) подменяются заглушками в composition root». `LMS_DRY_RUN` удаляем из `.env.example` и таблицы Configuration, добавляем `DRY_RUN` (default `false`).
2. **Обязательные поля без default:** `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `LMS_BASE_URL`, `LMS_UPLOADER_TOKEN` — fail-fast при старте, даже в dry-run (проще и предсказуемее; в тестах задаются через `monkeypatch.setenv`). Опциональные (`None` = выключено): `SKIP_OLDER_THAN_DAYS`, `LOKI_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATE_REGEX` (пусто = default-паттерн Телемоста, сам паттерн живёт в `metadata/filename.py`, не в Settings).
3. **Секреты — `pydantic.SecretStr`** (`S3_SECRET_KEY`, `LMS_UPLOADER_TOKEN`, `TELEGRAM_BOT_TOKEN`): не светятся в repr/логах.
4. **Модели `groups.yaml` живут в `config.py`** рядом с `Settings` (это конфигурация; `GroupResolver` этапа 5 получит уже загруженный маппинг). Формат см. раздел «config/groups.yaml» CLAUDE.md.
5. **Dev-зависимость `types-pyyaml`** (stubs для mypy strict): добавить через `uv add --dev types-pyyaml` перед 2.2 — согласовано 2026-07-16.

### 2.1 `Settings` (config.py)

- [ ] Все переменные таблицы Configuration CLAUDE.md (+ `DRY_RUN`, − `LMS_DRY_RUN`) как поля `Settings(BaseSettings)`; источник — env и `.env` (`SettingsConfigDict(env_file=".env")`). ⚠️ Осталось: `LMS_UPLOADER_TOKEN` (обязательный `SecretStr`), `TELEGRAM_BOT_TOKEN` (`SecretStr | None`) — отложены Даниилом сознательно; при добавлении дополнить `_empty_str_to_none` (telegram) и тест `test_required_fields_reported`.
- [x] Типы: пути — `Path`; числа — `int` с ограничениями; флаги — `bool`; секреты — `SecretStr`.
- [x] `ALLOWED_EXTENSIONS`: строка «через запятую» → нормализованный кортеж (`NoDecode` + before-валидатор).
- [x] `TZ_NAME` валидируется через `zoneinfo`; default — `Europe/Kaliningrad` (решение Даниила, CLAUDE.md синхронизирован).
- [x] `DATE_REGEX`: компиляция + проверка именованных групп в валидаторе.
- [x] Пустые строки env для опциональных полей → `None` (before-валидатор).
- [x] Никакого глобального экземпляра `Settings`.

### 2.2 Конфиг групп (config.py)

- [x] Pydantic-модели: `GroupEntry` (`slug` + `lms`, `extra="forbid"`, `frozen=True`) и `GroupsConfig` (`groups: dict[str, GroupEntry]`, ключ — имя папки, кириллица допустима).
- [x] Валидация `slug`: `^[a-z0-9]+(-[a-z0-9]+)*$` через `Field(pattern=...)`; уникальность slug'ов — `model_validator(mode="after")` с перечислением дублей и папок в сообщении.
- [x] Валидация `lms`: обязательный, непустой, плоский `dict`; ключи `^[a-z0-9_]+$`; значения — `int` или ASCII-строка. `mode="before"`, т.к. pydantic коэрсит `bool` в `int` (True → 1) раньше `mode="after"`-валидатора — без этого `group_id: true` из yaml незаметно проходил бы как `1`.
- [x] Функция `load_groups(path) -> GroupsConfig`: `read_text` → `yaml.safe_load` → `model_validate`; файловые/yaml-ошибки обёрнуты в `ValueError` с путём к файлу, ошибки схемы — «сырой» `ValidationError` от pydantic (сам показывает точный путь до поля).
- [x] Dev-зависимость `types-pyyaml` добавлена (`uv add --dev`).

### 2.3 Доменные модели (domain/models.py)

Все — frozen `dataclass(slots=True)`, только stdlib-типы + `pathlib`/`datetime`.

- [x] `VideoFile` — `path`, `group_folder`, `size_bytes`, `mtime` (без slug и sha256 — появляются позже).
- [x] `LessonMeta` — `group_slug`, `lms: dict[str, int | str]`, `recorded_at: datetime` (tz-aware по контракту, докстрингом), `date_from_fallback: bool`.
- [x] `UploadResult` — `s3_key`, `manifest_key`, `size_bytes`, `sha256`, `uploaded_at: datetime` (UTC по контракту).
- [x] Состав полей минимален — покрывает ровно то, что нужно для ключа S3, манифеста и REST-payload из CLAUDE.md; лишнего нет.
- [x] `tests/domain/test_models.py` (12 тестов): по 4 на класс — доступность полей, `FrozenInstanceError` при попытке изменить, отсутствие `__dict__` (slots), равенство по значению.

### 2.4 События и EventBus (domain/events.py)

- [x] Семь событий — frozen `dataclass(slots=True)`: `VideoDiscovered(path)`, `VideoUploaded(path, s3_key)`, `VideoRegistered(path, s3_key)`, `VideoArchived(path, archived_path)`, `VideoFailed(path, error, attempts)`, `GroupUnmapped(group_folder)`, `DateFallback(path)`.
- [x] `EventBus.subscribe(event_type, handler)` / `publish(event)`; синхронный, без потоков; несколько подписчиков на тип; подписчики других типов не вызываются.
- [x] Изоляция подписчиков: `try/except Exception` + `logger.exception` (логгер `video_uploader.domain.events`); ошибка одного хендлера не мешает ни остальным, ни publish.
- [x] Без глобального синглтона — только конструктор `EventBus()`, экземпляр создаётся в composition root.
- [x] Типизация без утечки `Any`: публичные `subscribe`/`publish` типизированы через `TypeVar E` — `subscribe(VideoFailed, handler)` требует `handler: Callable[[VideoFailed], None]`, mypy это проверяет на месте вызова. Внутреннее хранилище (`dict[type[Any], list[Callable[[Any], None]]]`) неизбежно гетерогенно (в одном dict соседствуют хендлеры на разные типы событий) — `Any`/`cast` изолированы в `subscribe` одной строкой, наружу не просачиваются.
- [x] `tests/domain/test_events.py` (14 тестов): доставка одному/нескольким подписчикам, изоляция по типу, publish без подписчиков, ошибка в хендлере не блокирует остальных и не долетает до publisher'а (`caplog`), поля всех 7 событий.

### 2.5 Сопутствующие правки

- [x] `.env.example`: `LMS_DRY_RUN` → `DRY_RUN`; `TZ_NAME=Europe/Kaliningrad`; `ALLOWED_EXTENSIONS=.webm,.mp4,.mkv`.
- [x] CLAUDE.md, таблица Configuration: та же замена + новые default'ы TZ/расширений; формулировка dry-run в разделе LMS REST.
- [x] `tests/test_scaffold.py`: правок не потребовалось (Settings не инстанцируется).

### 2.6 Тесты этапа

- [x] `tests/test_config.py`: 22 теста — дефолты, env-переопределения, парсинг расширений, обязательные поля, невалидные TZ/regex/диапазоны, пустые env-строки, маскирование секретов.
- [x] `tests/test_groups.py` (18 тестов, файлы через `tmp_path`): валидный/мультигрупповой yaml; плохой slug (5 вариантов) / дубль slug; пустой `lms` / отсутствующий `lms` / вложенный `lms` / не-ASCII значение / недопустимый ключ / `bool` вместо `int`; лишнее поле (`extra="forbid"`); отсутствующий файл / битый yaml / не-словарь верхнего уровня.
- [x] `tests/domain/test_models.py` (12 тестов): frozen (`FrozenInstanceError`), `slots` (нет `__dict__`), равенство по значению — см. 2.3.
- [x] `tests/domain/test_events.py` (14 тестов): доставка, изоляция по типу, изоляция ошибок (`caplog`), поля событий — см. 2.4.
- [x] Сеть / реальные пути вне `tmp_path` в тестах не использовались (проверено чтением всех тестовых файлов этапа).

### Definition of Done (этап 2)

- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 97/97 тестов.
- [x] Ревью Claude пройдено по ходу (2.1–2.4), один найденный баг (`bool`→`int` в `lms`) закрыт.
- [ ] Коммит в ветку `stage-2` (от `main` после мерджа этапа 1), PR — после подтверждения. **Блокер:** `main` пока не содержит этап 1 (см. DoD этапа 1) — сначала нужно смержить `stage-1`.
