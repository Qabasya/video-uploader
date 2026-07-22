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
- [x] Мердж в `main` — состоялся 2026-07-17 (PR #4 `stage-10 → main`, коммит `0048058`), см. итог всего проекта в конце файла. Отдельного PR только под этап 1 не было — все этапы 1–10 попали в `main` одним PR.

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

- [ ] Все переменные таблицы Configuration CLAUDE.md (+ `DRY_RUN`, − `LMS_DRY_RUN`) как поля `Settings(BaseSettings)`; источник — env и `.env` (`SettingsConfigDict(env_file=".env")`). ⚠️ Осталось: `TELEGRAM_BOT_TOKEN` (`SecretStr | None`) — отложен Даниилом сознательно, дополнить `_empty_str_to_none` и `test_required_fields_reported` при добавлении. `LMS_UPLOADER_TOKEN` закрыт этапом 8.1 — контракт LMS сменился на HMAC (`LMS_HMAC_SECRET`, `SecretStr`, обязательный), переименовывать в коде было нечего, добавлен сразу под новым именем.
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
- [x] Закоммичено в ветку `stage-2` (коммит 245ad38). Ветка ответвлена от `stage-1` (не от `main` — `main` пока не содержит этап 1, PR туда ещё не открыт). Осознанное отступление от исходного git-протокола: продолжаем последовательно на `stage-2`, мердж `stage-1`/`stage-2` в `main` — отдельным шагом позже.

---

## Этап 3 — Реестр SQLite (StateRepository) ← ТЕКУЩИЙ

**Цель:** `StateRepository` — единственная точка доступа к `state.db`: заводит запись при обнаружении файла, проводит её через все статусы пайплайна, отдаёт кэшированный `sha256` по `(path, size, mtime)`, не даёт пайплайну коснуться SQLAlchemy напрямую. Пайплайна и самих S3/LMS-вызовов на этом этапе ещё нет — только репозиторий и его тесты.

**Затрагиваемые файлы:** `video_uploader/state/repository.py` (+ модели таблицы в этом же модуле — Repository-пакет маленький, отдельный `models.py` избыточен), `tests/state/test_repository.py`.

### Решения, принятые в постановке (если не согласны — обсуждаем до кода)

1. **SQLAlchemy 2.0 Core+ORM, `Mapped`/`mapped_column` (2.0-style), не legacy `declarative_base()`.** Движок — `create_engine(f"sqlite:///{data_dir}/state.db")`; `PRAGMA journal_mode=WAL` выставляется через `event.listens_for(engine, "connect")` сразу после коннекта (CLAUDE.md требует WAL).
2. **Одна таблица `files`**, поля — ровно по списку из CLAUDE.md (раздел State): `id, path, group_name, size_bytes, mtime, sha256, status, s3_key, archived_path, attempts, last_error, created_at, updated_at`. Новых полей не добавляем без вашего запроса.
3. **`status` — `str` с проверкой допустимых значений на уровне репозитория**, не SQLAlchemy `Enum` — проще мигрировать список статусов в будущем, а переходы и так идут только через явные методы репозитория (CLAUDE.md: «никаких сырых UPDATE из пайплайна»).
4. **Время — `created_at`/`updated_at` в UTC ISO 8601, `str`**, не `DateTime`-колонка с tzinfo-плясками SQLite (SQLite не хранит tz нативно). Присваивается в Python (`datetime.now(UTC).isoformat()`), не `server_default`.
5. **Сессии — короткоживущие, по одной на вызов метода** (`with Session(self._engine) as session:` внутри каждого публичного метода), не одна долгоживущая сессия на весь репозиторий — так проще про потокобезопасность между циклами сканирования.
6. **Ключ кэша sha256 — составной `(path, size_bytes, mtime)`**, не просто `path`: ровно так описано в CLAUDE.md («кешируется в реестре по `(path, size, mtime)`») — если файл на шаре подменили (тот же путь, другой размер/mtime), старый хэш не переиспользуется.

### 3.1 Таблица и модель

- [x] `class Base(DeclarativeBase)` и `class FileRecord(Base)` с `__tablename__ = "files"`, все поля из CLAUDE.md через `Mapped[...] = mapped_column(...)`.
- [x] `id` — `Mapped[int] = mapped_column(primary_key=True)` (autoincrement).
- [x] `path` — `Mapped[str] = mapped_column(unique=True)`.
- [x] `sha256`, `s3_key`, `archived_path`, `last_error` — `Mapped[str | None]`, default `None`.
- [x] `attempts` — `Mapped[int] = mapped_column(default=0)`.
- [x] `Index("ix_files_path_size_mtime", "path", "size_bytes", "mtime")` в `__table_args__` — под `get_cached_sha256`.

### 3.2 `StateRepository` — создание и инициализация

- [x] Конструктор принимает `Path` к файлу БД, `create_engine`, `event.listen(engine, "connect", _enable_wal)` (не `listens_for` — функциональная форма читается прямее без декоратора), `Base.metadata.create_all(engine)`.
- [x] Логгер `video_uploader.state.repository` (через `__name__`) — пока не используется внутри методов (нечего логировать сверх того, что делает сам код), объявлен для будущих этапов.

### 3.3 Методы репозитория — переходы статусов

- [x] `discover(path, group_name, size_bytes, mtime) -> int`.
- [x] `get_cached_sha256(path, size_bytes, mtime) -> str | None`.
- [x] `set_sha256(file_id, sha256) -> None`.
- [x] `mark_uploading` / `mark_uploaded(s3_key)` / `mark_registered` / `mark_archived(archived_path)`.
- [x] `mark_failed(file_id, error) -> None` — инкремент `attempts`, запись `last_error`; повторный вызов из `failed` разрешён явным правилом `"failed": {"uploading", "failed"}` (ретрай пишет `last_error` дальше).
- [x] `mark_skipped(file_id, status: Literal["skipped_old", "skipped_unmapped"]) -> None`.
- [x] Недопустимый переход → `InvalidTransitionError` (свой класс исключения); таблица переходов — `_ALLOWED_TRANSITIONS: dict[str, frozenset[str]]`, единая точка правды, без разбросанных `if`.
- [x] `get_by_id` / `get_by_sha256` — возвращают `FileState | None` (см. 3.4), не `FileRecord`.
- [x] `count_by_status() -> dict[str, int]`, `get_recent(limit: int) -> list[FileState]`.

### 3.4 Возврат данных наружу

- [x] Выбран вариант «явный маппинг в свой frozen dataclass»: `FileState` (frozen, slots) в `state/repository.py` — копия полей `FileRecord`, но detached от сессии по построению. `_to_state()` — единственная точка конвертации, используется во всех геттерах (`get_by_id`, `get_by_sha256`, `get_recent`) одинаково.

### 3.5 Тесты (`tests/state/test_repository.py`, 18 тестов)

- [x] `discover`: статус `discovered`, идемпотентность повторного вызова того же пути (`get_recent` не плодит вторую запись).
- [x] `get_cached_sha256`: `None` до `set_sha256`, значение после, промах при изменившемся `size` или `mtime`.
- [x] Полная happy-path цепочка `discovered → uploading → uploaded → registered → archived` с проверкой `s3_key`/`archived_path`/`updated_at`.
- [x] `mark_failed`: инкремент `attempts`, `last_error`, повторный вызов копит `attempts` дальше.
- [x] `mark_skipped` для обоих значений.
- [x] Недопустимые переходы: `discovered → registered` (минуя upload) и переход из терминального `archived` — оба поднимают `InvalidTransitionError`.
- [x] `get_by_sha256`: находит `registered`-запись, `None` для незнакомого хэша.
- [x] WAL: отдельный тест открывает файл БД напрямую через `sqlite3.connect` и проверяет `PRAGMA journal_mode == "wal"`.
- [x] Персистентность: два экземпляра `StateRepository` на одном файле — второй видит данные первого.
- [x] Заодно — `count_by_status` и `get_recent(limit=...)` (не входили в исходный список, добавлены как публичные методы 3.3).

### Definition of Done (этап 3)

- [x] `uv add sqlalchemy` выполнен — `sqlalchemy==2.0.51`.
- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 115/115 тестов.
- [x] Ревью Claude пройдено по ходу реализации (само+тесты писал Claude по вашей просьбе, без отдельного цикла правок).
- [x] Коммит — теперь всегда на пользователе; Claude коммиты не предлагает и не выполняет (решение 2026-07-16).

---

## Этап 4 — Сканер и проверка стабильности ← ТЕКУЩИЙ

**Цель:** `VideoScanner` обходит `VIDEO_ROOT` и отдаёт список кандидатов (`VideoFile`) по правилам из CLAUDE.md (глубина 1, расширения, скрытые/временные имена); `StabilityChecker` отдельно решает, дописан ли конкретный файл. Оба — независимые классы без знания друг о друге и без знания про `groups.yaml`, реестр, S3 — это работа следующих этапов/pipeline (этап 8).

**Затрагиваемые файлы:** `video_uploader/scanner/scanner.py`, `video_uploader/scanner/stability.py`, `tests/scanner/test_scanner.py`, `tests/scanner/test_stability.py`.

### Решения, принятые в постановке (если не согласны — обсуждаем до кода)

1. **Зависимости — через конструктор, не через `Settings`.** `VideoScanner(video_root: Path, allowed_extensions: tuple[str, ...])`, `StabilityChecker(stability_minutes: int)` — узкие интерфейсы (SOLID-I): сканер не обязан знать все 20+ полей `Settings`, только то, что реально использует. Собирает их из `Settings` composition root на этапе 10.
2. **`StabilityChecker` не хранит снимки между вызовами.** «size и mtime не менялись ≥ `STABILITY_MINUTES`» эквивалентно «с последнего изменения (`mtime`) прошло ≥ `STABILITY_MINUTES`» — mtime и так обновляется при любой записи в файл, отдельно хранить прошлый snapshot и сравнивать через цикл не нужно. Один `stat()` на текущий момент, без внешнего состояния — так проще и это ровно то же самое по смыслу.
3. **Скоуп размежёван явно:**
   - `SKIP_OLDER_THAN_DAYS` — **не** здесь. Это решение «пропустить и пометить `skipped_old` в реестре», а не «не считать кандидатом» — работа pipeline (этап 8) через `StateRepository.mark_skipped`.
   - Сопоставление `group_folder → groups.yaml` (skipped_unmapped) — тоже не здесь, это `resolving/resolver.py` (этап 5).
   - `StabilityChecker` только отвечает bool; что делать с нестабильным файлом (ждать следующий цикл, не считать это ошибкой) — решает pipeline.
4. **Архивная подпапка `_uploaded` игнорируется автоматически**, без явной проверки имени на `ARCHIVE_SUBDIR`: раз сканируется только глубина 1 (файлы прямо внутри папки группы), а `_uploaded` — это директория, она просто не пройдёт фильтр «это файл, не каталог» и не будет рекурсивно обойдена. Нет нужды сравнивать имя с `ARCHIVE_SUBDIR`.
5. **Изоляция ошибок на уровне папки группы.** Если `iterdir()` одной группы падает (`OSError` — например временная проблема с правами/сетью на SMB), это не должно останавливать скан остальных групп: логируем `WARNING` и продолжаем со следующей папкой. Это распространение принципа «ошибка одного файла не останавливает сервис» на уровень папки — если не согласны, что это нужно уже на этом этапе, скажите, уберу.
6. **Порядок результата — по `mtime` по возрастанию** (`scan()` сортирует перед возвратом). CLAUDE.md требует порядок «от старых к новым (по `recorded_at`/mtime)»; `recorded_at` на этапе сканирования ещё не существует (это результат `metadata` этапа 5), поэтому сканер — точка, где естественно сортировать по доступному на этот момент `mtime`.

### 4.1 `VideoScanner` (scanner/scanner.py)

```python
class VideoScanner:
    """Обход VIDEO_ROOT/<группа>/*: глубина 1, фильтр расширений и служебных имён."""

    def __init__(self, video_root: Path, allowed_extensions: tuple[str, ...]) -> None:
        self._video_root = video_root
        self._allowed_extensions = allowed_extensions

    def scan(self) -> list[VideoFile]:
        """Возвращает кандидатов из всех папок групп, отсортированных по mtime (старые первыми)."""
```

- [x] `scan()` перебирает прямые подпапки `VIDEO_ROOT` (`is_dir()`); имя папки как есть → `VideoFile.group_folder`.
- [x] Внутри группы — только файлы (`is_file()`), без рекурсии — `_uploaded` отсекается автоматически.
- [x] Фильтр по имени: `.`/`~`-префикс.
- [x] Фильтр по расширению регистронезависимо (`path.suffix.lower() in allowed_extensions`).
- [x] Один `path.stat()` на файл → `VideoFile`.
- [x] Обход одной группы — `try/except OSError` → `logger.warning`, переход к следующей; `video_root.iterdir()` верхнего уровня не перехватывается (осознанно: недоступный `VIDEO_ROOT` — не «одна группа», должен упасть при старте, а не тихо дать пустой список).
- [x] `sorted(..., key=lambda video_file: video_file.mtime)`.

### 4.2 `StabilityChecker` (scanner/stability.py)

```python
class StabilityChecker:
    """Файл считается стабильным, если с последней записи прошло >= stability_minutes."""

    def __init__(self, stability_minutes: int) -> None:
        self._threshold = timedelta(minutes=stability_minutes)

    def is_stable(self, path: Path) -> bool:
        """True, если mtime не моложе порога и файл открывается на чтение."""
```

- [x] `path.stat()` → `mtime`; порог — `datetime.now(UTC) - modified_at < threshold` → `False` (включительно на границе, `<` а не `<=`).
- [x] Открываемость на чтение — `with path.open("rb"): pass` в `try/except OSError` → `False`.
- [x] `OSError` на `stat()` (файл исчез между scan и проверкой) → `False`, без исключения наружу.
- [x] Никакого `MAX_ATTEMPTS`/событий — вне зоны ответственности класса.

### 4.3 Тесты

`tests/scanner/test_scanner.py` (реальные временные каталоги через `tmp_path`, никаких реальных путей):

- [x] `tests/scanner/test_scanner.py` (14 тестов): базовый кейс (две группы), заполнение `size_bytes`/`mtime`, неподходящее расширение, регистронезависимость расширения, `.`/`~`-префиксы, файл прямо в `VIDEO_ROOT`, вложенный `_uploaded`, пустая группа, сортировка по `mtime` (через `os.utime`), изоляция ошибок через `monkeypatch.setattr(Path, "iterdir", ...)` + проверка `caplog`.

`tests/scanner/test_stability.py`:

- [x] `tests/scanner/test_stability.py` (6 тестов): свежий файл → `False`; состаренный (`os.utime`) → `True`; ровно на границе порога → `True` (`<` включительно); несуществующий путь → `False`; неоткрываемый файл (замокан `Path.open`) → `False`, даже если `mtime` достаточно старый.

### Definition of Done (этап 4)

- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 131/131 тестов.
- [x] Ревью Claude пройдено (код и тесты написаны Claude по вашей просьбе, разошедшихся с постановкой мест нет).
- [ ] Коммит — на вашей стороне.

---

## Этап 5 — Метаданные и резолвинг группы

**Цель:** две реализации `DateExtractor` (Protocol уже есть с этапа 1 — `metadata/base.py`, менять не нужно) и `GroupResolver`, который превращает сырое имя папки в `slug` + блок `lms`. Оба независимы: `metadata/*` ничего не знает про группы, `resolving/resolver.py` ничего не знает про даты. Склейка в цепочку `FilenameDateExtractor → FileStatDateExtractor` с публикацией `DateFallback` и рейт-лимитом `GroupUnmapped` — **не сюда**, это работа оркестратора `pipeline.py` на этапе 8 (у него есть понятие «цикл сканирования» и доступ к `EventBus`, а у стратегий и резолвера — нет).

**Затрагиваемые файлы:** `video_uploader/metadata/filename.py`, `video_uploader/metadata/filestat.py`, `video_uploader/resolving/resolver.py`, `tests/metadata/test_filename.py`, `tests/metadata/test_filestat.py`, `tests/resolving/test_resolver.py`.

### Решения, принятые в постановке (если не согласны — обсуждаем до кода)

1. **`tz_name` — параметр конструктора у обеих стратегий**, не аргумент `extract()`: сигнатура `DateExtractor.extract(path) -> datetime | None` уже зафиксирована Protocol'ом с этапа 1 и содержит только `path`. Часовой пояс не меняется между вызовами в рамках одного запуска сервиса — конструктор самое место.
2. **Default-паттерн живёт в `metadata/filename.py`**, не в `Settings`: `Settings.date_regex` как было `str | None = None` — «не задано» просто означает «использовать встроенный default». Дублировать регэксп-строку в двух местах незачем.
3. **`FilenameDateExtractor.extract` возвращает `None` на любую невозможность** — нет совпадения по regex, `ValueError` при сборке `datetime` (месяц > 12 и т.п.). Это философия Protocol: «стратегия неприменима» = `None`, решение «что дальше» — у вызывающего (цепочка в pipeline).
4. **Двузначный год → `20ГГ`, но не только двузначный**: беру длину захваченной строки года — если ровно 2 символа, прибавляю 2000; если больше (кастомный `DATE_REGEX` с `\d{4}`), использую как есть. Дефолтный паттерн Телемоста всегда двузначный, но `DATE_REGEX` можно переопределить в `.env`, и жёстко хардкодить «всегда +2000» было бы неверно для 4-значного варианта.
5. **`GroupResolver` работает с уже загруженным `GroupsConfig`** (результат `config.load_groups()` из этапа 2.2, передаётся в конструктор) — сам файл не читает, повторной валидации не делает: это забота composition root на этапе 10.
6. **`GroupResolver.resolve()` возвращает `GroupEntry | None`**, не новый локальный тип: `GroupEntry` (из `config.py`, этап 2.2) уже ровно то, что нужно — `slug` + `lms`, frozen, провалидирован при загрузке. Заводить ещё один датакласс с теми же двумя полями — лишняя абстракция без пользы (CLAUDE.md прямо просит не плодить слои без запроса). Если хотите на этом этапе завести отдельный доменный тип вместо переиспользования `GroupEntry` — скажите, поменяю.
7. **Сопоставление имени папки — точное, регистрозависимое**, без нормализации: CLAUDE.md прямо говорит «ключ — точное имя подпапки». `"кегэ-1" != "КЕГЭ-1"` — это два разных (не)совпадения, не приводим к одному регистру.
8. **`GroupResolver` не публикует события и не знает про `EventBus`**: «не чаще раза за цикл на папку» для `GroupUnmapped` — это состояние на уровне цикла сканирования, которого у резолвера нет и не должно быть (SOLID-I: узкий интерфейс). Резолвер просто отвечает `None`; троттлинг и публикация события — pipeline, этап 8.

### 5.1 `FilenameDateExtractor` (metadata/filename.py)

```python
_DEFAULT_PATTERN = (
    r"(?P<day>\d{2})_(?P<month>\d{2})_(?P<year>\d{2})"
    r"_(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})"
)


class FilenameDateExtractor:
    """Дата из блока ДД_ММ_ГГ_ЧЧ_ММ_СС (или кастомного DATE_REGEX) в имени файла."""

    def __init__(self, tz_name: str, pattern: str | None = None) -> None:
        self._tz = ZoneInfo(tz_name)
        self._pattern = re.compile(pattern or _DEFAULT_PATTERN)

    def extract(self, path: Path) -> datetime | None:
        """Ищет блок даты в имени файла (не привязан к началу строки)."""
```

- [x] `pattern` компилируется один раз в конструкторе.
- [x] `extract`: `self._pattern.search(path.name)`.
- [x] Нет совпадения → `None`.
- [x] `match.groupdict()` → `int`-поля; год — `_normalize_year` (решение 4, вынесено отдельным `@staticmethod` для явности).
- [x] Сборка `datetime(...)` в `try/except ValueError` → `None`.
- [x] Результат — tz-aware `datetime` в `tz_name`.

### 5.2 `FileStatDateExtractor` (metadata/filestat.py)

```python
class FileStatDateExtractor:
    """Fallback: дата из mtime файла, локализованная в tz_name."""

    def __init__(self, tz_name: str) -> None:
        self._tz = ZoneInfo(tz_name)

    def extract(self, path: Path) -> datetime | None:
        """mtime — абсолютный момент; локализация в tz_name не меняет сам момент."""
```

- [x] `path.stat().st_mtime` в `try/except OSError` → `None`.
- [x] `datetime.fromtimestamp(mtime, tz=self._tz)` — конвертация момента, не наивная дата с приклеенным tzinfo.
- [x] Практически не возвращает `None` в норме — только гонка с исчезновением файла.

### 5.3 `GroupResolver` (resolving/resolver.py)

```python
class GroupResolver:
    """group_folder → GroupEntry (slug + lms) по уже загруженному groups.yaml."""

    def __init__(self, groups_config: GroupsConfig) -> None:
        self._groups = groups_config.groups

    def resolve(self, group_folder: str) -> GroupEntry | None:
        """Точное совпадение по имени папки; None — группа не описана в groups.yaml."""
        return self._groups.get(group_folder)
```

- [x] Импорт `GroupEntry`, `GroupsConfig` из `video_uploader.config`.
- [x] Ровно один метод, без побочных эффектов, без `EventBus`.

### 5.4 Тесты

- [x] `tests/metadata/test_filename.py` (11 тестов): реальное имя из CLAUDE.md, двузначный год, «префикс не важен» (`.search`), невалидный месяц → `None`, имя без блока даты → `None`, tz-aware результат + конкретный offset для Калининграда, кастомный паттерн с 4-значным годом (без `+2000`) + проверка, что default-паттерн больше не матчит.
- [x] `tests/metadata/test_filestat.py` (4 теста): дата соответствует `mtime`, несуществующий путь → `None`, один и тот же момент в двух разных `tz_name` — разный `.hour`, но одинаковый `.timestamp()`.
- [x] `tests/resolving/test_resolver.py` (3 теста): известная папка резолвится, неизвестная → `None`, разный регистр кириллицы → `None` (решение 7).

### Definition of Done (этап 5)

- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 146/146 тестов.
- [x] Ревью Claude пройдено (код и тесты написаны Claude по вашей просьбе; отклонений от постановки нет).
- [ ] Коммит — на вашей стороне.

---

## Этап 6 — Хранилище S3 (KeyBuilder + S3Gateway) ← ТЕКУЩИЙ

**Цель:** `KeyBuilder` — чистые функции построения ключей (видео + манифест) без единого обращения к сети; `S3Gateway` — тонкий adapter над boto3 (upload видео, put манифеста, verify по `head_object`). Хэширование (`sha256`) — **не сюда**: как явно записано в памяти проекта, это работа `pipeline.py` (этап 8), у него есть доступ к `StateRepository`-кэшу по `(path, size, mtime)`. Сборка манифеста и `x-amz-meta-*`-словаря из `LessonMeta`/`UploadResult` (домена) — тоже этап 8: `S3Gateway` не должен знать про группы/`lms` (CLAUDE.md, SOLID-S), он принимает уже готовые примитивы (ключ-строку, plain-словарь метаданных, JSON-сериализуемый словарь манифеста).

**Затрагиваемые файлы:** `video_uploader/storage/key_builder.py`, `video_uploader/storage/s3_gateway.py`, `pyproject.toml` (mypy override, см. решение 1), `tests/storage/test_key_builder.py`, `tests/storage/test_s3_gateway.py`.

### Решения, принятые в постановке (обсуждаем, если не согласны)

1. ~~boto3 без типов: mypy-override~~ — **решено: вариант (а), `boto3-stubs[s3]`**. Установлено (`uv add --dev "boto3-stubs[s3]"`): `boto3-stubs==1.43.49`, `botocore-stubs==1.43.14`, `mypy-boto3-s3==1.43.31`, `types-s3transfer==0.16.0`, `types-awscrt==0.34.1`. Пункт 6.3 (mypy override) больше не нужен — `boto3.client("s3", ...)` теперь типизируется настоящим `S3Client` через overload по строковому литералу `"s3"`; для этого важно **не терять литерал** — писать `boto3.client("s3", ...)` напрямую (не через промежуточную переменную `service_name: str = "s3"`), иначе overload не сработает и тип снова расплывётся до `Any`.
2. **`KeyBuilder` принимает примитивы, не `LessonMeta`**: `build_video_key(group_slug, recorded_at, sha256, ext)` — так же, как `VideoScanner`/`StabilityChecker` на этапе 4 брали примитивы через конструктор, а не целиком `Settings`. `storage/` не обязан импортировать `domain/` ради четырёх значений.
3. **`KeyBuilder` сам проверяет charset ключа** (`[a-z0-9./_-]`) после сборки и падает `ValueError`, если что-то не так — это прямое требование Strict Rules CLAUDE.md («кириллица и пробелы в ключах S3 запрещены»), а не просто доверие тому, что `group_slug` уже провалидирован на входе в `groups.yaml` (защита от будущих ошибок, а не дублирование чужой валидации).
4. **Дата в ключе — `recorded_at.strftime(...)` без конвертации таймзоны**: `LessonMeta.recorded_at` уже tz-aware в `TZ_NAME`, ключ должен содержать те же «настенные» цифры, что и в примере CLAUDE.md (`16-04` совпадает с `16:04:45` в манифесте) — никакого приведения к UTC для этой части.
5. **`S3Gateway` не ловит исключения boto3** — методы просто вызывают `self._client.upload_file(...)`/`put_object(...)`/`head_object(...)` и дают ошибке всплыть. Изоляция ошибок по файлу — обязанность `pipeline.py` (Processing Rules: «обработка каждого файла в try/except»); дублировать `try/except` внутри тонкого adapter'а незачем.
6. **`S3Gateway` валидирует ASCII в `metadata`-словаре перед вызовом boto3** — это тоже прямой Strict Rule («кириллица и пробелы... в `x-amz-meta-*` запрещены»), а не только про ключи. Без этой проверки ошибка всплыла бы поздно и невнятно — где-то в недрах `botocore`/`urllib3` при кодировании HTTP-заголовка.
7. **Ключи `Metadata=` без префикса `x-amz-meta-`** — это нюанс самого boto3: параметр `ExtraArgs={"Metadata": {...}}` в `upload_file` автоматически добавляет префикс `x-amz-meta-` к каждому ключу словаря. То есть вызывающий код (этап 8) должен передавать `{"group-slug": "kege-1", "lms-group-id": "3"}`, **без** ручного `"x-amz-meta-"` — если приписать вручную, получится задвоение.
8. **Неизвестное расширение → `Content-Type: application/octet-stream`**, не исключение: `ALLOWED_EXTENSIONS` конфигурируем и по умолчанию шире таблицы `ContentType` из CLAUDE.md (`.webm/.mp4/.mkv`) — если админ расширит список в `.env` каким-то ещё форматом, загрузка не должна падать, только тип станет обобщённым.
9. **Тесты — без реальной сети и без новых зависимостей (`moto` не добавляем)**: `boto3.client` подменяется через `monkeypatch` на самодельный фейковый клиент, который просто запоминает аргументы вызовов. `scripts/smoke_s3.py` (ручная проверка против реального Beget) — это этап 11, не сюда.

### 6.1 `KeyBuilder` (storage/key_builder.py)

```python
_ALLOWED_KEY_CHARS = re.compile(r"[a-z0-9./_-]+")


class KeyBuilder:
    """Сборка ключей видео и манифеста по соглашению — единственный источник."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def build_video_key(
        self, group_slug: str, recorded_at: datetime, sha256: str, ext: str
    ) -> str:
        """{prefix}/{group_slug}/{yyyy}/{mm}/{yyyy-mm-dd}_{hh-mm}_{sha8}{ext}"""

    def build_manifest_key(self, video_key: str) -> str:
        """{video_key}.json"""
```

- [x] `build_video_key`: строка по формату из CLAUDE.md, `ext.lower()`, `sha256[:8]`, `_validate` перед возвратом.
- [x] `build_manifest_key`: `f"{video_key}.json"`, без повторной валидации.
- [x] `_validate(key)` — `@staticmethod`, `_ALLOWED_KEY_CHARS.fullmatch(key)` → `ValueError` с ключом в сообщении.
- [x] `prefix` — параметр конструктора.

### 6.2 `S3Gateway` (storage/s3_gateway.py)

```python
_MULTIPART_THRESHOLD_BYTES = 64 * 1024 * 1024
_CONTENT_TYPES = {".webm": "video/webm", ".mp4": "video/mp4", ".mkv": "video/x-matroska"}


class S3Gateway:
    """Шлюз S3 Beget: path-style addressing, multipart upload, put манифеста, verify."""

    def __init__(
        self, *, endpoint_url: str, region: str, bucket: str, access_key: str, secret_key: str
    ) -> None:
        """Собирает boto3-клиент с addressing_style="path" и TransferConfig на 64 MiB."""

    def upload_video(self, path: Path, key: str, metadata: Mapping[str, str]) -> None:
        """Multipart upload; ContentType по расширению key; ASCII-валидация metadata."""

    def put_manifest(self, key: str, manifest: dict[str, object]) -> None:
        """put_object с JSON-телом (UTF-8, кириллица в значениях — ОК) и своим ContentType."""

    def verify(self, key: str, expected_size: int) -> bool:
        """head_object -> ContentLength == expected_size (ETag не используется)."""
```

- [x] Конструктор: `boto3.client("s3", ...)` с литералом `"s3"` (важно для overload boto3-stubs), `Config(s3={"addressing_style": "path"})`, `TransferConfig` на 64 MiB.
- [x] `access_key`/`secret_key` — обычные `str`, gateway про `SecretStr`/pydantic не знает.
- [x] `upload_video`: `_validate_ascii_metadata` → `content_type` по расширению **ключа** (не исходного пути) → `upload_file(..., ExtraArgs={"ContentType": ..., "Metadata": dict(metadata)})`.
- [x] `put_manifest`: `json.dumps(..., ensure_ascii=False, indent=2)` → `put_object(...)`.
- [x] `verify`: `head_object` → `int(response["ContentLength"]) == expected_size`.
- [x] `_validate_ascii_metadata` — модульная функция, не метод.
- [x] Логгер `video_uploader.storage.s3_gateway` заведён; по решению 5 сами методы ничего не логируют — исключения boto3 не перехватываются.

### 6.3 pyproject.toml

- [x] `boto3-stubs[s3]` добавлен через `uv add --dev` (решение 1) — `boto3-stubs==1.43.49`, `botocore-stubs==1.43.14`, `mypy-boto3-s3==1.43.31`.

### 6.4 Тесты

- [x] `tests/storage/test_key_builder.py` (7 тестов): точное совпадение с примером CLAUDE.md, регистр расширения, кастомный prefix, защитный барьер на кириллице в `group_slug`, `build_manifest_key`.
- [x] `tests/storage/test_s3_gateway.py` (11 тестов, фейковый boto3-клиент через `monkeypatch.setattr(boto3, "client", ...)` — патчим сам модуль `boto3`, не атрибут `s3_gateway`-модуля, иначе mypy strict ругается на implicit reexport): `upload_file` с правильными `Bucket`/`Key`/`Filename`, `ContentType` по всем 3 известным расширениям + fallback на неизвестном, `Metadata` без ручного префикса `x-amz-meta-`, не-ASCII metadata → `ValueError` до вызова boto3, `put_manifest` — валидный JSON + кириллица без экранирования, `verify` — совпадение/несовпадение размера, конструктор — `path`-style addressing действительно передан.

### Definition of Done (этап 6)

- [x] Решение по пункту 1 подтверждено вами — `boto3-stubs[s3]`.
- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 163/163 тестов.
- [x] Ревью Claude пройдено (код и тесты написаны Claude по вашей просьбе).
- [ ] Коммит — на вашей стороне.

---

## Этап 7 — LMS REST-клиент (LmsClient) ← ТЕКУЩИЙ

**Цель:** `LmsClient` — тонкий adapter над `httpx` для `POST /wp-json/fs-lms/v1/videos`: один HTTP-запрос за вызов, интерпретация ответа в понятную для пайплайна классификацию (успех / повторить позже / отвергнуто окончательно). Ретраи «в следующих циклах», сборка payload из доменных моделей и `DRY_RUN` — не сюда, см. решения 1–3.

**Затрагиваемые файлы:** `video_uploader/lms/client.py`, `tests/lms/test_client.py`.

**Внешняя зависимость, не блокирующая этот этап:** `Settings.lms_uploader_token` вы сознательно не добавили на этапе 2.1 (отложенный пункт). `LmsClient` от этого не зависит — конструктор принимает обычный `token: str`, а откуда он берётся (когда добавите поле в `Settings`) — забота composition root на этапе 10.

### Решения, принятые в постановке (обсуждаем, если не согласны)

1. **Ретраи — не здесь.** «5xx и сетевые ошибки → ретраи с экспоненциальным backoff в следующих циклах» — это ретраи *между циклами сканирования* через `StateRepository`/`MAX_ATTEMPTS`, то есть работа `pipeline.py` (этап 8), не цикл повторов внутри одного вызова `register()`. `LmsClient` делает ровно одну попытку HTTP-запроса за вызов.
2. **Классификация ответа — через типизированные исключения, не через возвращаемый код/enum**: успех — тихий `return`; 5xx и сетевые ошибки (`httpx.HTTPError`) — `LmsRetryableError`; прочие 4xx — `LmsRejectedError` (оба — подклассы `LmsRegistrationError`). Так `pipeline.py` на этапе 8 сможет `except LmsRetryableError` (ретраить, пока `attempts < MAX_ATTEMPTS`) и `except LmsRejectedError` (сразу `failed`, без ретраев — именно это отдельно требует CLAUDE.md для «прочих 4xx») раздельно, без парсинга кода ответа заново.
3. **`register()` принимает уже готовый payload-словарь** (`dict[str, object]`), не отдельные `LessonMeta`/`UploadResult`/`sha256` аргументы — тот же принцип, что и у `S3Gateway.put_manifest()` на этапе 6: клиент не знает про домен, просто сериализует и шлёт то, что дали. Сборка payload по контракту (`s3_bucket`, `s3_key`, `group_slug`, `lms`, `recorded_at`, `duration_sec: null`, …) — этап 8. **Подтверждено вами.**
4. **`DRY_RUN` — не в `LmsClient`.** Несмотря на то, что в текущей заглушке-докстринге упомянут «dry-run», по аналогии с `S3Gateway` (этап 6, тоже не занимался `DRY_RUN`) это решение вынесено в composition root на этапе 10: при `DRY_RUN=true` там будет подключаться другая реализация (или клиент вообще не будет вызываться, а шаг сразу будет логироваться как успешный) — сам `LmsClient` всегда делает настоящий HTTP-запрос, никакой ветки `if self._dry_run` внутри него не будет.
5. **Успех — строго `{200, 201}`**, не любой код `< 300`: CLAUDE.md называет ровно эти два кода; если однажды плагин ответит, скажем, `204`, лучше явно увидеть непонятную классификацию в тесте/логе, чем молча посчитать успехом что-то не описанное в контракте.
6. **`LmsClient` владеет своим `httpx.Client`** (создаётся в конструкторе с `base_url` и заголовком токена на все запросы) и даёт `close()` — симметрично тому, что CLAUDE.md требует graceful shutdown в `main.py`; composition root закроет клиент при остановке сервиса.
7. **Таймаут — захардкожен константой модуля**, не новая переменная `Settings`: в таблице Configuration CLAUDE.md таймаута LMS-запроса нет, заводить новую конфигурацию без явного запроса не буду (по аналогии с 64 MiB в `S3Gateway`, тоже константа, не настройка).

### 7.1 `LmsClient` (lms/client.py)

```python
_TIMEOUT_SECONDS = 30.0
_ENDPOINT_PATH = "/wp-json/fs-lms/v1/videos"


class LmsRegistrationError(Exception):
    """Базовое исключение при регистрации видео в LMS."""


class LmsRetryableError(LmsRegistrationError):
    """5xx или сетевая ошибка — стоит повторить в следующем цикле сканирования."""


class LmsRejectedError(LmsRegistrationError):
    """Прочие 4xx — LMS отвергла payload содержательно, повторять бессмысленно."""


class LmsClient:
    """REST-клиент fs-lms: POST /wp-json/fs-lms/v1/videos с токеном в заголовке."""

    def __init__(self, base_url: str, token: str) -> None:
        """Создаёт httpx.Client с base_url и X-FS-Uploader-Token на все запросы."""

    def register(self, payload: dict[str, object]) -> None:
        """Один POST-запрос; успех — return, иначе — LmsRetryableError/LmsRejectedError."""

    def close(self) -> None:
        """Закрывает внутренний httpx.Client (graceful shutdown)."""
```

- [x] Конструктор: `httpx.Client(base_url=..., headers={"X-FS-Uploader-Token": token}, timeout=_TIMEOUT_SECONDS, transport=...)`. Добавлен keyword-only `transport: httpx.BaseTransport | None = None` сверх постановки — штатная точка подмены сети у самого `httpx` (`MockTransport` в тестах), в проде остаётся `None` → используется стандартный транспорт.
- [x] `register`: `try/except httpx.HTTPError` → `LmsRetryableError`.
- [x] Классификация: `{200, 201}` → `return`; `>= 500` → `LmsRetryableError`; иначе → `LmsRejectedError`. Сообщение — код + обрезанное тело (`[:500]`).
- [x] `close()` — `self._client.close()`.
- [x] Логгер `video_uploader.lms.client` заведён, сами методы не логируют.

### 7.2 Тесты (`tests/lms/test_client.py`, 13 тестов)

- [x] 200/201 → без исключений; тело запроса — валидный JSON = payload, заголовок токена, путь запроса.
- [x] 500/502/503 → `LmsRetryableError` (код и фрагмент тела — в тексте исключения).
- [x] 400/404/422 → `LmsRejectedError`; отдельный тест фиксирует, что это **не** `LmsRetryableError` (проверка направления иерархии, не только факта своего типа).
- [x] Сетевая ошибка (`MockTransport`, хендлер бросает `httpx.ConnectError`) → `LmsRetryableError`.
- [x] `close()`: последующий `register()` на закрытом клиенте поднимает `RuntimeError` (это `httpx`, не `httpx.HTTPError` — наружу, не оборачивается).

### Definition of Done (этап 7)

- [x] Решение по пункту 3 подтверждено вами — payload-словарь.
- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 176/176 тестов.
- [x] Ревью Claude пройдено (код и тесты написаны Claude по вашей просьбе).
- [ ] Коммит — на вашей стороне.

---

## Этап 8 — Pipeline (оркестратор) ← ТЕКУЩИЙ

**Цель:** `pipeline.py` — единственное место, которое видит весь путь файла целиком: от `scan()` до перемещения в архив, склеивая scanner (4), stability (4), metadata+resolver (5), state repository (3), S3Gateway+KeyBuilder (6), LmsClient (7) и `EventBus` (2.4). Это самый большой этап — 14 решений ниже, часть из них нетривиальна и меняет уже написанный код этапа 3. **Прошу явно подтвердить решения 1, 2 и 9 — они не следуют напрямую из CLAUDE.md, это моя интерпретация того, как должен вести себя пайплайн при повторных циклах и сбоях.**

**Затрагиваемые файлы:** `video_uploader/pipeline.py`, `video_uploader/state/repository.py` (точечное изменение таблицы переходов, решение 2), `tests/test_pipeline.py`.

### Порядок шагов (напоминание из CLAUDE.md)

```
scan → stability → dedup (реестр) → metadata (дата) → resolve (группа → slug + lms)
     → upload (S3) → verify → register (LMS REST) → cleanup (архив)
```

### Решения, принятые в постановке

1. **✅ Подтверждено. `run_cycle()` живёт в `Pipeline`, не в `main.py`.** Архитектурная таблица CLAUDE.md называет `pipeline.py` «оркестратором шагов обработки одного файла» — формально это про шаги *внутри* одного файла. Но `GroupUnmapped` должен публиковаться «не чаще раза за цикл на папку» (CLAUDE.md), а «цикл» — это понятие уровня *всех* файлов разом, и его должен где-то хранить объект, который переживает несколько вызовов `process()`. Предлагаю: `Pipeline.run_cycle()` сам вызывает `scanner.scan()`, заводит `set()` уже предупреждённых папок на время цикла и последовательно обрабатывает каждый файл с изоляцией ошибок. `main.py` (этап 10) просто дёргает `run_cycle()` по таймеру `SCAN_INTERVAL_SECONDS`. Альтернатива — вынести цикл и `set()` в `main.py`, а `Pipeline.process_one(video_file, warned_folders)` принимать это множество аргументом; мне вариант с `run_cycle()` внутри `Pipeline` кажется чище (меньше протекающих деталей наружу), но это ваш вызов.

2. **✅ Подтверждено** (папки — те, что `Sync-VideoGroups.ps1` создаёт из `video-groups.csv` до того, как вы синхронно обновите `groups.yaml`; переоткрытие даёт файлу шанс обработаться после закрытия дыры в конфиге, без ручного вмешательства в реестр). Точечное изменение `_ALLOWED_TRANSITIONS` в `state/repository.py`. Сейчас (этап 3) `"skipped_unmapped": frozenset()` — терминально навсегда. Но если админ *добавит* пропущенную папку в `groups.yaml` уже после того, как файлы в ней успели схватить `skipped_unmapped`, они должны получить шанс обработаться на следующих циклах, а не зависнуть навечно. Меняю на `"skipped_unmapped": frozenset({"uploading"})`. `"skipped_old"` **не трогаю** — оставляю терминальным: старение файла необратимо (время не идёт назад), в отличие от дыры в конфиге, которую можно исправить. Если считаете, что `skipped_old` тоже должен быть переоткрываемым (например, если админ увеличит `SKIP_OLDER_THAN_DAYS`) — скажите, добавлю симметрично.
3. **Протоколы `UploadGateway`/`RegistrationClient` объявляются прямо в `pipeline.py`**, не в новых файлах `storage/base.py`/`lms/base.py`. Это узкие интерфейсы (SOLID-I) ровно из тех методов, которые пайплайн реально вызывает у `S3Gateway`/`LmsClient` — сами классы им уже соответствуют структурно (Python Protocol, `S3Gateway`/`LmsClient` не нужно ничего наследовать). Место объявления — у потребителя, а не у поставщика: так Architecture-таблица CLAUDE.md (там нет строк `storage/base.py`/`lms/base.py`) не нарушается, а требование SOLID-D («pipeline зависит только от Protocol») выполняется.
   ```python
   class UploadGateway(Protocol):
       def upload_video(self, path: Path, key: str, metadata: Mapping[str, str]) -> None: ...
       def put_manifest(self, key: str, manifest: dict[str, object]) -> None: ...
       def verify(self, key: str, expected_size: int) -> bool: ...

   class RegistrationClient(Protocol):
       def register(self, payload: dict[str, object]) -> None: ...
   ```
   `StateRepository` за Protocol не прячем — раздел Testing CLAUDE.md явно говорит, что для пайплайна нужны `FakeS3Gateway`, `FakeLmsClient`, но реестр — «на tmp SQLite» (настоящий репозиторий). Сканер/`StabilityChecker`/`GroupResolver` — туда же, без фейков, настоящие объекты на `tmp_path`/собранном в тесте `GroupsConfig`.
4. **`sha256` считается прямо в `pipeline.py`** (этап 6 сознательно это не взял на себя, этап 3 дал только кэш). Поток по 1 MiB, как того требует CLAUDE.md: `hashlib.sha256()` + `while chunk := f.read(1024*1024): hasher.update(chunk)`. Модульная функция `_compute_sha256(path) -> str`, не метод — не нужен `self`.
5. **Сборка `metadata`-словаря для `x-amz-meta-*`, JSON-манифеста и REST-payload — тоже здесь**, как и было обещано на этапах 6–7 (там я сознательно вывел это за скобки). Три отдельные модульные функции: `_build_object_metadata(lesson, sha256) -> dict[str, str]`, `_build_manifest(video_file, lesson, sha256, s3_key, uploaded_at) -> dict[str, object]`, `_build_lms_payload(...) -> dict[str, object]`. Ключи `lms`-блока для `x-amz-meta-lms-*` — маппинг `_` → `-` (`teacher_id` → `lms-teacher-id`), как требует CLAUDE.md.
6. **Даты — сериализация через `.isoformat()`**: tz-aware `datetime` сам даёт `2026-07-08T16:04:45+03:00` (для `recorded_at`) и `...+00:00` (для `uploaded_at` в UTC) — ровно формат из примеров CLAUDE.md, без ручной сборки строки.
7. **Стратегии даты — упорядоченный список, перебор до первого успеха**, не хардкод «сначала имя файла, потом mtime» по именам классов: `date_extractors: Sequence[DateExtractor]` в конструкторе (Strategy, SOLID-O — новая стратегия добавляется без правки `pipeline.py`). `date_from_fallback = (индекс сработавшей стратегии > 0)` — обобщается корректно на любое число стратегий, а не только на ровно две.
8. **`SKIP_OLDER_THAN_DAYS` сравнивается с `recorded_at`**, не с `mtime`: семантически это «пропустить старые *занятия*», а дата занятия — результат шага metadata, не сырой атрибут файла. Проверка идёт сразу после определения даты, до resolve (нет смысла резолвить группу файлу, который всё равно пропустим).
9. **✅ Подтверждено. Возобновление после падения процесса — «не звать mark_\*, если запись уже в этом статусе».** Если сервис упадёт (SIGKILL, OOM, перезапуск контейнера) между `mark_uploading` и `mark_uploaded`, запись останется в статусе `uploading` без исключения, поймавшего это в `mark_failed`. На следующем цикле файл снова найдётся сканером, дойдёт до шага upload — и попытка повторно вызвать `mark_uploading` из статуса `uploading` упадёт `InvalidTransitionError` (в таблице переходов `"uploading"` нет самого себя как допустимой цели). Решение: каждый `mark_*`-вызов в pipeline предваряется проверкой `if current_status != "<целевой>"` — если запись уже там, где нужно, просто не вызываем репозиторий повторно, а используем уже сохранённые данные (`s3_key` из записи, если статус уже `uploaded`+ — тогда даже сам upload на S3 повторно не делаем, сразу verify). Если статус `uploading` (не дошли до `uploaded`) — upload на S3 повторяем (он идемпотентен, просто перезапишет тот же ключ), а вот `mark_uploading` — нет. Это не следует из CLAUDE.md напрямую, а закрывает дыру, которую я нашёл, продумывая этот этап — если считаете это избыточным для MVP, могу упростить до «просто дать упасть в failed и ретраить с нуля», но тогда придётся расширить таблицу переходов (`uploading`→`uploading`), что противоречит решению 2 (минимальные изменения `state/repository.py`).
10. **Идемпотентность по контенту (дедуп)** — сразу после получения `sha256` (свой, посчитанный или взятый из кэша), проверяем `repo.get_by_sha256(sha256)`: если нашли **чужую** запись (другой `id`) в статусе `registered`/`archived` — переиспользуем её `s3_key`, проходим `mark_uploading → mark_uploaded(тем же s3_key) → mark_registered` без единого сетевого вызова к S3/LMS, и сразу переходим к cleanup. Этот шорткат применяется только если *своя* запись ещё не начинала аплоад (`discovered`/`failed`/`skipped_unmapped`) — если она уже в `uploading`/`uploaded`, идём её собственным путём (решение 9), не запутываем два процесса.
11. **`GroupUnmapped` и повторный `mark_skipped`** — не публикуем событие повторно в рамках *одного* цикла для той же папки (`set()` из решения 1); `mark_skipped(file_id, "skipped_unmapped")` тоже не дёргаем, если запись уже в этом статусе (решение 9, тот же принцип).
12. **`DRY_RUN` не проникает в pipeline, кроме одного места — архивации.** `S3Gateway`/`LmsClient` подменяются на dry-run-реализации в composition root (этап 10, уже решили на этапах 6–7) — пайплайн зовёт их как обычно и даже проводит запись через `uploaded`/`registered` по-настоящему («шаг register логируется и считается успешным» — CLAUDE.md). Но у архивации нет отдельного inject-объекта (это просто `Path.rename`), поэтому единственная ветка `if self._dry_run` во всём файле — вокруг фактического перемещения файла: событие и статус `archived` в дневном режиме всё равно не проставляются (файл физически не тронут, значит и `mark_archived` вызывать нечего — иначе реестр окажется рассинхронизирован с диском).
13. **Cleanup не требует ни `group_slug`, ни `recorded_at`** — это чисто файловая операция `video_file.path.parent / ARCHIVE_SUBDIR`, `rename()` в пределах той же шары (сервер сам делает это без копирования — обычное поведение `Path.rename` на одном mount). При коллизии имени — суффикс `_{sha8}` к имени (не к расширению).
14. **Изоляция ошибок — на уровне `run_cycle()`**, оборачивает вызов обработки каждого файла; `file_id` получаем через `discover()` *до* захода в `try`, чтобы `except` мог записать `mark_failed` даже если упал произвольный более поздний шаг. Если падает сам `discover()` (маловероятно, локальная SQLite) — это уходит выше по стеку без записи в реестр (писать некуда), но не останавливает цикл — `run_cycle()` ловит вообще любое исключение per-file на самом верхнем уровне тоже.

### 8.1 Протоколы и модульные хелперы

- [x] `UploadGateway`, `RegistrationClient` (Protocol) — решение 3.
- [x] `_compute_sha256(path: Path) -> str` — потоково, чанк 1 MiB.
- [x] `_build_object_metadata(lesson: LessonMeta, sha256: str) -> dict[str, str]` — `group-slug`, `recorded-at` (`.isoformat()`), `sha256`, `lms-<key>` на каждую пару `lesson.lms` (`_` → `-`).
- [x] `_build_manifest(video_file, lesson, sha256, uploaded_at) -> dict[str, object]` — schema 2, все поля примера CLAUDE.md. Без параметра `s3_key`: в самом манифесте свой ключ не упоминается (манифест уже лежит под этим ключом + `.json`), убрал неиспользуемый параметр из исходной постановки.
- [x] `_build_lms_payload(bucket, s3_key, manifest_key, lesson, video_file, sha256) -> dict[str, object]` — `duration_sec: None`.

### 8.2 `Pipeline.__init__`

Зависимости через конструктор (композиция — этап 10): `scanner: VideoScanner`, `stability: StabilityChecker`, `repo: StateRepository`, `date_extractors: Sequence[DateExtractor]`, `resolver: GroupResolver`, `key_builder: KeyBuilder`, `s3: UploadGateway`, `lms: RegistrationClient`, `events: EventBus`, `bucket: str`, `archive_subdir: str`, `archive_after_register: bool`, `max_attempts: int`, `skip_older_than_days: int | None`, `dry_run: bool`. Да, параметров много — это ожидаемо для оркестратора, который единолично склеивает всё; не пытаюсь притворно упаковывать их в один объект-конфиг без вашей просьбы.

### 8.3 `run_cycle()`

- [x] `warned_folders: set[str] = set()` — локальная переменная на время вызова.
- [x] `for video_file in self._scanner.scan():`.
- [x] Два вложенных `try`: внешний вокруг `discover()` (если падает — `logger.exception` + `continue`, писать в реестр уже некуда), внутренний вокруг `self._process(...)` с двумя `except` — `LmsRejectedError` (permanent=True) первым, затем общий `Exception` (permanent=False). Более специфичный `except` обязан идти раньше общего.

### 8.4 `_process(file_id, video_file, warned_folders)` — алгоритм

Реализовано по алгоритму постановки, с одним найденным на тестах уточнением к шагу 11 (см. ниже).

1. [x] `state = repo.get_by_id(file_id)` (сам `discover()` уже выполнен в `run_cycle()`).
2. [x] Ранние выходы: `{"archived", "skipped_old"}` → `return`; `"failed"` с исчерпанными попытками → `return`.
3. [x] `"registered"` → сразу `_cleanup(file_id, video_file, state.sha256)`, `return`.
4. [x] `is_stable()` → `False` → `return`, не ошибка.
5. [x] `_resolve_sha256`: кэш реестра либо потоковый подсчёт + `set_sha256`.
6. [x] Дедуп по контенту — только для `_DEDUP_ELIGIBLE_STATUSES = ("discovered", "failed", "skipped_unmapped")`.
7. [x] `_extract_date`: перебор `date_extractors`, `date_from_fallback = (индекс > 0)`; событие `DateFallback`.
8. [x] `SKIP_OLDER_THAN_DAYS` от `recorded_at` → `mark_skipped(..., "skipped_old")`, `return`.
9. [x] `resolve()` → `None`: `GroupUnmapped` (не чаще раза за папку), `mark_skipped(..., "skipped_unmapped")` если ещё не в этом статусе, `return`.
10. [x] Собрать `LessonMeta`.
11. [x] **⚠️ Уточнение к постановке, найдено на тестах.** Условие входа в upload-блок — `state.s3_key is None`, **не** `state.status != "uploaded"`. Причина: если упасть на *более позднем* шаге (verify/register/cleanup), `mark_failed` перезатирает `status` на `"failed"`, а `s3_key` остаётся сохранённым — только `s3_key` надёжно говорит «загрузка уже случилась». Дальше: если `s3_key` уже есть, а `status == "failed"` (упало позже upload) — технически восстанавливаем `uploading → uploaded` (без сети) перед тем, как `mark_registered` увидит допустимый переход из `uploaded`, а не из `failed` (которого таблица переходов не разрешает напрямую в `registered`).
12. [x] `verify()` → `False` → `raise RuntimeError(...)`.
13. [x] Register-блок (`if state.status != "registered"`) — регистрация в LMS дешёвая и явно идемпотентна по контракту (upsert по `s3_key`), поэтому в отличие от upload не нужен отдельный «надёжный сигнал» — проверки по `status` достаточно.
14. [x] `_cleanup(file_id, video_file, sha256)`.

### 8.5 `_cleanup(file_id, video_file, sha256)`

Сигнатура упрощена относительно постановки — принимает `sha256: str` напрямую, не весь `FileState` (только это поле и нужно для суффикса коллизии).

- [x] `not archive_after_register` → `return`.
- [x] `dry_run` → `logger.info(...)`, `return` без изменений в БД/на диске.
- [x] `archive_dir = video_file.path.parent / archive_subdir`; `mkdir(exist_ok=True)`.
- [x] Коллизия имени → `_{sha256[:8]}` перед расширением.
- [x] `rename()` → `mark_archived` → событие `VideoArchived`.

### 8.6 Обработка ошибок в `run_cycle()` (метод `_fail`)

- [x] `logger.exception(...)`, `mark_failed(file_id, str(exc))`.
- [x] `permanent=True` (для `LmsRejectedError`) — крутит `mark_failed` в цикле, наращивая локальный счётчик `attempts` (не перечитывая БД на каждой итерации — `mark_failed` детерминированно инкрементирует на 1), пока не достигнет `max_attempts`; таблица переходов уже разрешала `failed → failed` с этапа 3, менять ничего не пришлось. Это и есть решение открытого пункта постановки про «4xx без ретраев» — вариант (а).
- [x] `attempts == max_attempts` (строгое равенство) → событие `VideoFailed` публикуется ровно один раз, на пересечении порога.

### 8.7 Тесты (`tests/test_pipeline.py`)

Фейки: `FakeS3Gateway`, `FakeLmsClient` (структурно реализуют `UploadGateway`/`RegistrationClient`). `StateRepository` — настоящий, на `tmp_path`. Сканер/`StabilityChecker`/`GroupResolver` — настоящие. 15 тестов, все прошли после исправления двух багов (см. ниже).

- [x] **Happy path** — до `archived`; события по одному разу; проверен ключ S3, `x-amz-meta-*`, REST-payload (`s3_bucket`, `group_slug`, `duration_sec is None`).
- [x] **Нестабильный файл** — остаётся `discovered`, upload не вызван.
- [x] **`GroupUnmapped` не чаще раза за цикл** — два файла одной незамапленной папки в одном `run_cycle()` → событие один раз, обе записи `skipped_unmapped`.
- [x] **`skipped_unmapped` → переоткрытие** — после добавления группы в конфиг следующий `run_cycle()` доводит до `archived`.
- [x] **`SKIP_OLDER_THAN_DAYS`** — `skipped_old`, upload не вызван.
- [x] **`DateFallback`** — событие опубликовано, дата из `mtime` дошла до манифеста.
- [x] **Verify fail** — `failed`, `attempts == 1`, register не вызван.
- [x] **Upload fail** — `failed`, `attempts == 1`.
- [x] **Register 5xx (retryable)** — `failed` после первого цикла; на втором (ошибка снята) — `archived`, **`upload_video` вызван ровно 1 раз за оба цикла** (найденный баг №1, см. DoD).
- [x] **Register 4xx (rejected)** — `attempts` сразу выставлены в `max_attempts` (не растут по одному за цикл), `VideoFailed` опубликован один раз, следующий `run_cycle()` файл не трогает вовсе.
- [x] **Дедуп по контенту** — второй файл с тем же содержимым архивируется с тем же `s3_key`, без вызовов `upload_video`/`put_manifest`/`register`.
- [x] **Возобновление из `uploading`** — статус выставлен вручную через репозиторий (симуляция крэша) без `s3_key`, `run_cycle()` не падает на `InvalidTransitionError`, доходит до `archived`.
- [x] **`ARCHIVE_AFTER_REGISTER=false`** — остаётся `registered` на диске, `VideoArchived` не публикуется.
- [x] **`DRY_RUN=true`** — архивация пропущена, статус остаётся `registered`, файл на месте.
- [x] **`MAX_ATTEMPTS` исчерпаны** — `VideoFailed` публикуется один раз за 3 цикла падений, четвёртый цикл файл не трогает (`upload_calls` не растёт).

### Definition of Done (этап 8)

- [x] Решения 1, 2, 9 подтверждены вами.
- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 191/191 тестов.
- [x] Ревью Claude пройдено. Найдено и исправлено два реальных бага при написании тестов:
  1. **`pipeline.py`** — `mark_registered` мог упасть `InvalidTransitionError` при ретрае после падения именно на шаге `register` (не `upload`): `mark_failed` перезатирал статус `uploaded → failed`, а таблица переходов не пускает `failed → registered` напрямую. Исправлено: если `s3_key` уже есть, а текущий статус `failed` — сначала технически восстанавливаем `uploaded` (`mark_uploading` + `mark_uploaded`, без единого сетевого вызова), только потом `mark_registered`.
  2. **`tests/test_pipeline.py`** — в `FakeS3Gateway.upload_video` вызов записывался в `upload_calls` *после* проверки на ошибку, из-за чего падающие попытки не попадали в счётчик. Поменял порядок: сначала фиксируем вызов, потом решаем, бросать исключение или нет.
- [ ] Коммит — на вашей стороне.

---

## Этап 8.1 — HMAC-аутентификация LMS (правки по контракту fs-lms) ← ТЕКУЩИЙ

**Контекст:** вы обновили CLAUDE.md (раздел «TODO интеграции с fs-lms», строки 306+) по итогам согласования с плагином (ветка `stage_11`, контракт `FS_LMS_API.md`). Статический токен `X-FS-Uploader-Token` заменён на HMAC-подпись (та же схема, что у модуля AdSync), плюс плагин теперь возвращает поле `matched` в ответе. Это не новый шаг пайплайна — правки точечные, в уже написанном коде этапов 2 и 7. `pipeline.py` не трогаем: REST-payload и Protocol `RegistrationClient` не изменились, меняется только *механика аутентификации* внутри `LmsClient`.

**Затрагиваемые файлы:** `video_uploader/lms/client.py`, `video_uploader/config.py`, `.env.example`, `config/groups.yaml.example`, `tests/lms/test_client.py`, `tests/test_config.py`, `tests/test_groups.py` (один тест на новый реальный кейс).

### Решения

1. **`raw_body` — сериализуем JSON один раз, переиспользуем для подписи и отправки.** Критично: если `httpx` пересериализует payload сам (через `json=`), байты подписи и байты тела могут разойтись (другой порядок ключей/пробелы) — плагин пересчитает HMAC от полученных байт и получит несовпадение → `401`. Поэтому `self._client.post(..., content=raw_body, ...)`, не `json=payload`; `Content-Type: application/json` выставляется вручную в заголовках запроса (при `content=` `httpx` его сам не проставляет, в отличие от `json=`).
2. **Сообщение для HMAC — конкатенация байтов, не строк**: `f"{timestamp}.".encode("ascii") + raw_body`, эквивалентно `"{timestamp}.{raw_body}"` из контракта, но без риска мисматча кодировки при склейке `str` и `bytes`.
3. **Таймстамп — `int(time.time())` прямо в `register()`**, без инъекции часов через конструктор: тесты пересчитывают ожидаемую подпись из **фактически отправленного** `X-Fs-Timestamp` (перехваченного через `httpx.MockTransport`), а не мокают время. Проще, чем городить `Clock`-протокол ради одного метода.
4. **`matched: false` — не исключение**, а `logger.warning(...)` внутри `register()` после успешного статуса; сам факт успеха (`return` без ошибки) не меняется — CLAUDE.md прямо говорит «для сервиса оба случая = registered». Тело ответа парсится в `try/except ValueError` (`response.json()` бросает `json.JSONDecodeError`, это подкласс `ValueError`) — если плагин однажды пришлёт `200` без валидного JSON, не должны с этого падать, раз статус уже говорит об успехе.
5. **`lms_hmac_secret: SecretStr` — обязательное поле** (без default), тем же паттерном, что `s3_secret_key`: это и был исходный план для LMS-секрета ещё на этапе 2.1, до того как вы сознательно отложили его добавление. Теперь добавляем сразу под правильным именем — переименовывать в коде нечего.
6. **`GroupResolver`/`GroupEntry`/`GroupsConfig` не переименовываем.** CLAUDE.md прямо говорит: «Сервис папки не различает — семантику задаёт состав `lms`-блока в конфиге», и пункт 5 TODO подтверждает «кода это не требует». Переименование устоявшихся классов ради терминологии («группа» → «папка/сущность») — не запрошено и добавило бы churn без функциональной пользы.

### 8.1.1 `LmsClient` (lms/client.py) — переписать аутентификацию

```python
def __init__(self, base_url: str, hmac_secret: str, *, transport: httpx.BaseTransport | None = None) -> None:
    """httpx.Client без постоянных заголовков — HMAC считается заново на каждый запрос."""

def register(self, payload: dict[str, object]) -> None:
    """Сериализует payload один раз, подписывает те же байты, шлёт их же."""

def _sign(self, timestamp: int, raw_body: bytes) -> str:
    """hex(hmac_sha256(f"{timestamp}." + raw_body, hmac_secret))."""
```

- [x] Конструктор: параметр `token: str` → `hmac_secret: str`; `httpx.Client` больше не получает `headers={...}` при создании (HMAC-заголовки — per-request, не постоянные).
- [x] `register`: `raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")`; `timestamp = int(time.time())`; `signature = self._sign(timestamp, raw_body)`; заголовки `{"X-Fs-Timestamp": str(timestamp), "X-Fs-Signature": signature, "Content-Type": "application/json"}`; `self._client.post(_ENDPOINT_PATH, content=raw_body, headers=headers)`.
- [x] Классификация ответа — **без изменений** (200/201 успех, 5xx retryable, прочие 4xx rejected); на успехе — новый вызов `_log_match_status(response)` перед `return`.
- [x] `_log_match_status(response)` — `try: data = response.json() except ValueError: return`; если `isinstance(data, dict) and data.get("matched") is False` → `logger.warning(...)`.
- [x] `close()` — без изменений.

### 8.1.2 `config.py`

- [x] `lms_hmac_secret: SecretStr` — обязательное поле, рядом с `s3_secret_key` в блоке «Секреты».
- [x] Обновить тест `test_required_fields_reported` в `tests/test_config.py` — теперь 5 обязательных полей, не 4.
- [x] Добавить `lms_hmac_secret` в хелпер `REQUIRED`/`_make_settings` в `tests/test_config.py`, иначе все существующие тесты `Settings` перестанут собираться.

### 8.1.3 `.env.example`

- [x] `LMS_UPLOADER_TOKEN=` → `LMS_HMAC_SECRET=`, комментарий — «Секрет HMAC-подписи (= `FS_LMS_VIDEO_HMAC_SECRET` в wp-config плагина)».

### 8.1.4 `config/groups.yaml.example`

- [x] Добавить пример персональной папки преподавателя (`"Индивидуальные-Петров"` → `lms: {teacher_username: "i.petrov"}`, без `group_id`), с комментарием про две ветки резолва на стороне плагина (по составу `lms`-блока) — как в примере CLAUDE.md.

### 8.1.5 Тесты

`tests/lms/test_client.py` — переписать под HMAC (статический токен и его заголовок больше не существуют):
- [x] Заголовки `X-Fs-Timestamp`/`X-Fs-Signature` присутствуют в запросе; `X-Fs-Timestamp` — целое число, близкое к текущему времени (например, `abs(int(request.headers["X-Fs-Timestamp"]) - time.time()) < 5`).
- [x] Подпись валидна: пересчитать `hmac_sha256(f"{ts}.".encode() + request.content, secret)` из перехваченного запроса и сверить с `X-Fs-Signature`.
- [x] `Content-Type: application/json` присутствует.
- [x] Тело запроса, декодированное из `request.content`, равно исходному payload (побайтовое соответствие тому, что ушло на подпись, — не косвенно через `json=`).
- [x] 200 с `{"ok": true, "matched": true, ...}` → `register()` не бросает, `caplog` **не** содержит WARNING про непривязанное занятие.
- [x] 200 с `{"matched": false, ...}` → не бросает, но `caplog` содержит WARNING.
- [x] 200 с невалидным JSON-телом → не бросает (ответ уже успешный по статусу, парсинг `matched` — best-effort).
- [x] Существующие тесты классификации (500/503 → `LmsRetryableError`, 400/404/422 → `LmsRejectedError`, сетевая ошибка, `close()`) — актуализировать под новую сигнатуру `LmsClient(base_url, hmac_secret, transport=...)`, поведение не меняется.

`tests/test_groups.py`:
- [x] Один новый тест: `lms: {teacher_username: "i.petrov"}` без `group_id` — валидируется как обычная запись (документирует реальный кейс из обновлённого CLAUDE.md; код уже поддерживает это без изменений — `lms`-блок opaque).

### Definition of Done (этап 8.1)

- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто.
- [x] Ревью Claude пройдено, замечания закрыты.
- [ ] Коммит — на вашей стороне.

### Не код (зафиксировано для памяти, не задача этого репозитория)

- **NTP** (пункт 4 TODO CLAUDE.md): часы LXC должны быть синхронизированы — окно HMAC ±300 c, рассинхрон часов → `401`. Это настройка хоста (`chrony`/`systemd-timesyncd`), проверить при деплое на этапе 11 (поставка), не задача кода.
- **Процесс** (пункт 7 TODO): завести персональные папки преподавателей на шаре (`Sync-VideoGroups.ps1`/вручную) и согласовать с преподавателями, что индивидуальные записи кладутся в личную папку — организационная договорённость, не код.

---

## Этап 9 — Логи и уведомления

**Цель:** `logging.Handler`-стратегии, фабрика, собирающая их из `Settings`. Ключевое эргономическое требование (по вашей просьбе): после того как фабрика один раз настроит логгер `video_uploader` в `main.py` (этап 10), **любой код в любом модуле** логирует куда угодно просто через `logging.getLogger(__name__)` + `.info()/.warning()/.error()` — без импорта чего-либо из `logging_setup`. Это и есть «удобно и универсально»: не новый API, а корректно настроенная стандартная иерархия логгеров stdlib.

**⚠️ Скоуп изменён по ходу этапа (2026-07-17).** Изначально планировались три хендлера (file/loki/telegram) и `TelegramNotifier`-подписчик `EventBus` для бизнес-уведомлений. **Вы приняли архитектурное решение отказаться от прямой Telegram-интеграции в этом сервисе**: Telegram-бот (и любые другие боты) будете делать отдельным сервисом на `aiogram`, вне этого репозитория. **Loki становится основным каналом** для такого бота — он будет читать события из Loki, а не получать вебхуки/push от `fs-video-uploader` напрямую. Соответственно:
- `logging_setup/telegram.py` (`TelegramLogHandler`) и `notifications/telegram.py` (`TelegramNotifier`) — **возвращены в состояние заглушки**, реализация отменена. `TELEGRAM_BOT_TOKEN` в `Settings` не добавляется. Обе заглушки помечены докстрингом «отложено 2026-07-17», чтобы будущая сессия понимала, что это осознанный откат, а не недоделанный этап 9.
- Обсуждали и вариант push-вебхука от `EventBus`-подписчика к боту (симметрично `lms/client.py`) — вы явно предпочли poll/read-из-Loki, вебхук не делаем.

**Найденный по ходу этапа пробел (не связан с решением про Telegram, актуален независимо):** `pipeline.py` публиковал события `GroupUnmapped`/`DateFallback` в `EventBus`, но **не логировал** их через `logging` — а CLAUDE.md прямо требует WARNING-уровень для обоих. Без лога они не долетали ни до файла, ни (что стало важно сегодня) до Loki. Исправлено. Заодно — по вашему решению сделать Loki основным каналом — добавлены INFO-логи на успешные шаги (`VideoUploaded`/`VideoRegistered`/`VideoArchived`), которых раньше не было вовсе (эти события тоже раньше жили только в `EventBus`, без следа в `logging`).

**Затрагиваемые файлы (по факту):** `video_uploader/logging_setup/loki.py`, `video_uploader/logging_setup/factory.py`, `video_uploader/pipeline.py` (точечные логи), `tests/logging_setup/test_loki.py`, `tests/logging_setup/test_factory.py`, правки в `tests/test_pipeline.py`.

### Решения

1. **Loki — основной канал наблюдаемости; Telegram/другие боты — читатели Loki, не получатели push от этого сервиса.** Ваше решение 2026-07-17, отменяет исходные пункты 1–2 постановки (выбор события для бизнес-уведомления, наполнение текста) — они больше не применимы, Telegram-уведомления из этого репозитория не отправляются.
2. **Один HTTP-запрос на запись, без батчинга** — в `LokiHandler`. Сервис фоновый, малый объём логов — батчинг с таймером флаша добавил бы сложность без реальной пользы на этом масштабе.
3. **Ошибки внутри `logging.Handler.emit()` — через `self.handleError(record)`**, стандартный механизм stdlib `logging`, а не собственный `try/except` с `logger.exception` (риск зацикливания — хендлер логирования сам логирует свою поломку тем же логированием).
4. **`configure_logging(settings)` вешает хендлеры на логгер `"video_uploader"`, не на root**, и выставляет `propagate = False`. Так сторонние библиотеки (`boto3`, `httpx`, `sqlalchemy`) не заваливают наши синки своим внутренним логом, и нет риска задвоения, если что-то ещё (например, `uvicorn`) сконфигурирует root-логгер по-своему.
5. **Уровень логгера `"video_uploader"` — `INFO` захардкожен**, не новая переменная `Settings`: в таблице Configuration `LOG_LEVEL` нет, заводить новую настройку без запроса не буду.
6. **`LokiHandler` получает `transport: httpx.BaseTransport | None = None`** — та же точка тестовой подмены сети, что уже была у `LmsClient` (этап 7): штатный механизм `httpx`, не monkeypatch.
7. **INFO-логи успешных шагов и WARNING для `GroupUnmapped`/`DateFallback` — прямо рядом с `events.publish(...)` в `pipeline.py`**, не через отдельного generic-подписчика «событие → лог». `EventBus` и `logging` — параллельные, независимые каналы с разными потребителями (уведомления vs наблюдаемость); подмешивать один в другой через дополнительную абстракцию не было запрошено, а прямой вызов `logger.info/warning` рядом с местом действия — ровно то же самое, что уже сделано для `logger.exception` в `_fail`.

### 9.1 `LokiHandler` (logging_setup/loki.py)

- [x] `__init__(self, url: str, *, transport: httpx.BaseTransport | None = None)`.
- [x] `emit`: `{"streams": [{"stream": {"service": "fs-video-uploader", "level": record.levelname, "logger": record.name}, "values": [[str(int(record.created * 1e9)), self.format(record)]]}]}` → `POST /loki/api/v1/push`; `try/except httpx.HTTPError: self.handleError(record)`.
- [x] Таймаут запроса — 5 с, константа модуля.
- [x] `close()` — закрывает `httpx.Client`, затем `super().close()`.

### 9.2 `TelegramLogHandler` (logging_setup/telegram.py) — отменено, см. врезку выше

- [x] Возвращён в состояние заглушки с докстрингом «отложено 2026-07-17».

### 9.3 `logging_setup/factory.py`

- [x] `logger = logging.getLogger("video_uploader")`; `setLevel(logging.INFO)`; `propagate = False`; `handlers.clear()` (идемпотентность).
- [x] file: `(settings.data_dir / "logs").mkdir(parents=True, exist_ok=True)`; `RotatingFileHandler(..., maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")`; `Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")`.
- [x] loki: `if settings.loki_url is not None:` → `LokiHandler(settings.loki_url)` с тем же форматтером.
- [x] Telegram-ветка удалена (решение 1).

### 9.4 `TelegramNotifier` (notifications/telegram.py) — отменено, см. врезку выше

- [x] Возвращён в состояние заглушки с докстрингом «отложено 2026-07-17».

### 9.5 `config.py` / `.env.example`

- [x] `telegram_bot_token` **не добавлен** — решение 1, больше не нужен этому сервису.

### 9.6 `pipeline.py` — недостающие логи (найдено по ходу этапа)

- [x] `DateFallback`: `logger.warning("дата занятия не найдена в имени файла, взят mtime: %s", video_file.path)` перед `events.publish(...)`.
- [x] `GroupUnmapped`: `logger.warning("папка отсутствует в groups.yaml: %s", video_file.group_folder)` перед `events.publish(...)` — внутри того же `if ... not in warned_folders`, так что тоже не чаще раза за цикл на папку.
- [x] `VideoUploaded`: `logger.info("видео загружено: %s -> %s", video_file.path, s3_key)` — и в основном потоке, и в `_replay_duplicate` (с пометкой «дубликат по контенту» в тексте).
- [x] `VideoRegistered`: `logger.info("видео зарегистрировано в LMS: %s -> %s", ...)` — аналогично, оба места.
- [x] `VideoArchived`: `logger.info("исходник перемещён в архив: %s -> %s", video_file.path, target)`.

### 9.7 Тесты

`tests/logging_setup/test_loki.py` (7 тестов, `httpx.MockTransport`, тот же подход, что у `LmsClient`):
- [x] Форма push-запроса (`streams[0].stream` — `service`/`level`/`logger`; `values[0]` — `(timestamp_ns, formatted_line)`).
- [x] Кастомный `Formatter`, если задан через `setFormatter`, реально используется в `values[0][1]`.
- [x] Сетевая ошибка не поднимает исключение из `emit()`.
- [x] Сетевая ошибка вызывает именно `self.handleError(record)` (проверено через `monkeypatch.setattr` на сам метод хендлера).
- [x] `close()` закрывает внутренний `httpx.Client` (`is_closed`).

`tests/logging_setup/test_factory.py` (5 тестов):
- [x] Только `DATA_DIR` → ровно один хендлер (file, `RotatingFileHandler`).
- [x] `LOKI_URL` задан → добавлен `LokiHandler`, хендлеров два.
- [x] Повторный вызов `configure_logging` не удваивает хендлеры.
- [x] `propagate is False`.
- [x] Интеграционный тест на саму суть эргономического требования: `logging.getLogger("video_uploader.some.module").info(...)` после `configure_logging(...)` долетает до `DATA_DIR/logs/uploader.log`.

`tests/test_pipeline.py` — три существующих теста дополнены проверками логов (не новые тесты, усилены существующие):
- [x] `TestGroupUnmapped.test_rate_limited_once_per_cycle` — WARNING с именем папки встречается в `caplog` ровно один раз за цикл (симметрично проверке на само событие).
- [x] `TestDateFallback.test_event_published_and_date_used` — WARNING с именем файла присутствует.
- [x] `TestHappyPath.test_file_reaches_archived` — INFO-сообщения на «загружено»/«зарегистрировано»/«архив» присутствуют.

### Definition of Done (этап 9)

- [x] Решение 1 (Loki — основной канал, Telegram отменён в этом репозитории) подтверждено вами.
- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 210/210 тестов.
- [x] Ревью Claude пройдено (код и тесты написаны Claude по вашей просьбе).
- [x] Коммит — на вашей стороне.

### Не код (важно для будущего aiogram-сервиса, не задача этого репозитория)

- Отдельный сервис на `aiogram` будет читать события из Loki (poll/tail через Loki API), а не получать push от `fs-video-uploader`. Раз так, стоит держать в уме на будущих этапах: тексты в `logger.info/warning(...)` в `pipeline.py` — это теперь не просто диагностика для вас, а фактический источник данных для внешнего потребителя. Если формат текста понадобится менять (например, для более простого парсинга ботом), это тронет уже написанный код `pipeline.py`, а не `logging_setup/`.

---

## Этап 10 — Composition root (main.py + api/app.py) ← ТЕКУЩИЙ

**Цель:** `main.py` собирает все зависимости из `Settings` (единственное место, где создаётся `Settings()`), запускает фоновый воркер сканирования и HTTP API, корректно завершается по SIGTERM. `api/app.py` — тонкий FastAPI-слой поверх `StateRepository`/воркера, без бизнес-логики. Это последний этап, где появляется новый код пайплайна — этап 11 (поставка) уже про Docker/README/smoke-скрипт, не про Python-логику.

**Затрагиваемые файлы:** `video_uploader/main.py`, `video_uploader/api/app.py`, `tests/test_main.py`, `tests/api/test_app.py`. Новых зависимостей не требуется — `fastapi`/`uvicorn` уже в `pyproject.toml` с этапа 1.

### Решения

1. **`uvicorn.run(app, host="0.0.0.0", port=settings.api_port)` блокирует главный поток; воркер — отдельный `threading.Thread`, запущенный ДО вызова `uvicorn.run`.** Порядок ровно как в докстринге заглушки CLAUDE.md: «воркер (фоновый поток) + uvicorn». `host="0.0.0.0"` захардкожен (не новая переменная `Settings` — в таблице Configuration только `API_PORT`, хоста нет): внутри контейнера иначе порт не будет достижим снаружи.
2. **Graceful shutdown по SIGTERM — не через свой `signal.signal(...)`, а через встроенный механизм uvicorn.** `uvicorn.run()`, вызванный в главном потоке, сам ставит обработчики SIGINT/SIGTERM, аккуратно останавливает HTTP-сервер и **возвращает управление** — сигнал не нужно ловить отдельно. После возврата из `uvicorn.run()` (в `finally`) останавливаем воркер: `worker.stop()` + `worker_thread.join()`. Свой обработчик сигнала здесь избыточен и рискует конфликтовать с uvicorn-овским (Python допускает один обработчик на сигнал).
3. **`/rescan` не запускает скан напрямую и не ждёт его завершения** — он лишь «будит» воркер (`threading.Event.set()`), прерывая текущий `sleep` между циклами. Единственный поток, который когда-либо вызывает `pipeline.run_cycle()`, — воркер; так гарантированно нет двух параллельных прогонов пайплайна по одной и той же SQLite (репозиторий на это не рассчитан — короткоживущие сессии, но не защита от гонки двух полных циклов одновременно). `POST /rescan` возвращает `{"status": "triggered"}` сразу, не дожидаясь результата — это соответствует слову «триггер» в описании эндпоинта CLAUDE.md.
4. **`ScanWorker` — отдельный класс внутри `main.py`**, не просто функция: инкапсулирует `stop_event`/`wake_event`/`last_scan_at` и не требует нового файла (Architecture-таблица CLAUDE.md называет только `main.py` для composition root). Публичный интерфейс — `run()` (тело потока), `stop()`, `request_rescan()`, атрибут `last_scan_at: datetime | None`.
5. **Ошибка целого цикла (не отдельного файла) ловится в `ScanWorker.run()`**, вокруг вызова `pipeline.run_cycle()` — дополнительный внешний защитный слой поверх уже существующей поштучной изоляции файлов внутри `_process`. Причина: `VideoScanner.scan()` может упасть на самом верхнем уровне (`video_root.iterdir()` — решение этапа 4: недоступность `VIDEO_ROOT` не перехватывается специально, «должен упасть»), а раз-два в рантайме SMB-шара может быть недоступна временно — сервис не должен падать целиком, только пропустить цикл и попробовать снова через `SCAN_INTERVAL_SECONDS`. `logger.exception(...)` + продолжение цикла.
6. **`api/app.py` не импортирует `ScanWorker` из `main.py`.** Обратная зависимость (composition root импортируется тем, что он сам собирает) — архитектурный запах и потенциальный циклический импорт (`main.py` импортирует `create_app` из `api/app.py`, а `api/app.py` импортировал бы `ScanWorker` оттуда же обратно). Вместо этого в `api/app.py` — узкий `Protocol` (`ScanWorkerLike`, всего `last_scan_at` + `request_rescan()`), тот же приём, что `UploadGateway`/`RegistrationClient` в `pipeline.py` (этап 8, решение 3). `StateRepository` — без Protocol: он и так единственная реализация, никогда не подменяется (решение подтверждено ещё на этапе 8, пункт 3 — «`StateRepository` за Protocol не прячем»).
7. **DRY_RUN-заглушки (`DryRunS3Gateway`, `DryRunLmsClient`) — тоже в `main.py`**, реализуют те же Protocol (`UploadGateway`/`RegistrationClient` из `pipeline.py`), структурно, без наследования. Только логируют `INFO` и возвращают успех/`True`. Архивация в dry-run уже устроена иначе (этап 8, решение 12: единственная ветка `if self._dry_run` внутри самого `Pipeline`, не через инъекцию объекта) — для неё отдельная заглушка не нужна.
8. **Порядок сборки в `main()` важен**: `configure_logging(settings)` вызывается **до** создания `StateRepository`. `configure_logging` создаёт `settings.data_dir / "logs"` через `mkdir(parents=True, exist_ok=True)` — побочным эффектом это создаёт и сам `settings.data_dir`, если его ещё нет. Если поменять порядок, `StateRepository` может упасть на несуществующей директории для `state.db`.
9. **`Settings()`/`load_groups(...)` не оборачиваются в `try/except` в `main()`.** Обе ошибки — pydantic `ValidationError` — уже сами по себе достаточно информативны («падение на старте с внятным сообщением», CLAUDE.md), самим этим требованием оправдан fail-fast без дополнительной обработки.
10. **`.close()` для `S3Gateway`/`LmsClient` (или их dry-run заглушек) — в `finally` после остановки воркера.** Оба класса (и заглушки, для единообразия — у них тоже пустой `close()`) владеют `httpx.Client`; закрывать нужно после того, как воркер точно не будет делать новых запросов (иначе теоретическая гонка — воркер начинает новый цикл, а клиент уже закрыт).

### 10.1 `ScanWorker` и DRY_RUN-заглушки (main.py)

```python
class ScanWorker:
    """Периодический запуск Pipeline.run_cycle() в фоновом потоке + внеочередной триггер."""

    def __init__(self, pipeline: Pipeline, scan_interval_seconds: int) -> None:
        self._pipeline = pipeline
        self._scan_interval_seconds = scan_interval_seconds
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self.last_scan_at: datetime | None = None

    def run(self) -> None:
        """Тело потока: цикл до stop(), прерываемый заранее через request_rescan()."""

    def request_rescan(self) -> None:
        """Будит поток немедленно, не дожидаясь SCAN_INTERVAL_SECONDS."""

    def stop(self) -> None:
        """Просит поток завершиться на следующей проверке; тоже будит его."""


class DryRunS3Gateway:
    """DRY_RUN=true: не трогает сеть, логирует и притворяется успехом."""


class DryRunLmsClient:
    """DRY_RUN=true: не трогает сеть, логирует и притворяется успехом."""
```

- [x] `run()`: `while not self._stop_event.is_set(): try: self._pipeline.run_cycle() except Exception: logger.exception(...); self.last_scan_at = datetime.now(UTC); self._wake_event.wait(timeout=self._scan_interval_seconds); self._wake_event.clear()`.
- [x] `request_rescan()` / `stop()` — оба просто `self._wake_event.set()` (`stop()` дополнительно `self._stop_event.set()`).
- [x] `DryRunS3Gateway.upload_video/put_manifest` — `logger.info(...)`, ничего не возвращают; `verify` — `logger.info(...)`, `return True`.
- [x] `DryRunLmsClient.register` — `logger.info(...)`, ничего не возвращает.
- [x] Оба dry-run класса — `close(self) -> None: pass`.

### 10.2 `main()` — сборка зависимостей

Порядок (решения 8–9):

1. `settings = Settings()`.
2. `configure_logging(settings)`.
3. `groups_config = load_groups(settings.groups_file)`.
4. `repo = StateRepository(settings.data_dir / "state.db")`.
5. `events = EventBus()` (подписчиков сейчас нет — `TelegramNotifier` отложен, этап 9; шина всё равно нужна `Pipeline`).
6. `scanner`, `stability`, `date_extractors`, `resolver`, `key_builder` — как в тестовых хелперах `tests/test_pipeline.py` (`make_pipeline`), только с реальными значениями из `settings`.
7. `s3 = DryRunS3Gateway() if settings.dry_run else S3Gateway(...)`; аналогично `lms`.
8. `pipeline = Pipeline(scanner=..., stability=..., repo=repo, date_extractors=[...], resolver=resolver, key_builder=key_builder, s3=s3, lms=lms, events=events, bucket=settings.s3_bucket, archive_subdir=settings.archive_subdir, archive_after_register=settings.archive_after_register, max_attempts=settings.max_attempts, skip_older_than_days=settings.skip_older_than_days, dry_run=settings.dry_run)`.
9. `worker = ScanWorker(pipeline, settings.scan_interval_seconds)`; `worker_thread = threading.Thread(target=worker.run, name="scan-worker")`; `worker_thread.start()`.
10. `app = create_app(repo=repo, worker=worker)`.
11. `try: uvicorn.run(app, host="0.0.0.0", port=settings.api_port) finally: worker.stop(); worker_thread.join(); s3.close(); lms.close()`.

- [x] `def main() -> None:` без параметров.
- [x] Секреты разворачиваются здесь и только здесь: `settings.s3_secret_key.get_secret_value()`, `settings.lms_hmac_secret.get_secret_value()`.
- [x] **Найдено mypy (не было в постановке):** `Settings()` без аргументов требовал плагин `pydantic.mypy` — добавлен в `[tool.mypy] plugins` (`pyproject.toml`); без него mypy не понимает, что поля читаются из env, и требует их как обязательные параметры конструктора.
- [x] **Найдено mypy:** `date_extractors` без явной аннотации схлопывался в `list[object]` — добавлена `list[DateExtractor]`.
- [x] **Реальный пробел в `S3Gateway` (этап 6):** у класса не было `close()` вообще, хотя `boto3`-клиент его поддерживает (закрывает пул соединений). Добавлен `S3Gateway.close()` — небольшая, но настоящая правка уже закрытого этапа.
- [x] **Устаревший тест:** `tests/test_scaffold.py::test_entry_point_stub` проверял, что `main()` бросает `NotImplementedError` (заглушка этапа 1). Заменён на `test_main_fails_fast_without_required_settings` — доказывает fail-fast (`ValidationError` от pydantic) без обязательных переменных окружения, не трогая сеть/потоки.

### 10.3 `api/app.py`

```python
class ScanWorkerLike(Protocol):
    """Узкий интерфейс воркера, который нужен API — не импортирует ScanWorker из main.py."""

    last_scan_at: datetime | None

    def request_rescan(self) -> None: ...


def create_app(*, repo: StateRepository, worker: ScanWorkerLike) -> FastAPI:
    """Три эндпоинта; вся логика — прямые вызовы repo/worker, без бизнес-правил."""
```

- [x] `GET /health` → `{"status": "ok", "last_scan_at": worker.last_scan_at.isoformat() if worker.last_scan_at else None}`.
- [x] `GET /status` → `{"counts": repo.count_by_status(), "recent": repo.get_recent(20)}` — `FileState` сериализуется FastAPI сам через `jsonable_encoder`.
- [x] `POST /rescan` → `worker.request_rescan()`; `return {"status": "triggered"}`.
- [x] Все три — обычные `def`, не `async def`.
- [x] Аутентификации нет.

### 10.4 Тесты

`tests/test_main.py` (11 тестов):
- [x] `run()` в фоновом потоке + `stop()` → поток завершается (`join(timeout=...)`, `is_alive() is False`).
- [x] `request_rescan()` прерывает `wait()` немедленно (< 1 с при `scan_interval_seconds=60`).
- [x] `last_scan_at` обновляется после каждого цикла.
- [x] Исключение из `pipeline.run_cycle()` не убивает поток — следующий цикл происходит.
- [x] `DryRunS3Gateway`/`DryRunLmsClient`: методы не бросают, `verify()` возвращает `True`, `close()` не бросает.

`tests/api/test_app.py` (6 тестов, `fastapi.testclient.TestClient`, `StateRepository` настоящий на `tmp_path`, воркер — лёгкий тестовый дубль):
- [x] `GET /health` без предшествующих циклов → `last_scan_at: null`; после — `.isoformat()`.
- [x] `GET /status` → `counts`/`recent` соответствуют состоянию `StateRepository`; `recent` ограничен 20 записями.
- [x] `POST /rescan` → `200 {"status": "triggered"}`, `request_rescan()` вызван ровно один раз.

### Definition of Done (этап 10)

- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 221/221 тестов.
- [x] **Ручная проверка выполнена по-настоящему** (не просто curl `/health`): `uv run video-uploader` с `DRY_RUN=true` в фоне — поднялся, `/health`/`/status`/`/rescan` ответили. Добавлен реальный видеофайл (стабильный по mtime) в тестовую папку группы → `POST /rescan` → `GET /status` показал полный проход `discovered → uploaded → registered` (dry-run, без архивации, файл остался на месте — ровно как задумано решением этапа 8). Проверены логи (`RotatingFileHandler`, кириллица в путях через `encoding="utf-8"` — без искажений). `kill -TERM` → uvicorn корректно поймал сигнал, лог показал `Shutting down → Application shutdown complete → Finished server process`, порт освобождён, процесс полностью завершился (значит `worker_thread.join()` в `finally` тоже отработал, не завис).
- [x] Ревью Claude пройдено (код и тесты написаны Claude по вашей просьбе).
- [ ] Коммит — на вашей стороне.

---

## Этап 11 — Поставка (Docker, README, smoke-скрипт, документация) ← ТЕКУЩИЙ

**Цель:** последний этап — код пайплайна больше не меняется (этапы 2–10 закрыты). Здесь только упаковка: `Dockerfile`, `docker-compose.yml`, ручной `scripts/smoke_s3.py`, и документация (`README.md`, `.docs/basic_doc.md`, `.docs/API_doc.md`). Решать почти нечего — форма Docker-сборки и compose уже полностью специфицирована в CLAUDE.md (раздел Runtime Environment), это транскрипция, не проектирование.

**Затрагиваемые файлы:** `Dockerfile`, `docker-compose.yml`, `.dockerignore` (не было — нужен для чистого build context), `scripts/smoke_s3.py`, `README.md`, `.docs/basic_doc.md`, `.docs/API_doc.md`.

### Решения

1. **Multi-stage `Dockerfile`**: builder-этап (`uv sync --frozen --no-dev`, сначала только `pyproject.toml`+`uv.lock` для кэша слоя зависимостей, потом код) → финальный этап копирует `.venv` + `video_uploader/` от непривилегированного пользователя `uid 1000`. Оба этапа — на `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, как явно указано в CLAUDE.md.
2. **`HEALTHCHECK` — в `docker-compose.yml`, не в `Dockerfile`.** CLAUDE.md перечисляет его именно в bullet про docker-compose («TZ=...; restart: unless-stopped; HEALTHCHECK → GET /health»), Dockerfile-bullet про него не упоминает. Через `python -c "...urllib.request..."`, не `curl` — на `bookworm-slim` curl не гарантирован, python есть точно (это python-образ).
3. **`ports:` в compose — добавляю, хотя CLAUDE.md явно не перечисляет** (только тома/TZ/restart/healthcheck): без публикации порта `API_PORT` наружу LXC HTTP API недостижим даже из «Tech/Admin-сегмента», а CLAUDE.md прямо говорит, что доступ оттуда должен быть. Если не согласны — уберу, `HEALTHCHECK` при этом всё равно работает (он бьёт внутри контейнерной сети, порт наружу не нужен).
4. **`env_file: .env` в compose**, а не построчный `environment:` на 20+ переменных — тот самый `.env`, что рядом с `docker-compose.yml` (создаётся из `.env.example`), автоматически и для подстановки `${TZ_NAME}` в самом YAML, и для инъекции всех переменных в контейнер.
5. **`scripts/smoke_s3.py` — не часть пакета, не под pytest**, обычный скрипт вне `mypy --strict`/CI-гейта (CLAUDE.md: «вне pytest»). Читает `Settings()`, поднимает `S3Gateway` как в `main.py`, грузит маленький тестовый объект под префиксом `smoke-test/`, проверяет `verify()`, кладёт манифест, затем удаляет тестовый объект напрямую через `boto3` (у `S3Gateway` нет и не должно быть `delete` — сервис в рантайме никогда не удаляет; это ограничение про исходники на шаре, не про тестовые объекты в S3, поэтому в ad hoc-скрипте прямой `delete_object` уместен).
6. **`.dockerignore`** — исключает то же, что и `.gitignore` (venv/кеши/IDE), плюс `.git/`, `tests/`, `.docs/` — тестам и документации незачем попадать в build context прод-образа.

### 11.1 `Dockerfile`

- [x] Builder-стадия: `WORKDIR /app`; сначала `COPY pyproject.toml uv.lock ./`, `uv sync --frozen --no-dev --no-install-project` (кэш зависимостей отдельным слоем); затем `COPY video_uploader ./video_uploader` + `README.md`, `uv sync --frozen --no-dev`.
- [x] Финальная стадия: тот же базовый образ; `groupadd`+`useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser`; `COPY --from=builder --chown=appuser:appuser /app /app`; `USER appuser`; `ENV PATH="/app/.venv/bin:$PATH"`; `CMD ["video-uploader"]`.

### 11.2 `docker-compose.yml`

- [x] `services.video-uploader`: `build: .`; `restart: unless-stopped`; `env_file: .env`; `environment: TZ: ${TZ_NAME:-Europe/Kaliningrad}`; `volumes: /mnt/video:/mnt/video, ./data:/data, ./config:/app/config:ro`; `ports: "${API_PORT:-8090}:8090"`; `healthcheck` через `python -c "...urlopen('http://localhost:'+os.environ.get('API_PORT','8090')+'/health')..."`.
- [x] Синтаксис проверен `docker compose config` — валиден, все подстановки резолвятся.

### 11.3 `.dockerignore`

- [x] `.git/`, `.github/`, `.claude/`, `.docs/`, `.idea/`, `tests/`, `__pycache__/`, `*.py[cod]`, `.venv/`, `dist/`, `build/`, `*.egg-info/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.env`, `data/`, `.DS_Store`.

### 11.4 `scripts/smoke_s3.py`

- [x] `Settings()` → `S3Gateway(...)` (реальные креды из `.env`, не dry-run); ключ `f"smoke-test/{uuid4().hex}.txt"`; `upload_video`/`put_manifest`/`verify` с маленьким временным файлом (`tempfile`); печать результата на каждом шаге; `delete_object` в конце напрямую через `boto3.client("s3", ...)` с теми же параметрами подключения (и для видео-ключа, и для манифест-ключа).
- [x] `if __name__ == "__main__":` — не в `[project.scripts]`, запускается `uv run python scripts/smoke_s3.py`.
- [x] `ruff`/`mypy` чистые и на этом файле (хотя формально вне обязательного гейта `mypy video_uploader`).

### 11.5 Документация

- [x] `.docs/basic_doc.md` — структура проекта, технологии (где/почему), паттерны (где/почему), сводка по доработке (каналы логирования, новые папки сканирования, другое хранилище), как пользоваться (настройки, деплой, S3-ключи, интеграция LMS). **Заполнено напрямую** (документация, не код — не требует цикла постановка → пишете сами).
- [x] `.docs/API_doc.md` — все три HTTP-эндпоинта сервиса с примерами запрос/ответ. **Заполнено напрямую**, на основе реального ручного прогона с этапа 10.

### Definition of Done (этап 11)

- [x] **`docker compose build`/`up` — проверено 2026-07-17.** Пользователь запустил Docker локально, сборка и запуск прогнаны по-настоящему: `docker compose up -d --build` собрал образ и поднял контейнер в статусе `healthy`. `GET /health`, `GET /status`, `POST /rescan` отвечают корректно. Дымовой тест пайплайна: тестовый видеофайл в папке группы → `/rescan` → сервис нашёл файл, распознал дату по имени, замэтчил группу/slug, посчитал sha256, собрал S3-ключ, прошёл upload → verify → register → archive в `DRY_RUN=true` (реальных вызовов к S3/LMS не было, всё видно в файловом логе как `dry-run: ... пропущен`), `/status` показал файл в статусе `registered`. Единственная накладка — на исходной машине `/mnt/video` из `docker-compose.yml` не был расшарен в Docker Desktop (путь просто не существовал), для теста источник видео временно подменялся на локальную папку через `docker-compose.override.yml`; в проде эта переменная указывает на реально примонтированную SMB-шару, override-файл в тесте использовался только локально и в репозиторий не попал.
- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 221/221 тестов (новые файлы вне `video_uploader/` гейт не задели).
- [x] JSON-примеры в `.docs/API_doc.md`/`.docs/basic_doc.md` проверены программно на валидность (`json.loads` по всем блокам) — нашёл и поправил одну свою опечатку (`245_681_302` — синтаксис Python, не JSON).
- [x] Ревью Claude пройдено (код и документация написаны Claude по вашей просьбе).
- [x] Коммит — сделан вами через PyCharm (коммит `8b2183d` «Этап 10. Документация» на ветке `stage-10`), не отдельно под этап 11 — по факту содержимого это ровно файлы этого раздела.

---

## Итог: весь проект смержен в `main`

**2026-07-17.** PR #4 (`stage-10 → main`) смержен на GitHub, коммит `0048058`. Локальная `main` обновлена (`git merge --ff-only origin/main`), полный quality gate прогнан **прямо на `main`**: `ruff format --check` + `ruff check` + `mypy --strict video_uploader` + `pytest` — чисто, **221/221 тестов**.

Единственный конфликт по пути (в `.docs/CLAUDE.md` — git не распознал переименование корневого `CLAUDE.md`, конфликтовал только отсутствующий перевод строки в конце файла, содержимое было побайтово идентично) разрешён локально дважды (пробный мердж, затем реальный на `stage-10` перед пушем) — оба раза одинаково, оба раза с зелёным gate после.

Все 11 этапов исходного плана закрыты, включая финальную проверку Docker-сборки (см. п. 11.4 выше — реальный `docker compose up --build` и дымовой прогон пайплайна в DRY_RUN прошли успешно). Поставка полностью завершена; README.md написан и покрывает установку, настройку, DRY_RUN и деплой.

---

## Доп. задача — `DRY_RUN_LMS_LIVE` (реальная регистрация в LMS при сухом прогоне) ← ТЕКУЩИЙ

**Дата:** 2026-07-21. **Контекст:** проект полностью поставлен (см. «Итог» выше); эндпоинт `fs-lms` (`POST /wp-json/fs-lms/v1/videos`) теперь существует, и `DRY_RUN=true` больше не обязан подменять LMS-регистрацию заглушкой — нужна возможность гонять `DRY_RUN=true` с реальным вызовом плагина (проверить матчинг занятия по дате/времени на тестовом курсе), не трогая при этом реальный S3 и не архивируя исходники.

**Цель:** новый независимый флаг `DRY_RUN_LMS_LIVE` (default `false`). При `DRY_RUN=true` и `DRY_RUN_LMS_LIVE=true` — LMS-регистрация идёт настоящим `LmsClient` (реальный HTTP + HMAC), S3-загрузка и архивация остаются заглушками, как и раньше. При `DRY_RUN=false` флаг не имеет смысла (LMS и так настоящий) — сервис не обязан на него смотреть, но и падать из-за него не должен.

**Затрагиваемые файлы:** `video_uploader/config.py`, `video_uploader/main.py`, `.env.example`, `.docs/CLAUDE.md` (раздел Configuration + LMS REST), `tests/test_config.py`, `tests/test_main.py`.

### Решения, принятые в постановке (если не согласны — обсуждаем до кода)

1. **Название и семантика** — `DRY_RUN_LMS_LIVE: bool = False` в `Settings`, рядом с `dry_run` (секция «Флаги»). Существующий `DRY_RUN` не трогаем и не переименовываем — обратная совместимость полная, дефолтное поведение не меняется.
2. **Ветвление — в `main()`, не в `Pipeline`.** Как и раньше, `Pipeline` ничего не знает про `DRY_RUN`/`DRY_RUN_LMS_LIVE` — только про Protocol `RegistrationClient`. Выбор конкретной реализации — целиком забота composition root.
3. **Вынести выбор gateway/client в отдельные функции** `_build_s3_gateway(settings) -> UploadGateway` и `_build_lms_client(settings) -> RegistrationClient` (module-level функции в `main.py`, рядом с `DryRunS3Gateway`/`DryRunLmsClient`) — сейчас это заинлайнено в `main()`, а `main()` целиком не тестируется (блокируется на `uvicorn.run`). Вынесенные функции — тестируемая единица без потоков/сети.
4. **Логика `_build_lms_client`:**
   ```python
   def _build_lms_client(settings: Settings) -> DryRunLmsClient | LmsClient:
       if settings.dry_run and not settings.dry_run_lms_live:
           return DryRunLmsClient()
       return LmsClient(settings.lms_base_url, settings.lms_hmac_secret.get_secret_value())
   ```
   `_build_s3_gateway` — та же форма, но `dry_run_lms_live` не участвует в условии (S3 всегда заглушка при `dry_run=True`, новый флаг S3 не касается).
5. **Архивация не меняется** — `_cleanup` в `pipeline.py` по-прежнему смотрит только на `self._dry_run` (не на новый флаг): раз S3-загрузка фейковая, реального файла в бакете нет, и переносить исходник в архив нельзя, даже если LMS-регистрация была настоящей. `pipeline.py` эта задача не трогает вообще.
6. **`DRY_RUN_LMS_LIVE=true` без `DRY_RUN=true`** — не ошибка валидации, просто не имеет эффекта (LMS и так настоящий). Отдельного doc/предупреждения не нужно, но стоит закрыть тестом (п. ниже), чтобы поведение не расползлось при будущем рефакторинге.

### Задачи

- [x] `config.py`: новое поле `dry_run_lms_live: bool = Field(default=False)` — в секции «Флаги», сразу после `dry_run`.
- [x] `main.py`: функции `_build_s3_gateway(settings: Settings) -> DryRunS3Gateway | S3Gateway` и `_build_lms_client(settings: Settings) -> DryRunLmsClient | LmsClient` по решениям 3–4; `main()` использует обе функции вместо инлайн `if settings.dry_run: ... else: ...` (текущий блок `main.py:112-125`).
- [x] `.env.example`: новая строка `DRY_RUN_LMS_LIVE=false` сразу под `DRY_RUN=false`, с комментарием («при `DRY_RUN=true` — регистрировать видео в LMS по-настоящему, S3 и архивация остаются заглушками; для проверки матчинга занятия без реальной загрузки видео»).
- [x] `.docs/CLAUDE.md`, таблица Configuration: новая строка `DRY_RUN_LMS_LIVE` рядом с `DRY_RUN`.
- [x] `.docs/CLAUDE.md`, раздел «LMS REST (push)», последний абзац («До его появления используется `DRY_RUN=true`...») — обновлён: эндпоинт уже есть, `DRY_RUN_LMS_LIVE=true` включает реальную регистрацию при сухом прогоне.
- [x] `tests/test_config.py`: `dry_run_lms_live` по умолчанию `False`; переопределяется через env `DRY_RUN_LMS_LIVE=true` → `True`.
- [x] `tests/test_main.py`, новый класс `TestBuildGateways`:
  - `dry_run=False` → `_build_lms_client` возвращает `LmsClient` независимо от `dry_run_lms_live`; `_build_s3_gateway` возвращает `S3Gateway`.
  - `dry_run=True, dry_run_lms_live=False` (default) → `DryRunLmsClient` (текущее поведение не сломалось).
  - `dry_run=True, dry_run_lms_live=True` → `_build_lms_client` возвращает `LmsClient`; `_build_s3_gateway` всё равно возвращает `DryRunS3Gateway` (S3 флаг не касается).
  - Реальной сети/HTTP-вызовов в тестах нет — `LmsClient.__init__` только собирает `httpx.Client`, соединение не открывает.

### Definition of Done

- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 224/224 тестов.
- [ ] Ручная проверка обоих режимов сухого прогона (реальный fs-lms/тестовый курс) — см. `.docs/basic_doc.md`, раздел 5.7 «Проверка обоих режимов сухого прогона». Не выполнялась в рамках этой сессии — нужен доступ к тестовому/staging fs-lms.
- [x] Ревью Claude — код и тесты написаны Claude по вашей прямой просьбе («реализуй задачи самостоятельно»).
- [ ] Коммит — на вашей стороне.

---

## Доп. правка — покрытие каждого шага пайплайна логами (по вашей просьбе)

**Дата:** 2026-07-21. Аудит по запросу «убедись, что каждый шаг логируется» нашёл реальный пробел: событие `VideoDiscovered` было заведено в домене ещё на этапе 2 (`domain/events.py`) и покрыто тестами `test_events.py`, но `pipeline.py` (этап 8) его никогда не публиковал и не логировал обнаружение файла — единственный шаг из докстринга `Pipeline` (`scan → stability → dedup → metadata → resolve → upload → verify → register → cleanup`) без своего лога/события. Заодно не было явного лога на успешный `verify` и на `skipped_old`.

**Изменения:**

- `state/repository.py`: `StateRepository.discover()` теперь возвращает `tuple[int, bool]` (`file_id`, `is_new`) — иначе pipeline не мог бы отличить «файл только что впервые увиден» от «уже видели на прошлых циклах» и логировал/публиковал бы `VideoDiscovered` на каждом цикле сканирования (спам, файл может неделю висеть в `discovered`, если не проходит стабильность). Обновлены все вызовы `discover()` (`pipeline.py`, тесты).
- `pipeline.py`:
  - `run_cycle`: при `is_new=True` — `logger.info("видео обнаружено: %s", ...)` + `events.publish(VideoDiscovered(...))`.
  - Ожидание стабильности: `logger.debug("файл ещё дописывается, ждём стабильности: %s", ...)` — DEBUG, не INFO, чтобы не шуметь в проде на каждом цикле по каждому ещё не устоявшемуся файлу.
  - `skipped_old`: `logger.info("видео пропущено (старше %s дней): %s", ...)` — раньше переход в БД был, а лога не было.
  - Успешный `verify`: `logger.info("видео верифицировано в S3: %s", s3_key)`.
- Теперь у всех 7 доменных событий (`VideoDiscovered`, `VideoUploaded`, `VideoRegistered`, `VideoArchived`, `VideoFailed`, `GroupUnmapped`, `DateFallback`) есть ровно одна точка публикации в `pipeline.py`, и каждый значимый шаг (обнаружение, стабильность, дедуп, дата, skip_old, resolve, upload, verify, register, cleanup, ошибка) пишет что-то в лог — INFO на успех, WARNING на аномалии (`DateFallback`, `GroupUnmapped`), DEBUG на ожидание, `logger.exception` на сбой.
- Тесты: `tests/state/test_repository.py` (новый `is_new` тест), `tests/test_pipeline.py` (`TestHappyPath` проверяет полный набор INFO-сообщений и порядок из 4 событий начиная с `VideoDiscovered`; `TestStability` проверяет, что `VideoDiscovered` публикуется один раз даже за два цикла подряд, и что есть DEBUG-лог; `TestSkipOlderThanDays` проверяет новый INFO-лог), `tests/api/test_app.py` (обновлён вызов `discover()` под новую сигнатуру).

**Definition of Done:**

- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 225/225 тестов.
- [x] Ревью Claude — код и тесты написаны Claude по вашей прямой просьбе.
- [ ] Коммит — на вашей стороне.

---

## Доп. правка — найден и исправлен реальный краш `LokiHandler`, унификация логов с `fs-adsync`

**Дата:** 2026-07-21. По жалобе на прод-ошибку (`tail` лога `/opt/video-uploader/data/logs/*.log` на `VideoUpdate`) и на сильное расхождение вида логов со вторым сервисом (`/Users/daniil/Python/AdSync`).

**Найденный баг (не косметика — реально роняет фоновый воркер):** `LokiHandler.emit()` ловил только `except httpx.HTTPError`. Если внутренний `httpx.Client` уже закрыт (`self._client.close()` вызван, например, штатным `logging.shutdown()` на выходе процесса), `httpx` бросает **`RuntimeError("Cannot send a request, as the client has been closed.")`** — это не подкласс `httpx.HTTPError`, старый `except` его не ловил. Дальше по цепочке: `logger.exception(...)` в `pipeline.py::_fail` падает с этим `RuntimeError` → пробрасывается вверх до `ScanWorker.run()`, где ВТОРОЙ вызов `logger.exception("необработанная ошибка цикла сканирования")` **тоже** падает на том же `RuntimeError` (клиент всё ещё закрыт) — и на этот раз ловить некому: исключение вылетает из `ScanWorker.run()` целиком и **фоновый поток сканирования молча умирает** (не daemon-поток, но join уже не нужен: он просто прекращает существовать). HTTP API (`/health` и т.п.) продолжает отвечать «ок» — создаётся ложное впечатление, что сервис жив, хотя сканирование навсегда остановлено. Именно эта картина видна в присланном логе (`tail -50` показывает ровно эту цепочку: `_fail` → `logger.exception` → `loki.py:34 emit` → `RuntimeError`, повторённую как «During handling of the above exception»).

**Сверка с `fs-adsync` (`src/logging_setup.py`) показала эталонный паттерн**, который в `video-uploader` не был соблюдён:
- `except Exception: self.handleError(record)` вокруг **всего** push (это и есть контракт `logging.Handler.emit()` — падение хендлера логирования никогда не должно ронять вызывающий код), а не только сетевых `httpx.HTTPError`.
- `response.raise_for_status()` — иначе 4xx/5xx от самого Loki (не сетевая ошибка, а именно отказ сервера) молча игнорировались, `video-uploader` этого не делал вообще.
- Формат Loki-строки **без `asctime`** — Loki и так хранит свою метку времени (`timestamp_ns` = `record.created`), дублировать её текстом в самой строке избыточно; `video-uploader` использовал один и тот же формат для файла и для Loki.
- Лейбл `level` — lowercase (`record.levelname.lower()`), не `INFO`/`ERROR` как есть — единообразие с `fs-adsync` важно, оба сервиса пушат в один Grafana Loki, разный регистр лейбла ломает общие дашборды/алерты (`level="error"` не поймает `level="ERROR"`).
- `service` — параметр конструктора (`service: str = "fs-video-uploader"`), не модульная константа — как в `fs-adsync` (`service: str = "fs-adsync"`).

**Изменения:**

- `video_uploader/logging_setup/loki.py`: `except Exception` вместо `except httpx.HTTPError`; `response.raise_for_status()`; `level` — lowercase; `service` — конструкторский параметр.
- `video_uploader/logging_setup/factory.py`: раздельные форматы — `_FILE_FORMAT` (с `asctime`, для файла) и `_LOKI_FORMAT` (без `asctime`, для Loki); убран общий `-8s` паддинг `levelname` (косметика, для единообразия текста с `fs-adsync`, у которого паддинга нет).
- `.docs/CLAUDE.md`, раздел Logging & Notifications — короткое уточнение про унификацию с `fs-adsync` и что любая ошибка push уходит в `handleError`, не роняя пайплайн.
- Тесты `tests/logging_setup/test_loki.py`: новый прямой регресс-тест `test_emit_after_close_does_not_raise` (закрывает клиент, потом `emit()` — раньше падало с `RuntimeError`, теперь уходит в `handleError`); тест на 5xx-ответ Loki (`raise_for_status`); тест на кастомный `service`; существующий тест уровня обновлён под lowercase.
- Тесты `tests/logging_setup/test_factory.py`: новый тест `test_loki_formatter_omits_asctime` — форматтеры файла и Loki дают разный текст для одной записи.

**Definition of Done:**

- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 229/229 тестов.
- [x] Ревью Claude — код и тесты написаны Claude по вашей прямой просьбе.
- [ ] **Важно:** это исправление нужно раскатить на прод (`VideoUpdate`) отдельным деплоем — старый образ с этим багом всё ещё может «тихо» держать сканирование остановленным после следующего перезапуска/редеплоя, пока не будет обновлён. Проверить после раскатки: `docker compose logs -f` не показывает больше `RuntimeError: Cannot send a request` и `/status` продолжает обновлять `last_scan_at` спустя много циклов (не залипает).
- [ ] Коммит — на вашей стороне.

---

## Доп. правка — старт/стоп/heartbeat-логи, различие «полный успех» vs «зарегистрировано без матчинга», видимость окончательного отказа; unификация с `fs-adsync`

**Дата:** 2026-07-21. По итогам реального прогона на `VideoUpdate` (лог из предыдущей правки) всплыли два новых наблюдения:

1. **`LMS 400: missing s3_bucket or s3_key`** — не баг сервиса: в тестовом `.env`/`VU.env` `S3_BUCKET` был пустой строкой. Это `str`-поле без валидатора «пустое → ошибка» (в отличие от опциональных полей вроде `LOKI_URL`), пустая строка проходит `Settings` и уходит в `_build_lms_payload` как `"s3_bucket": ""` — плагин считает это отсутствующим полем. Для теста с `DRY_RUN_LMS_LIVE=true` `S3_BUCKET` всё равно нужен непустым, хотя S3 реально не трогается. Кода это не касается — чисто конфигурация.
2. Эта ошибка — `LmsRejectedError` (4xx) — по контракту CLAUDE.md permanent, ретраев не будет. `_fail(permanent=True)` сразу выставляет `attempts = MAX_ATTEMPTS`. На следующих циклах `_process()` тихо выходит на `if state.status == "failed" and attempts >= max_attempts: return` — **без единого лога**. Отсюда и «загрузил то же видео (тот же путь), лога не получил» — файл был не «не найден», а молча заблокирован реестром навсегда (по конструкции: `path` уникален, `sha256`-дедуп не выручает для статуса `failed`).

Дополнительно (прямой запрос): в текущих логах не видно, что сервис вообще жив/поднялся, и нет отдельного «success»-лога на полностью пройденный цикл файла (плагин принял и замэтчил видео).

**Сверка с `fs-adsync`** (`/Users/daniil/Python/AdSync`) показала: у него **уже есть** старт/стоп-логи (`main.py:110,211`) и чёткая семантика уровней (INFO/WARNING/ERROR по тому же принципу, что описан в CLAUDE.md AdSync, раздел Logging & Notifications), но **нет heartbeat** — единственный кандидат (лог числа заданий за тик) был осознанно закомментирован в последнем коммите (`ebc1bbb`) из-за шума (тикает каждые 3 с). Важно: AdSync **сознательно не заводит новых Loki-лейблов** (только `service`/`level`/`logger` — прямая цитата его CLAUDE.md) и не строит отдельных абстракций уведомлений (`EventBus`/`notifier` реверчены на этапе 8 их `Tasks.md`) — «просто логируем на нужном уровне, алерты — через Grafana поверх Loki». Поэтому унификация — **не** общий `event`-лейбл (это бы разошлось с их явным решением), а одинаковая архитектура хендлеров (уже сделано прошлой правкой) + одинаковая семантика уровней + добавление heartbeat в **оба** сервиса.

### Решения

1. **Heartbeat — не лейбл, а обычный INFO-лог** `сервис жив: реестр=<counts>` раз в `HEARTBEAT_INTERVAL_SECONDS` (новый флаг, default 3600). Не в `Pipeline`/`run_cycle` (это была бы логика на каждый цикл сканирования, `SCAN_INTERVAL_SECONDS` default 300 с — слишком часто) — в `ScanWorker` (`main.py`), которому и так принадлежит понятие «фоновый цикл потока». Источник цифр — уже существующий `StateRepository.count_by_status()`.
2. **Первый heartbeat не срабатывает мгновенно при старте**, а ждёт полный интервал — так же, как первый тик `_loop()` в `fs-adsync` (`while not stop.wait(interval): tick()` — сначала `wait`, потом тик). Раз старт уже подтверждён отдельным логом «запускается», немедленный heartbeat был бы дублирующим сигналом.
3. **Узкий Protocol `RegistryCounts`** (`count_by_status() -> dict[str, int]`) вместо завязки `ScanWorker` на весь `StateRepository` — тот же SOLID-I, что у `ScanWorkerLike` в `api/app.py`.
4. **`RegistrationClient.register()` теперь возвращает `bool` (`matched`)**, а не `None`. Раньше `LmsClient._log_match_status` логировал `matched: false` WARNING-ом без контекста файла (`video_uploader.lms.client`, только «занятие не найдено» без пути/ключа). Теперь транспортный слой (`lms/client.py`) только извлекает флаг (`_extract_matched`), а `pipeline.py` — единственное место, которое решает, что писать в лог, с полным контекстом (`video_file.path`, `s3_key`): `matched: true` → INFO «видео полностью обработано» (это и есть запрошенный success-лог на весь пройденный цикл файла); `matched: false` → WARNING «зарегистрировано, но занятие не найдено — нужна ручная привязка». `DryRunLmsClient`/`FakeLmsClient` — всегда `True` (dry-run по-прежнему «притворяется полным успехом»).
5. **Одноразовое предупреждение на файл, окончательно исчерпавший попытки** (`Pipeline._warned_exhausted_ids: set[int]`, по образцу `warned_folders` для `GroupUnmapped`, только на уровне экземпляра `Pipeline`, не одного `run_cycle`): при первом же повторном скане такого файла — WARNING «видео больше не будет обработано — исчерпаны попытки, нужно вмешательство администратора», дальше молчит (не спамит на каждый цикл). Плюс отдельный ERROR **в момент**, когда `attempts` достигает `MAX_ATTEMPTS` (`_fail`, рядом с публикацией `VideoFailed`, которая раньше была вообще без лога) — «видео окончательно не обработано после N попыток, повторных попыток не будет».
6. **Как разблокировать зависший `failed`-файл** (нет отдельного API/механизма, сознательно не строим один без вашего запроса): переименовать/перезалить файл под другим именем (дедуп по `sha256` не блокирует повторную обработку для статуса `failed`, только для `registered`/`archived`) **или** вручную удалить строку из `data/state.db` (`DELETE FROM files WHERE path = '...'`). Если нужен нормальный `POST /retry/{id}` — отдельная задача, скажите.

### Задачи (video-uploader)

- [x] `config.py`: `heartbeat_interval_seconds: int = Field(default=3600, ge=1)`.
- [x] `main.py`: `RegistryCounts` (Protocol); `ScanWorker` принимает `repo`/`heartbeat_interval_seconds`, метод `_maybe_heartbeat()`; старт-лог после `configure_logging`, стоп-лог в конце `finally`; `DryRunLmsClient.register()` → `bool` (всегда `True`).
- [x] `lms/client.py`: `register()` → `bool`; `_log_match_status` → `_extract_matched` (только возвращает флаг, не логирует).
- [x] `pipeline.py`: `RegistrationClient.register()` → `bool`; `_process()` — matched/unmatched INFO/WARNING вместо общего «зарегистрировано»; `_replay_duplicate()` — та же формулировка success для дубликатов; `_fail()` — ERROR при достижении `MAX_ATTEMPTS`; `_warned_exhausted_ids` + одноразовый WARNING при скипе исчерпанного файла.
- [x] `.env.example`, `.docs/CLAUDE.md` (таблица Configuration + раздел Logging & Notifications) — `HEARTBEAT_INTERVAL_SECONDS`, уровни, старт/стоп, heartbeat.
- [x] Тесты: `tests/lms/test_client.py` (matched → bool, без caplog на этом уровне), `tests/test_pipeline.py` (`FakeLmsClient.register_matched`, обновлён текст в `TestHappyPath`, новый `TestUnmatched`, регресс-тесты в `TestRegisterRejected`/`TestMaxAttemptsExhausted` на оба новых лога), `tests/test_main.py` (`FakeRegistryCounts`, `make_worker()`, новый `TestHeartbeat`), `tests/test_config.py` (default + границы `heartbeat_interval_seconds`).

### Definition of Done (video-uploader)

- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 234/234 тестов.
- [x] Ревью Claude — код и тесты написаны Claude по вашей прямой просьбе.
- [ ] На тестовом хосте: поставить непустой `S3_BUCKET`, повторить прогон с `DRY_RUN_LMS_LIVE=true` — ожидается либо `видео полностью обработано` (если занятие в fs-lms нашлось), либо явный WARNING про ненайденное занятие — но не тишина.
- [ ] Коммит — на вашей стороне.

### Параллельно: аналогичная доработка `fs-adsync` (второй репозиторий)

Отдельный git-репозиторий (`/Users/daniil/Python/AdSync`), свой `CLAUDE.md`/`Tasks.md` — детали см. там же (heartbeat через `JobRepository.status_counts()` + третий `_loop()`-поток по образцу jobs/reconcile, `HEARTBEAT_INTERVAL_SECONDS`, default 3600). Старт/стоп-логи и уровни у него уже были в порядке, править не потребовалось.

---

## Доп. правка — `LokiHandler` пересобирает клиент сам; устранён конфликт сигналов uvicorn/наш shutdown

**Дата:** 2026-07-21. Продовый лог (`VideoUpdate`) показал: `RuntimeError: Cannot send a request, as the client has been closed.` продолжает возникать **уже с исправленным** `except Exception` из предыдущей правки — теперь она честно ловится и уходит в `handleError` (краша и смерти потока сканирования больше нет — подтверждено логом: `видео обнаружено` → `видео загружено` → `видео верифицировано` → регистрация → cleanup прошли до конца, несмотря на непрерывный отказ Loki на каждом шаге), но **сама доставка в Loki оставалась полностью потерянной до конца жизни процесса** — раз клиент закрыт, `except httpx.HTTPError`/`except Exception` не открывают его заново.

**Расследование причины закрытия (важное отличие от `fs-adsync`, у которого этот баг не наблюдается):**

- `httpx.Client._state = ClientState.CLOSED` выставляется **только** в `Client.close()`/`__exit__` (проверено по исходникам `httpx==0.28.1` — `grep` по всем присвоениям `_state`, других путей нет).
- В коде `LokiHandler.close()` явно не вызывается нигде, кроме самого метода `close()`; единственный автоматический вызывающий — `logging.shutdown()` (`atexit`, при завершении интерпретатора).
- Но трейс продового лога показывал сбой **посреди обычной работы** — стек вызова оканчивается на `ScanWorker.run() → self._pipeline.run_cycle()`, то есть поток сканирования в этот момент активно исполняется, а не находится в `finally`-блоке `main()` после `worker_thread.join()`. Значит закрытие происходит не через штатный путь нашего же graceful shutdown.
- **Структурное отличие от `fs-adsync`:** там `uvicorn.Server(...).run()` запускается в отдельном daemon-потоке, а сигналами управляет собственный `signal.signal()` в `main()` — с их же комментарием «uvicorn пропускает установку своих обработчиков сигналов, если запущен не из главного потока» (подтверждено чтением `uvicorn/server.py::Server.capture_signals()`: `if threading.current_thread() is not threading.main_thread(): yield; return`). В video-uploader `uvicorn.run(app, ...)` вызывался **в главном потоке** — уvicorn сам ставил `signal.signal()` на SIGTERM/SIGINT (через `capture_signals()`), **параллельно** с нашим собственным `finally: worker.stop(); worker_thread.join(); ...`. Двух независимых механизмов остановки в одном процессе достаточно, чтобы объяснить сбой, не сводящийся к тривиальной гонке, которую видно в статическом коде — конкретный триггер (например, повторный/быстрый SIGTERM при `docker compose restart`) не подтверждён вживую, но устранение самой возможности конфликта — правильный шаг независимо от точного триггера.

**Решения:**

1. **`LokiHandler` — самовосстановление**: `emit()` теперь проверяет `self._client.is_closed` и прозрачно пересобирает `httpx.Client` (`_build_client()`) перед отправкой. Не устраняет причину закрытия, но гарантирует, что доставка в Loki восстанавливается на следующей же записи, а не теряется навсегда до перезапуска контейнера. Тот же паттерн применён в `fs-adsync` (`src/logging_setup.py`) — на случай, если там тоже когда-нибудь проявится (по объяснённой выше причине — маловероятно, но защита дешёвая).
2. **`main.py` — архитектурное исправление, устраняющее саму возможность конфликта**: uvicorn теперь поднимается через `uvicorn.Server(uvicorn.Config(app, ...)).run()` в отдельном `daemon=True`-потоке (как `worker_thread`, тоже теперь `daemon=True`); сигналами SIGTERM/SIGINT управляет только наш `signal.signal(handle_signal)` в главном потоке — один явный, контролируемый путь остановки, один в один как в `fs-adsync`. `handle_signal` устанавливает `stop`-Event, `worker.stop()` и `server.should_exit = True`; главный поток блокируется на `stop.wait()`, затем джойнит оба потока с таймаутом `_SHUTDOWN_JOIN_TIMEOUT_SECONDS = 10.0` (раньше `worker_thread.join()` был без таймаута — теоретически мог зависнуть навечно, если `run_cycle()` застрянет на сетевом вызове без собственного таймаута).
3. **`log_config` uvicorn не трогаем** (в отличие от `fs-adsync`, который передаёт `log_config=None`) — баннер `INFO: Started server process...`/`Uvicorn running on...` в `docker logs` полезен и используется для диагностики (видно в присланных пользователем логах), убирать не за чем: связь была именно в том, из какого потока запускается `Server.run()`, а не в `log_config`.

### Задачи

- [x] `logging_setup/loki.py`: `_build_client()`, самовосстановление в `emit()` при `is_closed`.
- [x] `main.py`: `uvicorn.Server`/`uvicorn.Config` вместо `uvicorn.run()`; `api_thread`/`worker_thread` — оба `daemon=True`; собственный `signal.signal(SIGTERM/SIGINT, handle_signal)`; `stop`-Event; join с таймаутом 10 с.
- [x] Тест `tests/logging_setup/test_loki.py::test_emit_after_close_self_heals_and_delivers` переписан под новое поведение (раньше проверял только «не падает», теперь — что запись реально доставляется после пересборки).
- [x] Синхронно в `fs-adsync`: тот же self-heal в `src/logging_setup.py::LokiHandler` + новый тест `test_emit_after_close_self_heals_and_delivers` в `tests/test_logging_setup.py` (у него архитектура уже была правильная — потоковая модель менять не потребовалось).
- [x] **Ручная проверка graceful shutdown выполнена по-настоящему** (не просто чтение кода): локальный запуск с `DRY_RUN=true`, `SCAN_INTERVAL_SECONDS=5` → `GET /health` (`last_scan_at` уже проставлен — воркер реально работает в фоне) → `GET /status` → `kill -TERM <pid>`. Результат в файловом логе: `получен сигнал 15, начинаю остановку` → (uvicorn сам корректно завершился: `Shutting down` → `Application shutdown complete` → `Finished server process`) → `fs-video-uploader остановлен`. Процесс полностью завершился (`ps aux` пуст) за < 2 секунд, без зависаний, без гонки между uvicorn и нашим shutdown.

### Definition of Done

- [x] video-uploader: `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 234/234.
- [x] fs-adsync: `uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest` — чисто, 90/90.
- [x] Ревью Claude — код и тесты написаны Claude по вашей прямой просьбе («да, сделай сейчас»).
- [ ] На проде: раскатить обновлённый образ, понаблюдать несколько дней — если `RuntimeError: Cannot send a request` в логе больше не появляется вообще (не только не роняет поток, а вообще не возникает), это будет косвенным подтверждением диагноза выше. Если продолжит появляться даже с новой потоковой моделью — вернуться к более глубокому расследованию (например, добавить `logging.raiseExceptions`-трейс прямо в момент `close()`, если он всё же случится).
- [ ] Коммит — на вашей стороне (в обоих репозиториях).

---

## Доп. правка — `event` третьим лейблом Loki-стрима для доменных событий

**Дата:** 2026-07-22. По итогам аудита `.docs/Events-Logging.md` (советы 3 и 4) — сейчас событие в Grafana
приходится ловить регекспом по русскому тексту сообщения, что ломается при любой правке формулировки.
Выбран вариант «добавить `event` третьим лейблом Loki-стрима» (а не только в текст строки).

**Это меняет ранее зафиксированное решение** в `CLAUDE.md` (раздел Logging & Notifications):
«Новых Loki-лейблов не заводим... синхронизировано с `fs-adsync`». `event` — по факту фиксированный
набор из 7 значений (по числу типов событий `EventBus`), это не лейбл высокой кардинальности, поэтому
исключение оправдано, но решение больше не единое между сервисами, пока `fs-adsync` не получит такую же
правку (см. «Параллельно» ниже) — **до тех пор дашборды по `event` работают только для `fs-video-uploader`**.

### Решения

1. **Без единого источника имён — литеральная строка прямо в `extra` на каждом вызове.**
   Обсуждали словарь `EVENT_NAMES`/автовывод из имени класса — решили не делать: 7-9 вызовов не
   оправдывают отдельную абстракцию, было бы дублированием ради дублирования. Имя события — snake_case
   от имени класса, пишется вручную по месту: `video_discovered`, `video_uploaded`, `video_registered`,
   `video_archived`, `video_failed`, `group_unmapped`, `date_fallback`. Если позже строки разъедутся
   между собой (опечатка в одном из вызовов) — это ловится тестами (см. ниже), а не типами; на 7 именах
   риск признан приемлемым.
2. **`event` в `extra` только там, где рядом стоит `self._events.publish(...)`** — то есть ровно на
   7 типах событий шины. Остальные логи (heartbeat, dry-run-заглушки, `видео верифицировано в S3`,
   DEBUG-стабильность, старт/стоп и т.д. — см. таблицу «Значимые шаги вне EventBus» в
   `Events-Logging.md`) `event` не получают: они не завязаны на доменное событие.
3. **`VideoRegistered` логируется тремя разными текстами (matched / unmatched / дубликат) — все три
   несут один и тот же `event=video_registered`.** Отдельный маркер `matched=true/false` (совет 1 в
   `Events-Logging.md`) в этот раз **не делаем** — вне текущего запроса, при необходимости отдельная
   задача. `VideoUploaded` аналогично: обычная загрузка и дубликат по контенту — один `event`.
4. **`LokiHandler.emit`** — читает `getattr(record, "event", None)`; если атрибут есть, кладёт третьим
   ключом в `stream` рядом с `service`/`level`/`logger`; если атрибута нет (обычный лог без `extra`) —
   ключ `event` в `stream` вообще не появляется (не слать `"event": null` — это тоже был бы лишний
   лейбл-значение, пусть и одно).

### Задачи (video-uploader)

- [x] `domain/events.py`: стаб `EVENT_NAMES` убран (сделано пользователем); добавлен `extra` на
      `подписчик %r упал на событии %r` → `event_subscriber_error` (сверх исходного плана — для
      симметрии с остальными internal-ошибками).
- [x] `pipeline.py`: `extra={"event": "..."}` добавлен на все 9 точек рядом с `publish(...)`
      (`video_discovered`/`date_fallback`/`group_unmapped`/`video_uploaded` ×2/`video_registered` ×3/
      `video_archived`/`video_failed`) **плюс** на 5 внесобытийных логов, нужных для метрик:
      `registry_error`, `video_attempts_exhausted`, `video_skipped_old`, `video_verified`,
      `video_processing_error`. Dry-run-заглушки (`_cleanup`) сознательно не затронуты — не несут
      прод-сигнала.
- [x] `main.py`: `extra` на `service_started`, `heartbeat`, `scan_cycle_error`,
      `shutdown_signal_received`, `service_stopped`.
- [x] `scanner/scanner.py`: `extra={"event": "group_folder_read_error"}` на ошибке чтения папки группы.
- [x] `logging_setup/loki.py`: `emit()` читает `getattr(record, "event", None)`, кладёт третьим ключом
      в `stream_labels`, только если не `None`; докстринг модуля дополнен.
- [ ] Тесты `tests/logging_setup/test_loki.py` (`event` в `stream`/его отсутствие без `extra`) —
      **не сделаны в этом заходе** (был прямой запрос только на логи, без тестов).
- [ ] Тесты `tests/test_pipeline.py` (`caplog` на `record.event` по веткам) — **не сделаны**, аналогично.
- [x] `CLAUDE.md`, раздел Logging & Notifications: формулировка «Новых Loki-лейблов не заводим»
      заменена на описание `event`-лейбла, кардинальность ~19 значений, ссылка на полный список в
      `basic_doc.md`.
- [x] `Events-Logging.md`: советы 3 и 4 отмечены принятыми (дата, ссылка на эту правку и на
      `basic_doc.md`).
- [x] `basic_doc.md`: новый раздел 5.8 «Метрики и алерты в Grafana (лейбл `event`)» — таблица всех
      19 событий (собрана `grep`'ом по фактическому коду, не по плану), примеры LogQL, кандидаты на
      алерты.

### Definition of Done (video-uploader)

- [x] `uv run ruff format . && uv run ruff check . && uv run mypy video_uploader && uv run pytest` — чисто, 234/234 (без новых тестов на `event` — код не покрыт регрессией на конкретные строки-теги).
- [x] Ревью Claude — код и документация написаны Claude по прямой просьбе пользователя.
- [ ] Тесты на `event` — отдельная задача, если понадобится (см. выше).
- [ ] Коммит — на вашей стороне.

### Параллельно (отдельная сессия/репозиторий): `fs-adsync`

**Сделано 2026-07-22.** `fs-adsync` не имеет `EventBus`/доменных событий (реверчено на этапе 8 его
`Tasks.md`) — правка там не копипаста, а отдельное решение: свои строковые `event`-теги при вызовах
`logger.*` (25 значений — бизнес-исходы заданий/сверки + основная инфраструктура), без доменных
классов. Затронуты его `CLAUDE.md` (раздел Logging & Notifications), `src/logging_setup.py::LokiHandler`
(тот же приём — третий лейбл `stream` рядом с `service`/`level`, только при наличии `record.event`),
`.docs/basic_doc.md` (свой раздел «Метрики и алерты в Grafana») и `.docs/Events-Logging.md` (советы
3–6 отмечены принятыми). Подробности — его `.docs/Tasks.md`, «Пост-этап 9 — `event`-лейбл Loki-стрима».
Дашборд по `event` в Grafana теперь валиден для обоих сервисов; тесты на `event` там тоже не добавлены
в этом заходе (только код + документация, по прямой просьбе).
