# fs-video-uploader

![CI](https://github.com/Qabasya/video-uploader/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white)
![uv](https://img.shields.io/badge/package%20manager-uv-de5fe9)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-v2-e92063?logo=pydantic&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red)
![boto3](https://img.shields.io/badge/boto3-S3-ff9900?logo=amazonaws&logoColor=white)
![mypy](https://img.shields.io/badge/mypy-strict-blue)
![ruff](https://img.shields.io/badge/lint-ruff-black)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)

Фоновый сервис, который следит за папкой с записями занятий на SMB-шаре, заливает готовые видео в S3 (Beget) и регистрирует их в LMS-плагине [fs-lms](https://github.com/Qabasya/fs-lms). Разово настроил — дальше он молча работает сам.

## Что он делает

1. Раз в N секунд сканирует `VIDEO_ROOT` — там подпапки учебных групп/преподавателей, в них видеофайлы.
2. Ждёт, пока файл «отлежится» (перестал дописываться), чтобы не залить недописанную запись.
3. Достаёт дату/время записи из имени файла (или использует mtime, если формат не распознан).
4. Заливает файл в S3 (мультипарт для больших файлов) + кладёт рядом JSON-манифест.
5. Регистрирует видео в LMS через HTTP (запрос подписан HMAC, LMS ищет подходящее занятие по группе/дате).
6. Переносит исходник в архивную подпапку — файлы никогда не удаляются, только перекладываются.
7. Если что-то сломалось — повторит попытку на следующем цикле, до `MAX_ATTEMPTS`, дальше пометит файл как failed и оставит в покое.

Всё состояние (кто в очереди, кто залит, кто упал и почему) — в SQLite, доступно через HTTP `/status`.

## Установка и запуск локально

Нужен [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env          # заполнить S3/LMS реквизиты
cp config/groups.yaml.example config/groups.yaml   # прописать свои группы
uv run video-uploader
```

Сервис поднимет HTTP API на `API_PORT` (по умолчанию 8090) и будет сканировать `VIDEO_ROOT` в фоне.

## Настройка

Всё через переменные окружения / `.env` (см. `.env.example` — там расписана каждая переменная). Ключевое:

- **`VIDEO_ROOT`** — корень SMB-шары с папками групп.
- **`GROUPS_FILE`** — `groups.yaml`, маппинг «папка → slug для S3 + ID для LMS» (пример в `config/groups.yaml.example`). Папка, которой нет в файле, просто пропускается.
- **`S3_*`** — эндпоинт, бакет, ключи Beget S3.
- **`LMS_BASE_URL` / `LMS_HMAC_SECRET`** — куда стучаться и чем подписывать запросы к fs-lms (секрет должен совпадать с тем, что в wp-config плагина).
- **`STABILITY_MINUTES`** — сколько минут файл должен не меняться, прежде чем его тронут.
- **`DATE_REGEX`** — свой формат имени файла, если стандартный (записи Телемоста) не подходит.
- **`LOKI_URL`** — если задан, логи параллельно улетают в Grafana Loki. Это основной канал наблюдаемости — телеграм-уведомлений сервис сам не шлёт, для этого будет отдельный бот, который читает Loki.

Обязательные поля (без них сервис не стартует — упадёт сразу с понятной ошибкой, а не по пути): `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `LMS_BASE_URL`, `LMS_HMAC_SECRET`.

## Сухой прогон (DRY_RUN)

`DRY_RUN=true` — сервис делает вид, что всё загрузил и зарегистрировал, но реально:

- ничего не льёт в S3,
- ничего не шлёт в LMS,
- ничего не перекладывает в архив.

Полезно, чтобы проверить, что сканер правильно видит файлы, вытаскивает даты и матчит группы — без риска что-то сломать на проде. Логи и `/status` при этом работают как обычно, только с фейковыми загрузками.

## HTTP API

- `GET /health` — жив ли процесс.
- `GET /status` — счётчики по статусам + последние 20 файлов из реестра.
- `POST /rescan` — разбудить сканер прямо сейчас, не дожидаясь `SCAN_INTERVAL_SECONDS`.

Подробнее с примерами запросов/ответов, а также контракт исходящей регистрации в fs-lms — в `.docs/VU_API.md`.

## Деплой (Docker)

```bash
cp .env.example .env
cp config/groups.yaml.example config/groups.yaml
docker compose up -d --build
```

`docker-compose.yml` монтирует:

- `/mnt/video` — SMB-шара (должна быть примонтирована на хосте),
- `./data` — SQLite-реестр и файловые логи, переживают рестарт контейнера,
- `./config` — `groups.yaml`, read-only.

Healthcheck дергает `/health` изнутри контейнера. Логи, помимо файла, можно направить в Loki через `LOKI_URL`.

## Разработка

```bash
uv run ruff format . && uv run ruff check .   # форматирование и линт
uv run mypy video_uploader                    # типы, strict-режим
uv run pytest                                 # тесты
```

Всё то же самое гоняется в CI на каждый PR/push в `main`.

## Архитектура

Подробное описание слоёв, паттернов и решений — в `.docs/basic_doc.md`.
