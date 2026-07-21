# События сервиса и их логи

Аудит соответствия «доменное событие → строка лога» (составлен 2026-07-21).
Цель: убедиться, что каждое значимое событие залогировано, и подготовить логи
к удобному использованию в Grafana (Loki).

## Доменные события (EventBus, `video_uploader/domain/events.py`)

| Событие | Когда происходит | Текст лога | Уровень | Файл : строка |
|---|---|---|---|---|
| `VideoDiscovered` | Сканер нашёл новый файл, заведена запись реестра | `видео обнаружено: %s` | INFO | `video_uploader/pipeline.py:177` |
| `VideoUploaded` | Файл загружен и в S3 записан манифест | `видео загружено: %s -> %s` | INFO | `video_uploader/pipeline.py:272` |
| `VideoUploaded` (дубликат) | Контент уже был в S3 под другим path, s3_key переиспользован | `видео загружено (дубликат по контенту): %s -> %s` | INFO | `video_uploader/pipeline.py:337-339` |
| `VideoRegistered` (занятие найдено) | LMS принял регистрацию и сматчил занятие | `видео полностью обработано: %s -> %s (занятие найдено)` | INFO | `video_uploader/pipeline.py:296-300` |
| `VideoRegistered` (занятие не найдено) | LMS принял регистрацию, но занятие не сматчено | `видео зарегистрировано, но занятие не найдено по дате/времени — нужна ручная привязка: %s -> %s` | WARNING | `video_uploader/pipeline.py:302-307` |
| `VideoRegistered` (дубликат) | Регистрация засчитана по дубликату контента | `видео полностью обработано (дубликат по контенту, занятие уже привязано ранее): %s -> %s` | INFO | `video_uploader/pipeline.py:342-347` |
| `VideoArchived` | Исходник перемещён в архивную подпапку | `исходник перемещён в архив: %s -> %s` | INFO | `video_uploader/pipeline.py:367` |
| `VideoFailed` | Исчерпаны `MAX_ATTEMPTS`, файл больше не обрабатывается | `видео окончательно не обработано после %d попыток, повторных попыток не будет: %s` | ERROR | `video_uploader/pipeline.py:383-387` |
| `GroupUnmapped` | Папка группы отсутствует в `groups.yaml` | `папка отсутствует в groups.yaml: %s` | WARNING | `video_uploader/pipeline.py:244` |
| `DateFallback` | Дата не извлечена из имени файла, взят mtime | `дата занятия не найдена в имени файла, взят mtime: %s` | WARNING | `video_uploader/pipeline.py:226` |

Все 7 типов событий шины залогированы; лог пишется в той же точке, где публикуется событие. ✅

## Значимые шаги вне EventBus (логируются, но события не публикуют)

| Шаг | Текст лога | Уровень | Файл : строка |
|---|---|---|---|
| Ошибка записи в реестр при discover | `не удалось завести запись реестра для %s` | EXCEPTION (ERROR) | `video_uploader/pipeline.py:173` |
| Попытки исчерпаны ранее (повторное сканирование) | `видео больше не будет обработано — исчерпаны попытки (%d), нужно вмешательство администратора: %s` | WARNING | `video_uploader/pipeline.py:196-201` |
| Файл ещё дописывается | `файл ещё дописывается, ждём стабильности: %s` | DEBUG | `video_uploader/pipeline.py:209` |
| Файл старше `SKIP_OLDER_THAN_DAYS` | `видео пропущено (старше %s дней): %s` | INFO | `video_uploader/pipeline.py:232-236` |
| Верификация в S3 прошла | `видео верифицировано в S3: %s` | INFO | `video_uploader/pipeline.py:286` |
| Ошибка обработки файла (каждая попытка) | `ошибка обработки %s` | EXCEPTION (ERROR) | `video_uploader/pipeline.py:373` |
| dry-run: архивация пропущена | `dry-run: архивация %s пропущена` | INFO | `video_uploader/pipeline.py:356` |
| dry-run: загрузка пропущена | `dry-run: upload_video пропущен: %s -> %s` | INFO | `video_uploader/main.py:107` |
| dry-run: манифест пропущен | `dry-run: put_manifest пропущен: %s` | INFO | `video_uploader/main.py:110` |
| dry-run: верификация пропущена | `dry-run: verify пропущен (успех): %s` | INFO | `video_uploader/main.py:113` |
| dry-run: регистрация пропущена | `dry-run: register пропущен (успех): s3_key=%s` | INFO | `video_uploader/main.py:124` |
| Старт сервиса | `fs-video-uploader запускается (dry_run=%s, dry_run_lms_live=%s)` | INFO | `video_uploader/main.py:155-159` |
| Heartbeat фонового цикла | `сервис жив: реестр=%s` | INFO | `video_uploader/main.py:91` |
| Необработанная ошибка цикла сканирования | `необработанная ошибка цикла сканирования` | EXCEPTION (ERROR) | `video_uploader/main.py:79` |
| Получен сигнал остановки | `получен сигнал %s, начинаю остановку` | INFO | `video_uploader/main.py:217` |
| Остановка сервиса | `fs-video-uploader остановлен` | INFO | `video_uploader/main.py:234` |
| Ошибка чтения папки группы | `не удалось прочитать папку группы %s: %s` | WARNING | `video_uploader/scanner/scanner.py:31` |
| Упал подписчик EventBus | `подписчик %r упал на событии %r` | EXCEPTION (ERROR) | `video_uploader/domain/events.py:102` |

## Замечания по покрытию

- **Все события EventBus имеют парный лог** — пропусков нет.
- `VideoRegistered` публикуется одним событием, но логируется тремя разными
  текстами (найдено / не найдено занятие / дубликат) — для метрик в Grafana это
  три разных строки на одно бизнес-событие, см. совет ниже.
- `VideoUploaded` тоже имеет два текста (обычная загрузка / дубликат).
- `DEBUG`-лог стабильности не попадает в Loki (логгер настроен на INFO,
  `logging_setup/factory.py:28`) — это осознанно, шаг срабатывает каждый цикл.

## Как проще находить логи событий для метрик в Grafana

Сейчас в Loki уходит строка `LEVEL logger: message` с лейблами `service`,
`level`, `logger` (`logging_setup/loki.py:52-57`). Событие приходится ловить
регекспом по русскому тексту сообщения — это хрупко: любая правка формулировки
ломает дашборд.

**Рекомендация: добавить в каждую «событийную» строку стабильный машинный
токен `event=<имя>`**, а человеческий текст оставить как есть. Например:

```python
logger.info("event=video_uploaded видео загружено: %s -> %s", path, s3_key)
```

Тогда в Grafana запросы становятся однострочными и не зависят от формулировок:

```logql
# счётчик загрузок за 5 минут
sum(count_over_time({service="fs-video-uploader"} |= "event=video_uploaded" [5m]))

# или через парсер logfmt-подобного токена:
{service="fs-video-uploader"} | regexp "event=(?P<event>\\w+)" | event != ""
```

Дополнительные советы:

1. **Один токен на одно бизнес-событие.** Три текста `VideoRegistered` должны
   нести один `event=video_registered` (+ отдельный маркер `matched=true/false`),
   иначе метрика «зарегистрировано» собирается из трёх регекспов.
2. **Ключ-значение вместо свободного текста для параметров**: `path=... s3_key=...`
   вместо `%s -> %s` — тогда `| logfmt` в LogQL сам разложит строку на поля и
   можно фильтровать/группировать по `s3_key`, `group`.
3. **Не делать `event` лейблом Loki-стрима** (в `LokiHandler`): лейблы с высокой
   кардинальностью Loki не любит, но `event` — это ~десяток значений, так что
   при желании можно добавить его третьим лейблом рядом с `level` — тогда
   запрос упрощается до `{service="fs-video-uploader", event="video_uploaded"}`
   и `count_over_time` работает без парсинга строк. Это самый удобный вариант,
   но потребует передавать имя события в `record` (например, через
   `logger.info(..., extra={"event": "video_uploaded"})` и чтение
   `record.event` в `LokiHandler.emit`).
4. **Единый источник имён событий** — использовать имена классов из
   `domain/events.py` в snake_case (`video_discovered`, `video_uploaded`,
   `video_registered`, `video_archived`, `video_failed`, `group_unmapped`,
   `date_fallback`), чтобы код, логи и дашборды говорили на одном языке.
5. Для алертов: `video_failed` (ERROR) и `group_unmapped` (WARNING) — главные
   кандидаты; heartbeat `сервис жив` удобно использовать как absent-алерт
   (`absent_over_time` за 2× интервала heartbeat).