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
