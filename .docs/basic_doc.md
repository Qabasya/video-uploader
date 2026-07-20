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

### Деплой на реальный сервер (LXC в Proxmox)

Сервис рассчитан на отдельный **непривилегированный LXC-контейнер** (Ubuntu) в технической сети учебного центра, с Docker + Compose внутри. Ниже — полный чек-лист от чистого LXC до работающего сервиса.

#### 5.1. Требования к LXC

- Сеть: LXC в Tech-сегменте (в наших примерах — `11.11.11.0/24`), с сетевой видимостью до:
  - SMB-шары (`\\dc.fs.loc\Shares$\Video`, в примерах — хост `11.11.11.11`);
  - сайта с плагином fs-lms (в примерах — `11.11.11.20:8080`).
- Внутри LXC установлены: Docker, Docker Compose plugin, `cifs-utils`.
- **NTP обязателен** (`timedatectl set-ntp true` или `chrony`/`systemd-timesyncd`) — HMAC-подпись запросов к LMS живёт в анти-replay окне ±300 секунд; рассинхрон часов LXC даёт `401` на каждый запрос регистрации (см. `.docs/VU_API.md`, раздел 2).

#### 5.2. Монтирование SMB-шары на уровне LXC

Контейнер сервиса сам по SMB ничего не монтирует — шара монтируется на хосте LXC через `cifs-utils`, внутрь Docker-контейнера прокидывается уже смонтированным путём (bind mount в `docker-compose.yml`).

`/etc/fstab` на LXC:

```
//11.11.11.11/Shares$/Video  /mnt/video  cifs  credentials=/root/.smb-video,vers=3.1.1,iocharset=utf8,uid=1000,gid=1000,file_mode=0660,dir_mode=0770,_netdev  0 0
```

`/root/.smb-video` (`chmod 600`):

```
username=svc-video-upload
password=<пароль сервисной учётки>
domain=FS
```

- Учётка `svc-video-upload` — доменная, права Modify на шару (нужны для перемещения исходников в архивную подпапку `_uploaded`).
- **`iocharset=utf8` обязателен** — имена папок групп кириллические, без этого параметра будут биты/нечитаемые имена.
- `uid=1000,gid=1000` — совпадает с непривилегированным пользователем внутри Docker-образа (см. `Dockerfile` ниже), иначе контейнер не сможет читать/писать файлы на шаре.

#### 5.3. Что нужно заранее подготовить (IP и ключи)

| Что | Где взять | Куда идёт |
|---|---|---|
| IP/хост SMB-шары + креды `svc-video-upload` | Windows-администратор домена | `/etc/fstab` + `/root/.smb-video` на LXC (не в `.env`) |
| `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Панель Beget → Object Storage (бакет создать заранее, имя выдаётся с автопрефиксом вида `f6bcd57c2800-...`) | `.env` |
| `LMS_BASE_URL` | Адрес WordPress-инсталляции с плагином fs-lms (в примерах — `http://11.11.11.20:8080`) | `.env` |
| `LMS_HMAC_SECRET` | Задаётся один раз и **должен совпадать** с константой `FS_LMS_VIDEO_HMAC_SECRET` в `wp-config.php` плагина — сгенерировать случайную строку и прописать в обоих местах | `.env` + `wp-config.php` плагина |
| `group_id` / `course_id` / `teacher_id` для каждой группы и препода | Админка fs-lms (таблица `fs_lms_groups` и список преподавателей) | `config/groups.yaml` |
| (опц.) `LOKI_URL` | Адрес Grafana Loki push API, если используется централизованное логирование | `.env` |
| (опц.) `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | BotFather + ID чата для ERROR-уведомлений | `.env` |

Без `S3_BUCKET`/`S3_ACCESS_KEY`/`S3_SECRET_KEY`/`LMS_BASE_URL`/`LMS_HMAC_SECRET` сервис не стартует — падает сразу при валидации `Settings`, с понятным сообщением, какой переменной не хватает.

#### 5.4. Как передать конфигурацию групп в сервис (`groups.yaml`)

`config/groups.yaml` — это YAML-файл, который сервис читает **один раз при старте** (валидация через pydantic; ошибка схемы = падение с понятным сообщением). Хот-релоада нет — если файл изменился на уже запущенном сервисе, нужно перечитать конфиг перезапуском:

```bash
cp config/groups.yaml.example config/groups.yaml   # первый раз
# отредактировать config/groups.yaml
docker compose restart video-uploader               # применить изменения
```

Формат — см. `.docs/CLAUDE.md`, раздел `config/groups.yaml`, и живой пример в `config/groups.yaml.example`. Коротко: ключ — точное имя подпапки на шаре (кириллица допустима), `slug` — для ключей S3, `lms` — плоский словарь ID для плагина (`{group_id, course_id, teacher_id}` для групповой папки или только `{teacher_id}` для персональной папки препода). Список папок должен быть согласован с `video-groups.csv` на Windows-стороне (см. `.docs/CLAUDE.md`, Related Work) — иначе часть папок будет пропускаться со статусом `skipped_unmapped`.

Сам файл монтируется в контейнер только на чтение (`./config:/app/config:ro` в `docker-compose.yml`) — редактируется на хосте LXC, не внутри контейнера.

#### 5.5. Запуск

```bash
cp .env.example .env      # заполнить секреты из чек-листа выше
cp config/groups.yaml.example config/groups.yaml   # заполнить реальные группы
docker compose up -d --build
```

Что делает `docker-compose.yml`:
- Монтирует уже смонтированную на уровне LXC SMB-шару (`/mnt/video`) внутрь контейнера бинд-маунтом — сам контейнер по SMB ничего не монтирует, это забота хоста (шаг 5.2 выше).
- `./data:/data` — здесь живут `state.db` и файлы логов, переживают пересоздание контейнера.
- `./config:/app/config:ro` — `groups.yaml` монтируется только на чтение.
- `env_file: .env` — все переменные окружения сервиса.
- `HEALTHCHECK` — `GET /health`, для `docker compose ps`/оркестраторов.
- `restart: unless-stopped` — переживает падения и перезагрузку хоста.

`Dockerfile` — двухстадийная сборка на `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`: сначала `uv sync --frozen --no-dev` в builder-стадии, затем копирование готового `.venv` в чистый финальный слой от непривилегированного пользователя (`uid 1000`) — секреты и исходники SMB-шары никогда не видны образу вне рантайма.

#### 5.6. Проверка после деплоя

```bash
curl -s http://localhost:8090/health   # {"status": "ok", ...}
curl -s http://localhost:8090/status   # счётчики реестра, изначально пустые
```

Перед первым продакшен-запуском стоит:
1. Проверить реальное S3-подключение: `uv run python scripts/smoke_s3.py` (грузит тестовый объект, проверяет `verify()`, удаляет за собой).
2. Прогнать один цикл с `DRY_RUN=true`, чтобы убедиться, что сканер правильно видит папки/файлы и матчит их на `groups.yaml`, не трогая реальные S3/LMS/архив (см. раздел 5 в README.md).
3. Убедиться через `docker compose logs -f` / Loki, что нет предупреждений `GroupUnmapped` — значит, все папки на шаре учтены в `groups.yaml`.

### Ключи S3 и интеграция с fs-lms — подробности

`S3_ENDPOINT_URL`/`S3_REGION` уже настроены по умолчанию под Beget (`https://s3.ru1.storage.beget.cloud`, `ru-1`); откуда брать `S3_BUCKET`/`S3_ACCESS_KEY`/`S3_SECRET_KEY`, `LMS_BASE_URL`, `LMS_HMAC_SECRET` и как проверить S3 через `scripts/smoke_s3.py` — см. раздел 5.3–5.6 выше. Полный контракт исходящей регистрации в fs-lms (HMAC-подпись, формат payload, обработка `matched`/ошибок/ретраев) и то, что плагин может прочитать напрямую из S3 (манифест, `x-amz-meta-*`) — `.docs/VU_API.md`.
