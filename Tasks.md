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
