# fs-video-uploader — техническая документация

Фоновый сервис, который переносит видеозаписи занятий с SMB-шары учебного центра в S3-хранилище Beget и регистрирует их в LMS (WordPress-плагин [fs-lms](https://github.com/Qabasya/fs-lms)).

## 1. Структура проекта

Плоская раскладка (flat layout) — пакет `video_uploader/` лежит в корне репозитория, не в `src/` (осознанный выбор: одна вложенность вместо двух, `pyproject.toml` → `module-root = ""`).

```
video-uploader/
├── video_uploader/
│   ├── main.py                 # composition root: сборка зависимостей, воркер, uvicorn
│   ├── config.py                # Settings (pydantic-settings) + модели/загрузка groups.yaml
│   ├── pipeline.py              # оркестратор: scan → ... → cleanup, per-file изоляция ошибок
│   │
│   ├── domain/
│   │   ├── models.py            # VideoFile, LessonMeta, UploadResult — frozen dataclass
│   │   └── events.py            # 7 доменных событий + EventBus (Observer)
│   │
│   ├── scanner/
│   │   ├── scanner.py           # обход VIDEO_ROOT/<папка>/*, глубина 1
│   │   └── stability.py         # проверка «файл дописан»
│   │
│   ├── metadata/
│   │   ├── base.py              # DateExtractor (Protocol)
│   │   ├── filename.py          # дата из имени файла (default — Телемост)
│   │   └── filestat.py          # fallback: mtime
│   │
│   ├── resolving/
│   │   └── resolver.py          # GroupResolver: имя папки → slug + блок lms
│   │
│   ├── storage/
│   │   ├── key_builder.py       # соглашение о ключах S3 — единственный источник
│   │   └── s3_gateway.py        # adapter над boto3 (Beget)
│   │
│   ├── lms/
│   │   └── client.py            # REST-клиент fs-lms, HMAC-подпись
│   │
│   ├── state/
│   │   └── repository.py        # Repository над SQLite (SQLAlchemy 2.0), машина статусов
│   │
│   ├── logging_setup/
│   │   ├── factory.py           # Factory: собирает хендлеры логов из Settings
│   │   └── loki.py              # кастомный logging.Handler для Grafana Loki
│   │
│   ├── notifications/
│   │   └── telegram.py          # заглушка — см. раздел 4 про доработку
│   │
│   └── api/
│       └── app.py               # FastAPI: /health, /status, /rescan — без бизнес-логики
│
├── tests/                       # зеркалит структуру video_uploader/, 221 тест
├── config/groups.yaml.example   # шаблон маппинга папок → LMS ID
├── scripts/smoke_s3.py          # ручная проверка против реального Beget (вне pytest)
├── Dockerfile, docker-compose.yml
├── .env.example
└── pyproject.toml
```

Pipeline одного файла:

```
scan → stability → dedup (реестр) → metadata (дата) → resolve (папка → slug + lms)
     → upload (S3) → verify → register (LMS REST) → cleanup (архивация)
```

## 2. Используемые технологии

| Технология | Где используется | Почему |
|---|---|---|
| **Python 3.12+, uv** | весь проект | Современный тулчейн без `pip`/`poetry`: один быстрый резолвер зависимостей, единый `uv.lock`, единая команда на всё (`uv run`, `uv add`). |
| **pydantic v2 + pydantic-settings** | `config.py` (`Settings`, `GroupEntry`, `GroupsConfig`) | Валидация конфигурации на старте с понятными сообщениями об ошибке (fail-fast); `SecretStr` не даёт секретам случайно попасть в лог/`repr`. |
| **boto3** | `storage/s3_gateway.py` | Официальный AWS SDK, полностью совместим с S3-API Beget (path-style addressing). Типизирован через `boto3-stubs[s3]` — иначе `mypy --strict` не видит реальные типы клиента. |
| **httpx** | `lms/client.py`, `logging_setup/loki.py` | Синхронный HTTP-клиент с человеческим API; поддерживает `transport=` для подмены сети в тестах без моков библиотек. |
| **SQLite + SQLAlchemy 2.0 (ORM)** | `state/repository.py` | Один файл `state.db`, ноль внешней инфраструктуры для реестра статусов. Верхняя граница нагрузки — сотни файлов, не требует полноценной СУБД. Режим WAL — конкурентные читатели во время записи. |
| **PyYAML** | `config.py` (`load_groups`) | Чтение `config/groups.yaml` — единственное место, где сервис работает с YAML. |
| **FastAPI + uvicorn** | `api/app.py`, `main.py` | Тонкий HTTP-слой поверх воркера: `/health` (Docker HEALTHCHECK), `/status`, `/rescan`. Синхронные обработчики (FastAPI сам уводит их в threadpool — блокирующий SQLite/`threading.Event` не блокирует event loop). |
| **pytest / ruff / mypy --strict** | dev-инструменты | Обязательный чистый прогон перед завершением любого этапа: `ruff format` + `ruff check` + `mypy` + `pytest`. |

Зачем **не** взяли: `aiobotocore`/asyncio — воркер синхронный по архитектуре (опрос шары раз в `SCAN_INTERVAL_SECONDS`, не веб-сервер с сотнями конкурентных запросов), throughput на одной загрузке уже даёт multipart-upload boto3 через свой пул потоков.

## 3. Применённые паттерны

| Паттерн | Где | Почему |
|---|---|---|
| **Strategy** | `metadata/filename.py` + `metadata/filestat.py` (оба реализуют `Protocol DateExtractor` из `metadata/base.py`); `logging_setup/loki.py` (`logging.Handler` — стандартная реализация Strategy из stdlib) | Цепочка стратегий извлечения даты перебирается в `pipeline.py` до первого успеха — новая стратегия добавляется без правки существующего кода (SOLID-O). |
| **Observer** | `domain/events.py` (`EventBus`) | Пайплайн публикует события (`VideoUploaded`, `VideoRegistered`, `GroupUnmapped`, …) на значимых шагах; подписчики (уведомления) реагируют, не будучи вплетёнными в критичный путь. Шина изолирует ошибку одного подписчика от остальных и от публикующего кода. |
| **Factory** | `logging_setup/factory.py` (`configure_logging`) | Собирает набор `logging.Handler`-стратегий из `Settings` — какие сконфигурированы (`LOKI_URL` задан → добавлен `LokiHandler`), те и подключаются. |
| **Repository** | `state/repository.py` (`StateRepository`) | Единственная точка доступа к SQLite; все переходы статусов — только через явные методы (`mark_uploaded`, `mark_registered`, …), никаких сырых `UPDATE` из пайплайна. Допустимые переходы — одна таблица `_ALLOWED_TRANSITIONS`, не разбросанные `if`. |
| **Adapter / Gateway** | `storage/s3_gateway.py` (`S3Gateway`), `lms/client.py` (`LmsClient`) | Оборачивают внешние SDK/протоколы (`boto3`, HMAC-подписанный REST) в узкий интерфейс, которым пользуется `pipeline.py` — сам пайплайн не знает о `boto3`/`httpx` вообще. |
| **Protocol (структурная типизация, не наследование)** | `UploadGateway`/`RegistrationClient` в `pipeline.py`; `ScanWorkerLike` в `api/app.py` | Узкие интерфейсы прямо у потребителя, не у поставщика — так `api/app.py` не импортирует `main.py` (не возникает обратной/циклической зависимости), а `pipeline.py` может получить dry-run-заглушку вместо настоящего `S3Gateway`/`LmsClient` без единого `if` внутри самого пайплайна. |
| **Composition root** | `main.py` | Единственное место, где создаётся `Settings()`, разворачиваются секреты (`.get_secret_value()`) и собираются все зависимости. Больше нигде в коде нет глобального состояния или синглтонов. |

## 4. Как расширять сервис

### Добавление канала логирования (боты, Elastic и т.д.)

Логи уже уходят в Grafana Loki (`LOKI_URL`) — это основной канал наблюдаемости. **Telegram-бот и любые другие боты в этот сервис не встраиваются напрямую** — архитектурное решение: они читают события из Loki (poll/tail), а не получают push от `fs-video-uploader`. Файлы `logging_setup/telegram.py` и `notifications/telegram.py` — сознательно оставленные заглушки под эту идею, не «недоделанные».

Чтобы добавить ещё один канал (например, Elastic):

1. Новый класс `logging.Handler` в `logging_setup/<канал>.py`, реализующий `emit(self, record: logging.LogRecord) -> None`. Ошибки внутри — через `self.handleError(record)` (стандартный механизм stdlib, не собственный `try/except`, чтобы не зациклиться в логировании собственной поломки).
2. Новая переменная в `Settings` (`config.py`), опциональная — «канал включён, если задан URL/токен».
3. Ветка в `configure_logging()` (`logging_setup/factory.py`): `if settings.<новая_переменная> is not None: logger.addHandler(<НовыйHandler>(...))`.

Ни `pipeline.py`, ни любой другой модуль трогать не нужно — они логируют через `logging.getLogger(__name__)`, и всё, что настроено в фабрике, получает запись автоматически (это и есть смысл единой иерархии логгеров `video_uploader.*`).

### Добавление новых папок для сканирования

Кода это **не требует**. `VideoScanner` обходит все прямые подпапки `VIDEO_ROOT` одинаково — будь то папка учебной группы или персональная папка преподавателя (индивидуальные занятия). Семантику задаёт исключительно состав блока `lms` в `config/groups.yaml`:

```yaml
groups:
  "Новая-Группа":
    slug: novaya-gruppa
    lms:
      group_id: 12
      course_id: 55
      teacher_id: 3
```

Папка без записи в `groups.yaml` просто пропускается (`skipped_unmapped`, WARNING в логах) — сервис не падает. Если запись добавить позже, уже обнаруженные файлы получат шанс обработаться на следующем цикле сканирования (переоткрытие статуса реализовано специально для этого случая).

### Интеграция с другим хранилищем вместо S3

`pipeline.py` зависит не от конкретного `S3Gateway`, а от узкого `Protocol` (`UploadGateway`, объявлен в самом `pipeline.py`):

```python
class UploadGateway(Protocol):
    def upload_video(self, path: Path, key: str, metadata: Mapping[str, str]) -> None: ...
    def put_manifest(self, key: str, manifest: dict[str, object]) -> None: ...
    def verify(self, key: str, expected_size: int) -> bool: ...
```

Чтобы переехать на другое хранилище: новый класс в `storage/`, реализующий эти три метода (структурно, без наследования — Python `Protocol` проверяет форму, не иерархию), и замена `S3Gateway(...)` на новый класс в `main.py`. Всё соглашение о ключах остаётся в `storage/key_builder.py` — трогать его нужно только если меняется сам формат ключей, не поставщик хранилища.

Тот же приём — для LMS: `RegistrationClient` Protocol в `pipeline.py`, реализация в `lms/client.py`. Если понадобится другая LMS/CRM — новый класс с методом `register(payload: dict[str, object]) -> None`.

## 5. Как пользоваться

### Настройки

Полный список переменных — `.env.example` (скопировать в `.env`, заполнить секреты; `.env` не коммитится). Коротко по группам:

- **Шара и данные**: `VIDEO_ROOT` (корень смонтированной SMB-шары), `DATA_DIR` (`state.db` + логи), `GROUPS_FILE` (маппинг папок).
- **Сканирование**: `SCAN_INTERVAL_SECONDS`, `STABILITY_MINUTES`, `ALLOWED_EXTENSIONS`, `DATE_REGEX` (пусто = формат Телемоста), `SKIP_OLDER_THAN_DAYS`.
- **Архивация**: `ARCHIVE_AFTER_REGISTER`, `ARCHIVE_SUBDIR` — исходник **никогда не удаляется**, только переносится в `<папка>/_uploaded/`.
- **Обработка**: `MAX_ATTEMPTS`, `TZ_NAME`, `DRY_RUN` (сухой прогон — S3/LMS/архивация подменяются заглушками, логирующими вместо реальных вызовов; удобно до готовности эндпоинта LMS или для локальной проверки).
- **S3, LMS, наблюдаемость, HTTP API** — см. разделы ниже.

### Деплой в контейнер

```bash
cp .env.example .env      # заполнить секреты
cp config/groups.yaml.example config/groups.yaml   # заполнить реальные группы
docker compose up -d --build
```

Что делает `docker-compose.yml`:
- Монтирует уже смонтированную на уровне LXC SMB-шару (`/mnt/video`) внутрь контейнера бинд-маунтом — сам контейнер по SMB ничего не монтирует, это забота хоста (`cifs-utils` в `fstab`, см. `.docs/CLAUDE.md`, Runtime Environment).
- `./data:/data` — здесь живут `state.db` и файлы логов, переживают пересоздание контейнера.
- `./config:/app/config:ro` — `groups.yaml` монтируется только на чтение.
- `env_file: .env` — все переменные окружения сервиса.
- `HEALTHCHECK` — `GET /health`, для `docker compose ps`/оркестраторов.
- `restart: unless-stopped` — переживает падения и перезагрузку хоста.

`Dockerfile` — двухстадийная сборка на `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`: сначала `uv sync --frozen --no-dev` в builder-стадии, затем копирование готового `.venv` в чистый финальный слой от непривилегированного пользователя (`uid 1000`) — секреты и исходники SMB-шары никогда не видны образу вне рантайма.

### Ключи S3 (Beget)

`S3_ENDPOINT_URL`/`S3_REGION` уже настроены по умолчанию под Beget (`https://s3.ru1.storage.beget.cloud`, `ru-1`). Нужно завести бакет в панели Beget (имя бакет получит с автопрефиксом вида `f6bcd57c2800-...` — это и есть значение `S3_BUCKET`) и ключ доступа (`S3_ACCESS_KEY`/`S3_SECRET_KEY`). Проверить реальное подключение до продакшен-запуска:

```bash
uv run python scripts/smoke_s3.py
```

Скрипт грузит маленький тестовый объект, проверяет `verify()`, кладёт манифест и удаляет за собой — ничего не оставляет в бакете.

### Интеграция с плагином LMS (fs-lms)

1. В `wp-config.php` плагина задать секрет `FS_LMS_VIDEO_HMAC_SECRET` — то же значение идёт в `.env` этого сервиса как `LMS_HMAC_SECRET`. Запросы к `POST {LMS_BASE_URL}/wp-json/fs-lms/v1/videos` подписываются HMAC-SHA256 (заголовки `X-Fs-Timestamp`/`X-Fs-Signature`), статического токена в заголовках больше нет.
2. Часы LXC должны быть синхронизированы (NTP) — окно анти-replay ±300 секунд, рассинхрон часов даст `401` от плагина.
3. `LMS_BASE_URL` — адрес WordPress-инсталляции с плагином (например, `http://11.11.11.20:8080`).
4. Пока REST-эндпоинт плагина не готов — `DRY_RUN=true`: шаг регистрации логируется и засчитывается успешным, реального запроса не будет.
5. В `config/groups.yaml` — блок `lms` для каждой папки: `{group_id, course_id, teacher_id}` для групповых занятий или `{teacher_id}` (без `group_id`) для персональной папки преподавателя — плагин сам определяет ветку резолва по составу блока, сервис его не интерпретирует. `teacher_id` — это числовой WP user ID (тот же, что в `fs_lms_groups.teacher_id`).
