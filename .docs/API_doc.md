# API — fs-video-uploader

Сервис предоставляет тонкий HTTP API (FastAPI) поверх реестра и фонового воркера сканирования — без бизнес-логики, только чтение состояния и один управляющий метод. Реализация — `video_uploader/api/app.py`.

- Базовый URL: `http://<host>:<API_PORT>` (по умолчанию порт `8090`, см. `.env`).
- Аутентификации нет — доступ ограничен сетевым сегментом (Tech/Admin), не приложением.
- Формат — везде `application/json`.
- Синхронные обработчики: FastAPI сам уводит их в threadpool (внутри — блокирующие вызовы к SQLite и `threading.Event`).

## `GET /health`

Проверка живости сервиса — используется Docker `HEALTHCHECK` в `docker-compose.yml`.

**Запрос**

```bash
curl -s http://localhost:8090/health
```

**Ответ `200 OK`**

Сразу после старта, до первого цикла сканирования:

```json
{
  "status": "ok",
  "last_scan_at": null
}
```

После хотя бы одного цикла — `last_scan_at` в ISO 8601, UTC:

```json
{
  "status": "ok",
  "last_scan_at": "2026-07-17T13:44:12.405483+00:00"
}
```

`status` всегда `"ok"`, если процесс жив и ответил — эндпоинт не проверяет доступность S3/LMS/шары отдельно, это было бы дороже, чем нужно для liveness-проверки контейнера. Диагностика конкретных проблем — `GET /status` и логи (Loki/`DATA_DIR/logs/uploader.log`).

## `GET /status`

Счётчики по статусам реестра + последние записи — для быстрой диагностики без похода в SQLite напрямую.

**Запрос**

```bash
curl -s http://localhost:8090/status
```

**Ответ `200 OK`**

```json
{
  "counts": {
    "registered": 1,
    "failed": 1
  },
  "recent": [
    {
      "id": 2,
      "path": "/mnt/video/КЕГЭ-1/rec_09_07_26_10_00_00.webm",
      "group_name": "КЕГЭ-1",
      "size_bytes": 245681302,
      "mtime": 1783497600.0,
      "sha256": null,
      "status": "failed",
      "s3_key": null,
      "archived_path": null,
      "attempts": 1,
      "last_error": "boto3 boom",
      "created_at": "2026-07-17T13:44:05.100000+00:00",
      "updated_at": "2026-07-17T13:44:05.410000+00:00"
    },
    {
      "id": 1,
      "path": "/mnt/video/КЕГЭ-1/rec_08_07_26_16_04_45.webm",
      "group_name": "КЕГЭ-1",
      "size_bytes": 19,
      "mtime": 1783504800.0,
      "sha256": "6a1bf35f2da20adaa77617f3512f275f1d1e3beaf9ac79bdb88fd8b203683041",
      "status": "registered",
      "s3_key": "videos/kege-1/2026/07/2026-07-08_16-04_6a1bf35f.webm",
      "archived_path": null,
      "attempts": 0,
      "last_error": null,
      "created_at": "2026-07-17T13:44:12.405483+00:00",
      "updated_at": "2026-07-17T13:44:12.410992+00:00"
    }
  ]
}
```

Поля:

| Поле | Тип | Описание |
|---|---|---|
| `counts` | `object` | Ключ — один из статусов реестра (`discovered`, `uploading`, `uploaded`, `registered`, `archived`, `failed`, `skipped_old`, `skipped_unmapped`), значение — количество записей. Статусы, по которым записей нет, в объекте отсутствуют (не `0`). |
| `recent` | `array` | Последние 20 записей реестра по времени обновления, самые свежие первыми. Каждый элемент — прямой дамп строки таблицы `files` (`StateRepository.FileState`). |
| `recent[].sha256`, `.s3_key`, `.archived_path`, `.last_error` | `string \| null` | `null`, пока соответствующий шаг ещё не пройден. |
| `recent[].mtime` | `number` | Unix-время (эпоха), как есть из `os.stat()`. |
| `recent[].created_at`, `.updated_at` | `string` | UTC, ISO 8601. |

Пустой реестр (сервис только что запущен, файлов ещё не было) — `{"counts": {}, "recent": []}`.

## `POST /rescan`

Триггер внеочередного цикла сканирования, не дожидаясь `SCAN_INTERVAL_SECONDS`.

**Запрос**

```bash
curl -s -X POST http://localhost:8090/rescan
```

Тело запроса не требуется и игнорируется.

**Ответ `200 OK`**

```json
{
  "status": "triggered"
}
```

Важно: ответ приходит немедленно и **не означает**, что скан уже завершился — это именно триггер («разбудить» фоновый поток пораньше), а не синхронный запуск. Единственный поток, который когда-либо выполняет цикл сканирования, — фоновый воркер; `/rescan` не запускает его параллельно, а прерывает текущее ожидание между циклами. Результат смотреть через `GET /status` спустя несколько секунд или в логах.

Повторные вызовы `/rescan` во время уже идущего цикла безопасны — не создают очередь и не запускают несколько сканирований одновременно.

---

## Исходящий API: регистрация в LMS

Помимо HTTP API, который сервис предоставляет, он сам выступает клиентом REST API плагина fs-lms (`video_uploader/lms/client.py`) — это не эндпоинт этого сервиса, а то, что он вызывает наружу на шаге `register`.

```
POST {LMS_BASE_URL}/wp-json/fs-lms/v1/videos
Headers:
  X-Fs-Timestamp: <unix-время, секунды>
  X-Fs-Signature: hex(hmac_sha256(f"{timestamp}." + raw_body, LMS_HMAC_SECRET))
  Content-Type: application/json
```

```json
{
  "s3_bucket": "f6bcd57c2800-fs-video",
  "s3_key": "videos/kege-1/2026/07/2026-07-08_16-04_6a1bf35f.webm",
  "manifest_key": "videos/kege-1/2026/07/2026-07-08_16-04_6a1bf35f.webm.json",
  "group_slug": "kege-1",
  "lms": {"group_id": 3, "course_id": 42, "teacher_id": 7},
  "recorded_at": "2026-07-08T16:04:45+03:00",
  "size_bytes": 245681302,
  "sha256": "6a1bf35f2da20adaa77617f3512f275f1d1e3beaf9ac79bdb88fd8b203683041",
  "duration_sec": null
}
```

Ожидаемый ответ плагина — `200 {"ok": true, "matched": true|false, "group_lesson_id": <int|null>}`. Полный контракт (анти-replay окно, семантика `matched:false`, коды ошибок) — `.docs/CLAUDE.md`, раздел «LMS REST (push)»; этот файл его не дублирует, только даёт живой пример payload.
