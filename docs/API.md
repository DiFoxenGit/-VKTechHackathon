# Контракт API для отдельного фронтенда

Base URL: `http://localhost:8000`. Префикс `/api/v1`. За обратным прокси сервис может жить под под-путём (`DESIGNER_BASE_PATH`, например `https://auto-sell.site/presentations`): тогда `exports`, `status_url` и `servers` в `openapi.json` уже содержат префикс, и достраивать его не нужно — используйте эти значения как есть. Swagger `/docs`, схема `/openapi.json`.
При заданном `DESIGNER_API_KEY` каждый запрос `/api/v1/*` содержит `Authorization: Bearer <token>`.

## Эндпоинты

| Метод | Путь | Результат |
|---|---|---|
| GET | `/health` | Статус сервера, доступность LLM и PDF |
| GET | `/api/v1/workflow` | Версия агентов, файлы промптов и SHA-256 |
| GET | `/api/v1/templates` | `{items: [...]}` — шаблоны, без подробного списка объектов |
| POST | `/api/v1/templates` | multipart `file` (.pptx), 201, шаблон и токены |
| GET | `/api/v1/templates/{id}` | Полная декомпозиция: tokens, geometry, patterns, layouts, assets |
| GET | `/api/v1/templates/{id}/assets` | Картинки шаблона: `{counts, items:[{id,kind,tags,label,url…}]}` — иконки, иллюстрации, фото |
| POST | `/api/v1/templates/{id}/assets/tags` | Подписать картинки шаблона мультимодальной моделью; 503 без `DESIGNER_VLM_MODEL` |
| GET | `/api/v1/assets/{template\|pack}/{owner}/{file}` | Файл картинки (SVG отдаётся с запрещающим CSP) |
| GET | `/api/v1/content-packs` | Список загруженных материалов |
| POST | `/api/v1/content-packs` | multipart `file`, 201, `{id,name,text,assets,asset_counts,sha256}`. Текст (txt, md, csv, json, pdf, docx, pptx), картинка (svg, png, jpg) или zip из них |
| GET | `/api/v1/content-packs/{id}` | Извлечённый текст и метаданные картинок |
| GET | `/api/v1/content-packs/{id}/assets` | Картинки пакета со ссылками на файлы |
| POST | `/api/v1/outlines` | Бриф → Outline; синхронно, до 150 секунд ожидания модели |
| POST | `/api/v1/generations` | 202, задача генерации трёх вариантов |
| GET | `/api/v1/jobs/{id}` | Статус, progress 0–100, presentation_ids, error |
| GET | `/api/v1/presentations?offset=0&limit=50` | Список презентаций с пагинацией |
| GET | `/api/v1/presentations/{id}` | Слайды, геометрия, аудит, revision, ссылки exports |
| GET | `/api/v1/presentations/{id}/slides/{index}/preview?highlight=true` | SVG-превью с подсветкой найденных проблем, требует LibreOffice |
| GET | `/api/v1/presentations/{id}/audit` | Аудит текущей версии |
| POST | `/api/v1/presentations/{id}/audit?contextual=false` | Повторный аудит; true добавляет проверку LLM |
| POST | `/api/v1/presentations/{id}/fixes` | `{revision,issue_ids}` — применить выбранные автоматические исправления |
| PATCH | `/api/v1/presentations/{id}/slides/{index}` | `{revision,content}` — заменить содержимое одного слайда |
| GET | `/api/v1/presentations/{id}/export/{format}?revision=1` | Скачать pptx/pdf/html нужной версии |

Индексы слайдов начинаются с 0. Идентификаторы ресурсов — непрозрачные строки.
Максимальная загрузка — 50 MB, распакованный ZIP — 300 MB. Сканированный PDF без текстового слоя не поддерживается.

## Визуальный контент-пакет

Zip с картинками и, по желанию, текстами. `manifest.json` в корне задаёт вид и теги:

```json
{"assets": [{"file": "icons/rocket.svg", "kind": "icon", "tags": ["запуск", "ракета"]}]}
```

Без манифеста вид берётся из папки (`icons/`, `illustrations/`, `photos/`) или по самой картинке, а теги — из имени файла (`запуск-ракета.svg`). Одноцветные SVG и PNG считаются иконками и перекрашиваются в акцент шаблона; SVG вставляется нативными фигурами, растр — картинкой без растяжения. Пример — `samples/content-pack/visual-pack.zip` (его собирает `tools/make_content_pack.py`).

## Рекомендуемый сценарий

1. Загрузить шаблон или выбрать импортированный через GET templates.
2. Загрузить контент-пакет(ы).
3. POST outlines: показать и при необходимости отредактировать структуру.
4. POST generations с выбранным шаблоном и отредактированным outline.
5. Опрос jobs раз в 1–2 секунды до `completed` или `failed`.
6. Получить три presentations; показать варианты и аудит.
7. Отправить выбранные исправления или отредактировать отдельный слайд.
8. Скачать нужный экспорт по URL из последнего ответа.

### Бриф

```json
{
  "brief": "Подготовь защиту инициативы по материалам",
  "purpose": "initiative",
  "language": "ru",
  "slide_count": 12,
  "content_pack_ids": ["ID_ЗАГРУЖЕННОГО_МАТЕРИАЛА"]
}
```

`purpose`: `feature | product | project | initiative`; `slide_count`: 1–30, по умолчанию 12.

### Генерация без обращения к модели

```json
{
  "template_id": "ID_ШАБЛОНА",
  "brief": "Пилот: 10 команд, после запуска 20 команд. Метрика — число команд.",
  "slide_count": 1,
  "outline": {
    "title": "Результаты пилота",
    "slides": [{
      "title": "Число команд выросло с 10 до 20",
      "bullets": ["Пилот охватил 10 команд", "После запуска участвуют 20 команд"],
      "source_refs": ["brief"],
      "notes": "",
      "visual": {
        "kind": "bar",
        "categories": ["Пилот", "Запуск"],
        "series": [{"name": "Команды", "values": [10, 20]}],
        "unit": "команд"
      }
    }]
  }
}
```

Поле `contextual_audit: true` добавляет контекстуальную проверку в фоновый пайплайн: одна проверка общей структуры применяется ко всем вариантам. По умолчанию false.

Если outline отсутствует, сервер сам вызывает планировщик. Если передан — число слайдов должно совпасть с slide_count. Один и тот же outline идёт во все три варианта.

### Visual

- `none`: без визуализации.
- `bar`, `line`: `categories`, `series: [{name,values}]`, рекомендуемая `unit`. Длина каждой серии совпадает с categories; до 8 серий, но более 5 отмечает аудит (`chart_series`), а пустая `unit` — `chart_labels`.
- `table`: `columns: string[]`, `rows: string[][]`, до 8 колонок и 12 строк; более 5 колонок или 7 строк отмечает аудит (`table_size`).
- `process`, `icon`: `steps: string[]`, 1–6 подписанных элементов.

### Аудит и исправления

```json
{
  "revision": 1,
  "issues": [{
    "id": "STABLE_ISSUE_ID",
    "slide_index": 0,
    "element_id": "body",
    "code": "text_overflow",
    "message": "Оценка: текст может не поместиться в рамку",
    "box": [40, 100, 500, 180],
    "fixable": true,
    "category": "deterministic",
    "severity": "warning"
  }]
}
```

`box = [x,y,width,height]` в пунктах; ширина/высота слайда в `deck.width`, `deck.height`. Чтобы подсветить на превью, умножьте x/w на ширину превью и y/h на высоту (через соответствующие размеры слайда). `box=null` означает проблему всего слайда или содержания. `slide_index=null` означает проблему всей колоды (`font_variety`); такие findings не относятся ни к одному превью.

Коды и их соответствие Приложению 1 перечислены в [AUDIT.md](../AUDIT.md). Исправляемые автоматически (`fixable=true`): `out_of_bounds`, `margin_encroachment`, `misaligned`, `text_overflow`, `font_size_off_scale`, `color_not_in_palette`.

Запись презентации содержит `export_check` — результат проверки выгруженного PPTX: `{"opens": true, "slides": 12, "native_objects": 48, "raster_slides": []}`. Непустой `raster_slides` или несовпадение числа слайдов приводит к ошибке на этапе генерации, а не к молчаливой выгрузке.

POST fixes:

```json
{"revision": 1, "issue_ids": ["STABLE_ISSUE_ID"]}
```

Принимаются только `fixable=true`. Проверки текста с потенциальной потерей смысла исправляются вручную через PATCH. Ответ содержит новую ревизию, новый аудит и новые URLs экспорта. Автоисправление не гарантирует исчезновение проблемы: если допустимых кеглей недостаточно, она остаётся в отчёте.

### Ошибки

Ответ: `{"detail": ...}`. При валидации detail — массив ошибок FastAPI.

- 401 — неверный/отсутствующий общий API-токен.
- 404 — ресурс/слайд/ревизия не найдены.
- 409 — конфликт revision; перечитать презентацию.
- 413 — превышен размер загрузки.
- 422 — некорректный файл, схема или выбранное исправление.
- 429 — очередь занята.
- 502 — ошибка модели/невалидный ответ.
- 503 — модель не настроена или недоступен конвертер PDF/HTML.

Фоновая ошибка генерации возвращается через job.status=`failed` и job.error. HTTP-запрос статуса при этом успешен. При частичном завершении уже созданные presentation_ids остаются доступны.

Все export URL относительные к API, а не фронтенду. При Bearer-авторизации скачивайте через fetch → Blob, чтобы передать заголовок. LLM API key никогда не передаётся браузеру.
