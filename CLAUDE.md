# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`fs-video-uploader` — фоновый сервис, который переносит видеозаписи занятий с SMB-шары учебного центра в S3-хранилище Beget и регистрирует их в LMS (WordPress-плагин `fs-lms`).

Контекст среды:

- Занятие записывается в Яндекс Телемосте; преподаватель сохраняет файл записи в `\\dc.fs.loc\Shares$\Video\<Группа>` (имена групп кириллицей: `КЕГЭ-1`, `ОГЭ-1`, …). В рантайме сервиса шара смонтирована в `VIDEO_ROOT` (default `/mnt/video`); **подпапка = учебная группа**.
- Формат — `.webm`, имя вида `Встреча_в_Телемосте_08_07_26_16_04_45_—_запись.webm` (блок даты/времени начала: `ДД_ММ_ГГ_ЧЧ_ММ_СС`). Файл появляется копированием/скачиванием и в процессе растёт — трогать его можно только после проверки стабильности.
- После подтверждённой загрузки и регистрации исходник **не удаляется**, а перемещается в архивную подпапку `_uploaded` внутри папки своей группы (сервисная учётка `svc-video-upload` имеет права Modify). Очистка архива — ручная, администратором.
- Плагин получает при регистрации готовый блок `lms` с ID (группа / курс / преподаватель — состав задаёт админ в конфиге) и раскладывает видео строго по ним; человекочитаемые названия и ФИО в интеграции не участвуют.

Pipeline одного файла:

```
scan → stability → dedup (реестр) → metadata (дата) → resolve (папка группы → slug + блок lms)
     → upload (S3) → verify → register (LMS REST) → cleanup (перемещение исходника в архив)
```

Доменные события публикуются на значимых шагах (см. Observer ниже).

## Commands

```bash
uv sync                          # окружение + зависимости (включая dev)
uv run video-uploader              # локальный запуск сервиса
uv run pytest                    # тесты
uv run ruff format .             # автоформат (PEP 8)
uv run ruff check --fix .        # линт
uv run mypy src                  # проверка типов (strict)
docker compose -f docker/docker-compose.yml up -d --build   # прод-запуск
```

Обязательная проверка перед завершением любого этапа (должна проходить чисто):

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest
```

- **pip / poetry / pdm не использовать.** Только uv: зависимости добавлять через `uv add <pkg>` (dev: `uv add --dev <pkg>`); `uv.lock` коммитится.
- Новые зависимости — только после явного согласования с пользователем.

## Tech Stack

- Python 3.12+, менеджер — **uv** (`pyproject.toml` + `uv.lock`, src-layout)
- pydantic v2 + pydantic-settings — конфиг и внешние DTO с валидацией
- boto3 — S3 (Beget); httpx — LMS REST / Telegram / Loki
- sqlite3 (stdlib) — реестр состояния; 
- ORM SQLAlchemy 2.0
- PyYAML — `config/groups.yaml`
- FastAPI + uvicorn — тонкий HTTP-слой (`/health`, `/status`, `/rescan`)
- dev: pytest, ruff, mypy

## Code Style

- PEP 8 через `ruff format` + `ruff check`; line-length 100; конфиг в `pyproject.toml`
- `mypy --strict`; типы у всех параметров и возвращаемых значений
- ООП: логика в классах, зависимости — через конструктор; интерфейсы — `typing.Protocol` в `base.py` соответствующего пакета
- Доменные модели — frozen `dataclass(slots=True)`; конфиг и внешние DTO — pydantic
- Пути — только `pathlib.Path`
- `print` запрещён — только `logging` (логгеры `video_uploader.<module>`)
- Docstrings (Google style) на публичных классах и методах
- Никакого глобального изменяемого состояния и синглтонов; вся сборка зависимостей — в composition root (`main.py`)

## SOLID в этом проекте

- **S** — модуль отвечает за одно: scanner не знает про S3, gateway не знает про группы, репозиторий не знает про пайплайн.
- **O** — новая стратегия даты / лог-синк / резолвер = новая реализация Protocol + регистрация в фабрике; существующий код не правится.
- **L** — реализации Protocol полностью взаимозаменяемы: не сужать контракт, не бросать неожиданных исключений.
- **I** — интерфейсы узкие: `DateExtractor.extract(path) -> datetime | None`, а не «универсальный обработчик».
- **D** — `pipeline` зависит только от Protocol; boto3/httpx/sqlite3 живут только внутри Gateway/Client/Repository и подключаются в `main.py`.

## Architecture

| Модуль (`src/video_uploader/`) | Роль |
|---|---|
| `main.py` | Composition root: конфиг → сборка зависимостей → воркер (фоновый поток) + uvicorn; graceful shutdown по SIGTERM |
| `config.py` | `Settings` (pydantic-settings; источник — env/`.env`) |
| `domain/models.py` | `VideoFile`, `LessonMeta`, `UploadResult` — frozen dataclasses |
| `domain/events.py` | Доменные события + `EventBus` (Observer): `subscribe` / `publish` |
| `scanner/scanner.py` | Обход `VIDEO_ROOT/<группа>/*`, отбор кандидатов |
| `scanner/stability.py` | Проверка «файл дописан» |
| `metadata/base.py` | `DateExtractor` (Protocol) |
| `metadata/filename.py` | Дата из имени файла (regex с именованными группами, default под Телемост) |
| `metadata/filestat.py` | Fallback: mtime |
| `resolving/resolver.py` | `GroupResolver`: имя папки → `slug` + блок `lms` (`groups.yaml`) |
| `storage/key_builder.py` | Ключи S3 (видео + манифест) по соглашению — единственный источник |
| `storage/s3_gateway.py` | Adapter над boto3: multipart upload, put manifest, head/verify |
| `lms/client.py` | REST-клиент fs-lms (httpx): регистрация видео |
| `state/repository.py` | Repository над SQLite: реестр файлов и статусов |
| `notifications/telegram.py` | Подписчик EventBus: бизнес-уведомления в Telegram |
| `logging_setup/factory.py` | Фабрика лог-хендлеров из конфига (Strategy + Factory) |
| `logging_setup/loki.py`, `logging_setup/telegram.py` | Кастомные `logging.Handler` |
| `pipeline.py` | Оркестратор шагов обработки одного файла |
| `api/app.py` | FastAPI: `/health`, `/status`, `/rescan` — без бизнес-логики |

### Design Patterns (обязательные)

- **Strategy** — извлечение даты (`metadata/*`); лог-синки (каждый `logging.Handler` — стратегия вывода).
- **Observer** — `EventBus` в `domain/events.py`; издатель — pipeline, подписчики — `notifications/*`. События: `VideoDiscovered`, `VideoUploaded`, `VideoRegistered`, `VideoArchived`, `VideoFailed`, `GroupUnmapped`, `DateFallback`. EventBus — только для побочных эффектов (уведомления, метрики); критичный путь (реестр, S3, LMS) — явные вызовы, не события.
- **Factory** — `logging_setup/factory.py`; сборка стратегий из `Settings`.
- **Repository** — `state/repository.py`, единственная точка доступа к SQLite.
- **Adapter/Gateway** — `storage/s3_gateway.py`, `lms/client.py`.

Важно про Observer: следить за SMB-шарой событийно нельзя — inotify не работает поверх CIFS. Обнаружение файлов делается **опросом** по `SCAN_INTERVAL_SECONDS`; Наблюдатель живёт на уровне доменных событий, а не файловой системы. watchdog/inotify не предлагать.

Новые слои и паттерны не вводить без явного запроса пользователя.

## Contracts

### S3 (Beget)

- Endpoint: `https://s3.ru1.storage.beget.cloud`, регион `ru-1`, **path-style addressing** (`s3={"addressing_style": "path"}`).
- Имя бакета Beget автогенерирует с префиксом (вида `f6bcd57c2800-fs-video`) — берётся из `S3_BUCKET`, в коде не хардкодить.
- Соглашение о ключах (реализуется только в `key_builder.py`):

```
{S3_KEY_PREFIX}/{group_slug}/{yyyy}/{mm}/{yyyy-mm-dd}_{hh-mm}_{sha8}{ext}
пример: videos/kege-1/2026/07/2026-07-08_16-04_a1b2c3d4.webm
```

  - `group_slug` — из `groups.yaml`; `sha8` — первые 8 hex от sha256 файла; `ext` — оригинальное расширение lowercase.
  - В ключах допустимы только `[a-z0-9./_-]`; кириллица и пробелы запрещены.
- Рядом с каждым видео кладётся манифест `{video_key}.json` (UTF-8, `ContentType: application/json`) — бакет самоописывающий, LMS может свериться с ним без сервиса:

```json
{
  "schema": 2,
  "group_slug": "kege-1",
  "source_folder": "КЕГЭ-1",
  "lms": {"group_id": 3, "course_id": 42, "teacher_id": 7},
  "recorded_at": "2026-07-08T16:04:45+03:00",
  "original_name": "Встреча_в_Телемосте_08_07_26_16_04_45_—_запись.webm",
  "size_bytes": 123456789,
  "sha256": "…",
  "uploaded_at": "2026-07-14T21:00:05+00:00",
  "service": {"name": "fs-video-uploader", "version": "0.1.0"}
}
```

- `x-amz-meta-*` — **только ASCII**: `group-slug`, `recorded-at`, `sha256`, плюс зеркало блока `lms`: каждая пара кладётся как `x-amz-meta-lms-<key>` (символ `_` в ключе заменяется на `-`). Так плагин получает все ID одним `HEAD`-запросом, не скачивая манифест. Кириллица (`source_folder`) — только в манифест.
- `ContentType` по расширению: `.webm → video/webm`, `.mp4 → video/mp4`, `.mkv → video/x-matroska`.
- Multipart: `upload_file` + `TransferConfig` (threshold и chunk — 64 MiB). Верификация: `head_object` → `ContentLength == size_bytes`. ETag при multipart ≠ md5 — им не верифицировать.

### LMS REST (push)

```
POST {LMS_BASE_URL}/wp-json/fs-lms/v1/videos
Header: X-FS-uploader-Token: {LMS_uploader_TOKEN}
```

```json
{
  "s3_bucket": "…", "s3_key": "…", "manifest_key": "…",
  "group_slug": "kege-1",
  "lms": {"group_id": 3, "course_id": 42, "teacher_id": 7},
  "recorded_at": "2026-07-08T16:04:45+03:00",
  "size_bytes": 123456789, "sha256": "…", "duration_sec": null
}
```

- Идемпотентность — на стороне плагина, upsert по `s3_key`; повторная отправка безопасна.
- 200/201 → `registered`; 5xx и сетевые ошибки → ретраи с экспоненциальным backoff в следующих циклах; прочие 4xx → `failed` + ERROR, без ретраев.
- Эндпоинта в fs-lms пока нет — он реализуется отдельно в репозитории плагина. До его появления используется `LMS_DRY_RUN=true`: шаг register логируется и считается успешным.

### config/groups.yaml

```yaml
groups:
  "КЕГЭ-1":
    slug: kege-1
    lms:               # произвольные ID для плагина; сервис их не интерпретирует
      group_id: 3
      course_id: 42
      teacher_id: 7
```

- Ключ — точное имя подпапки в `VIDEO_ROOT` (кириллица допустима).
- `slug`: уникален, `^[a-z0-9]+(-[a-z0-9]+)*$` — единственное поле, которое сервис использует сам (ключи S3).
- `lms`: обязательный непустой **плоский** словарь: ключи `^[a-z0-9_]+$`, значения — int или ASCII-строка. Сервис не знает семантики этих полей — валидирует формат и пробрасывает блок как есть в манифест, REST-payload и `x-amz-meta-lms-*`. Состав (group_id / course_id / teacher_id / …) определяет плагин; новые поля добавляются в конфиг без изменений кода.
- Файл валидируется на старте (pydantic); ошибка схемы — падение на старте с внятным сообщением.
- Папка без записи в `groups.yaml`: файлы пропускаются (`skipped_unmapped`), событие `GroupUnmapped` (WARNING, не чаще раза за цикл на папку); сервис не падает.

## Processing Rules

- Сканируются только прямые подпапки `VIDEO_ROOT` (глубина ровно 1: `VIDEO_ROOT/<группа>/<файл>`).
- Кандидаты: расширение из `ALLOWED_EXTENSIONS`; имена, начинающиеся с `.` или `~`, игнорируются.
- Стабильность: `size` и `mtime` не менялись ≥ `STABILITY_MINUTES` **и** файл открывается на чтение; иначе — ждать следующего цикла (это не ошибка, `failed` не ставить).
- Дата занятия: цепочка стратегий — `FilenameDateExtractor` → `FileStatDateExtractor` (mtime; событие `DateFallback`, WARNING). `FilenameDateExtractor` работает по `DATE_REGEX` с именованными группами `day/month/year/hour/minute/second`; default — под записи Телемоста: `(?P<day>\d{2})_(?P<month>\d{2})_(?P<year>\d{2})_(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})`. Двузначный год → `20ГГ`; префикс имени не важен (переименованная встреча тоже распарсится); невалидная дата (месяц > 12 и т.п.) → fallback на mtime. Часовой пояс — `TZ_NAME`.
- `SKIP_OLDER_THAN_DAYS` (опция): более старые файлы → `skipped_old`, не загружаются.
- `sha256` считается потоково (чанк 1 MiB) один раз и кешируется в реестре по `(path, size, mtime)`.
- Идемпотентность: если `sha256` уже `registered`/`archived` — повторно не грузить; сразу cleanup (если разрешён).
- **Cleanup — перемещение исходника в архив, не удаление**: файл переносится в `<папка группы>/{ARCHIVE_SUBDIR}/` серверным rename в пределах шары (без копирования; при коллизии имён к имени добавляется `_{sha8}`). Выполняется **только при всех условиях**: `uploaded` + верификация пройдена + `registered` + `ARCHIVE_AFTER_REGISTER=true`. Иначе файл остаётся на месте. Архивная подпапка сканером игнорируется (сканируется только глубина 1); очистка архива — ручная, вне сервиса.
- Изоляция ошибок: обработка каждого файла в try/except; ошибка → `failed`, `last_error`, инкремент `attempts`; ретраи в следующих циклах до `MAX_ATTEMPTS`, затем событие `VideoFailed` (ERROR).
- Порядок обработки — от старых к новым (по `recorded_at`/mtime).

## State (SQLite)

- Файл `DATA_DIR/state.db`; режим WAL; доступ — только через `StateRepository`.
- Таблица `files`: `id`, `path`, `group_name`, `size_bytes`, `mtime`, `sha256`, `status`, `s3_key`, `archived_path`, `attempts`, `last_error`, `created_at`, `updated_at`.
- Статусы: `discovered → uploading → uploaded → registered → archived`; терминальные пропуски/ошибки: `failed`, `skipped_old`, `skipped_unmapped`.
- Все переходы статусов — методами репозитория (никаких сырых UPDATE из пайплайна); времена в БД — UTC ISO 8601.

## Logging & Notifications

- Только stdlib `logging`; хендлеры собирает `logging_setup/factory.py` из `Settings`:
  - file — `RotatingFileHandler` `DATA_DIR/logs/uploader.log` (10 MiB × 5), всегда включён;
  - loki — HTTP push (`/loki/api/v1/push`), включается при заданном `LOKI_URL`;
  - telegram — только `ERROR`+, включается при `TELEGRAM_*`; защита от флуда (одинаковый текст не чаще 1 раза в 30 с).
- Бизнес-уведомления (успешная загрузка, финальный сбой) — это **не логи**: их шлют подписчики EventBus из `notifications/` тем же Telegram Bot API через httpx.

## Configuration

`.env` → pydantic-settings. Секреты — только через env; `.env` в `.gitignore`; `.env.example` поддерживать актуальным.

| Переменная                                    | Default | Назначение |
|-----------------------------------------------|---|---|
| `VIDEO_ROOT`                                  | `/mnt/video` | Корень смонтированной шары |
| `DATA_DIR`                                    | `/data` | state.db + логи |
| `GROUPS_FILE`                                 | `/app/config/groups.yaml` | Маппинг групп |
| `SCAN_INTERVAL_SECONDS`                       | `300` | Период опроса |
| `STABILITY_MINUTES`                           | `5` | Порог «файл дописан» |
| `ALLOWED_EXTENSIONS`                          | `.webm` | Кандидаты (при необходимости расширить) |
| `DATE_REGEX`                                  | под Телемост | Именованные группы `day/month/year/hour/minute/second` (см. Processing Rules) |
| `SKIP_OLDER_THAN_DAYS`                        | — | Пропуск залежей (пусто = выкл) |
| `ARCHIVE_AFTER_REGISTER`                      | `true` | Перемещать исходник в архив после регистрации |
| `ARCHIVE_SUBDIR`                              | `_uploaded` | Имя архивной подпапки внутри папки группы |
| `MAX_ATTEMPTS`                                | `5` | Ретраи на файл |
| `TZ_NAME`                                     | `Europe/Moscow` | TZ для `recorded_at` |
| `S3_ENDPOINT_URL`                             | `https://s3.ru1.storage.beget.cloud` | Beget S3 |
| `S3_REGION`                                   | `ru-1` | Для SigV4 |
| `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | — | Реквизиты Beget |
| `S3_KEY_PREFIX`                               | `videos` | Префикс ключей |
| `LMS_BASE_URL`                                | — | Напр. `http://11.11.11.20:8080` |
| `LMS_UPLOADER_TOKEN`                          | — | Shared secret |
| `LMS_DRY_RUN`                                 | `false` | Регистрация «вхолостую» до готовности эндпоинта |
| `LOKI_URL`                                    | — | Опция |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`      | — | Опция |
| `API_PORT`                                    | `8090` | FastAPI |

## HTTP API

- `GET /health` → `{"status": "ok", "last_scan_at": …}` — для Docker HEALTHCHECK.
- `GET /status` → счётчики по статусам + последние 20 записей реестра.
- `POST /rescan` → триггер внеочередного цикла сканирования.
- API — тонкий слой над репозиторием/воркером; бизнес-логики не содержит. Аутентификации нет: доступ есть только из Tech/Admin-сегментов.

## Runtime Environment

- Отдельный LXC (Ubuntu, privileged) в Tech-сегменте `11.11.11.0/24`; внутри — Docker + Compose.
- Шара монтируется на уровне LXC через cifs-utils (fstab), в контейнер — bind mount:

```
//11.11.11.11/Shares$/Video  /mnt/video  cifs  credentials=/root/.smb-video,vers=3.1.1,iocharset=utf8,uid=1000,gid=1000,file_mode=0660,dir_mode=0770,_netdev  0 0
```

  Креды — доменная учётка `svc-video-upload` (файл `/root/.smb-video`, chmod 600). **`iocharset=utf8` обязателен** — имена папок кириллические.
- docker-compose: тома `/mnt/video:/mnt/video`, `./data:/data`, `./config:/app/config:ro`; `TZ=${TZ_NAME}`; `restart: unless-stopped`; HEALTHCHECK → `GET /health`.
- Dockerfile: multi-stage на `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, `uv sync --frozen --no-dev`, запуск от непривилегированного пользователя (uid 1000).

## Testing

- pytest; `tests/` зеркалит структуру `src/`.
- Всё внешнее — за Protocol; в тестах фейки: `FakeS3Gateway`, `FakeLmsClient`, репозиторий на tmp SQLite, файлы через `tmp_path`.
- В тестах запрещены: сеть, реальная шара, реальный S3/LMS/Telegram.
- Обязательное покрытие: `key_builder` (все правила ключей), стратегии даты (включая fallback), `resolver` (валидация `lms`-блока, неизвестная папка), `stability`, переходы статусов в репозитории, `pipeline` — happy path и все ветки отказов (upload fail, verify fail, register 5xx/4xx).
- Ручная проверка против реального Beget — `scripts/smoke_s3.py` (вне pytest).

## CI (GitHub Actions)

- Workflow: `.github/workflows/ci.yml`. Триггеры: `pull_request` в `main` и `push` в `main`.
- Одна джоба на `ubuntu-latest`, Python 3.12: checkout → официальный `astral-sh/setup-uv` (актуальная мажорная версия, `enable-cache: true`) → `uv sync --frozen` → `uv run ruff format --check .` → `uv run ruff check .` → `uv run mypy src` → `uv run pytest`.
- Секреты в CI не нужны: тесты не ходят в сеть/S3/LMS (только фейки) — это гарантировано разделом Testing.
- Мердж в `main` — только при зелёном CI. Branch protection (required status check `ci`) настраивается руками в GitHub: Settings → Branches → правило для `main`.

## Strict Rules

- pip запрещён; зависимости — только через `uv add` и только по согласованию.
- Сервис **никогда не удаляет** файлы на шаре. Единственная операция над исходником — перемещение в архивную подпапку на шаге cleanup при выполненных условиях; `unlink` по исходникам не вызывается нигде.
- boto3 / httpx / sqlite3 — только внутри `s3_gateway` / `lms.client` + лог-хендлеры / `state.repository`; остальной код работает через Protocol.
- Кириллица и пробелы в ключах S3 и `x-amz-meta-*` запрещены.
- Ошибка обработки одного файла не останавливает сервис и цикл сканирования.
- `print` запрещён; исключения не глотаются молча (минимум — лог с traceback).
- Не вводить новые слои, паттерны и зависимости без явного запроса.
- Работать поэтапно (план — в стартовом промпте): в конце этапа прогнать ruff + mypy + pytest и остановиться до подтверждения пользователя.

## Related Work (вне этого репозитория)

- **fs-lms**: REST-роут `fs-lms/v1/videos` (upsert по `s3_key`) и выдача видео ученикам (presigned URL / публичный бакет / CDN Beget) — реализуется в репозитории плагина по его CLAUDE.md. Контракт: блок `lms` приходит в REST-payload и продублирован в `x-amz-meta-lms-*` и в манифесте — плагин раскладывает видео только по этим ID, не разбирая имена файлов и папок.
- **Windows-сторона**: папки групп на шаре создаёт `Sync-VideoGroups.ps1` из `video-groups.csv`; `groups.yaml` должен оставаться согласованным с этим списком. Архив `_uploaded` копится внутри FSRM-квоты группы (авто-квота 30 GB на `C:\Shares\Video`) — квоту нужно расширить (`Set-FsrmQuotaTemplate ... -UpdateDerived`) либо регулярно чистить архив, иначе при переполнении новые записи не сохранятся на шару.
