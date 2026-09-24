import asyncio
import base64
import hashlib
import json
import logging
import os
import re
from pathlib import Path

import httpx
from fastapi import HTTPException

from .inference import llm_settings, require_llm
from .language import CYRILLIC, LATIN, foreign_labels, visual_labels
from .models import Brief, Outline, Visual

PROMPTS = Path(__file__).parent / "prompts"
LOGGER = logging.getLogger("designer.generation")

# Open-weight models below 35B miss the schema often enough that one shot is not a
# contract. Each retry shows the model its own answer and what was wrong with it.
MAX_ATTEMPTS = max(1, int(os.getenv("DESIGNER_LLM_ATTEMPTS", "3")))
RETRY_DELAY = max(0.0, float(os.getenv("DESIGNER_LLM_RETRY_DELAY", "0.4")))


class InvalidCompletion(Exception):
    """The provider answered, but the answer cannot be used as is."""


def workflow():
    manifest = json.loads((PROMPTS / "manifest.json").read_text())
    manifest["sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(PROMPTS.iterdir())
        if p.is_file()
    }
    return manifest


def narrative(purpose):
    """Каркас повествования для этого типа презентации.

    Состав слайдов зависит от того, что за презентация: у продукта — рынок и
    ценность, у проекта — статус и риски. Каркас лежит конфигом рядом с промптами
    и версионируется вместе с ними.
    """
    manifest = workflow()
    path = PROMPTS / manifest.get("narratives", "narratives.v1.json")
    if not path.exists():
        return None
    frames = json.loads(path.read_text(encoding="utf-8"))
    return frames.get(purpose)


def provider():
    settings = require_llm()
    return settings.url, settings.model


def message_text(message):
    """Текст ответа, в какой бы форме его ни прислал провайдер.

    Модели с режимом рассуждений возвращают content = null и кладут ответ в
    reasoning_content, а часть провайдеров присылает content списком частей.
    """
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") in (None, "text")
        )
    if not content:
        content = message.get("reasoning_content") or ""
    text = content.strip() if isinstance(content, str) else ""
    if not text:
        raise InvalidCompletion("Провайдер вернул пустой ответ")
    return text


def parse_json(text):
    """Accept the JSON a chat model returns: fenced blocks and stray prose around it."""
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(value)
    except ValueError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise InvalidCompletion("Ответ не содержит JSON-объекта") from None
        try:
            return json.loads(value[start : end + 1])
        except ValueError as exc:
            raise InvalidCompletion(f"JSON не разобран: {exc}") from None


async def ask(messages):
    settings = require_llm()
    payload = {
        "model": settings.model,
        "temperature": 0.2,
        "max_tokens": settings.max_tokens,
        "messages": messages,
    }
    if settings.json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.timeout, connect=15)) as client:
        response = await client.post(
            settings.url + "/chat/completions",
            headers={"Authorization": "Bearer " + settings.key},
            json=payload,
        )
        response.raise_for_status()
        try:
            return message_text(response.json()["choices"][0]["message"])
        except (ValueError, KeyError, IndexError, AttributeError) as exc:
            raise InvalidCompletion(f"Ответ провайдера без содержимого: {exc}") from exc


def vision_provider():
    """Отдельная модель для проверки по картинке; по умолчанию — основная."""
    url = (os.getenv("DESIGNER_VLM_BASE_URL") or llm_settings().url).rstrip("/")
    model = os.getenv("DESIGNER_VLM_MODEL", "")
    if not url or not model:
        raise HTTPException(
            503,
            "Configure DESIGNER_VLM_MODEL (and DESIGNER_VLM_BASE_URL) for image-based audit",
        )
    return url, model


def vision_available():
    return bool(
        os.getenv("DESIGNER_VLM_MODEL")
        and (os.getenv("DESIGNER_VLM_BASE_URL") or llm_settings().url)
    )


async def ask_vision(prompt, payload, image_png: bytes):
    """Один слайд картинкой + его текст. Ответ — JSON, как и у текстовых агентов."""
    url, model = vision_provider()
    encoded = base64.b64encode(image_png).decode()
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
        response = await client.post(
            url + "/chat/completions",
            headers={
                "Authorization": "Bearer "
                + (os.getenv("DESIGNER_VLM_API_KEY") or llm_settings().key)
            },
            json={
                "model": model,
                "temperature": 0.1,
                # Режим рассуждений съедает лимит: ответу нужен запас после мыслей.
                "max_tokens": 6000,
                "messages": [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{encoded}"},
                            },
                            {
                                "type": "text",
                                "text": json.dumps(payload, ensure_ascii=False),
                            },
                        ],
                    },
                ],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        try:
            answer = message_text(response.json()["choices"][0]["message"])
        except (ValueError, KeyError, IndexError, AttributeError) as exc:
            raise InvalidCompletion(f"Ответ VLM без содержимого: {exc}") from exc
    return parse_json(answer)


def image_provider():
    """Провайдер генерации изображений; по умолчанию — адрес основной модели.

    Контракт — OpenAI-совместимый `/images/generations`, поэтому подключается
    любой сервис с таким эндпоинтом: хватает адреса, модели и ключа в окружении.
    """
    url = (
        os.getenv("DESIGNER_IMAGE_BASE_URL") or os.getenv("DESIGNER_LLM_BASE_URL", "")
    ).rstrip("/")
    model = os.getenv("DESIGNER_IMAGE_MODEL", "")
    if not url or not model:
        raise HTTPException(
            503,
            "Configure DESIGNER_IMAGE_MODEL (and DESIGNER_IMAGE_BASE_URL) for image generation",
        )
    return url, model


def image_available():
    return bool(
        os.getenv("DESIGNER_IMAGE_MODEL")
        and (os.getenv("DESIGNER_IMAGE_BASE_URL") or os.getenv("DESIGNER_LLM_BASE_URL"))
    )


async def draw_image(prompt, size=None) -> bytes:
    """Одна картинка по текстовому описанию. Возвращает байты PNG.

    Провайдеры отвечают по-разному: кто-то кладёт base64 в ответ, кто-то отдаёт
    ссылку со сроком жизни. Поддержаны оба варианта, иначе половина совместимых
    сервисов не подключилась бы.
    """
    url, model = image_provider()
    size = size or os.getenv("DESIGNER_IMAGE_SIZE", "1024x1024")
    key = os.getenv("DESIGNER_IMAGE_API_KEY") or os.getenv("DESIGNER_LLM_API_KEY", "local")
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
        response = await client.post(
            url + "/images/generations",
            headers={"Authorization": "Bearer " + key},
            json={
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "response_format": "b64_json",
            },
        )
        response.raise_for_status()
        try:
            item = response.json()["data"][0]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise InvalidCompletion(f"Ответ генератора без картинки: {exc}") from exc
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            loaded = await client.get(item["url"])
            loaded.raise_for_status()
            return loaded.content
    raise InvalidCompletion("Генератор не вернул ни b64_json, ни ссылки")


async def vision_completion(prompt, payload, image_png, attempts=2):
    """Проверка по картинке с повтором: пустой ответ модели не должен терять слайд."""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return await ask_vision(prompt, payload, image_png)
        except (InvalidCompletion, ValueError, httpx.HTTPError) as exc:
            last = exc
            LOGGER.warning("Vision attempt %s/%s failed: %s", attempt, attempts, exc)
            if attempt < attempts and RETRY_DELAY:
                await asyncio.sleep(RETRY_DELAY)
    raise InvalidCompletion(str(last) or "VLM не ответила")


async def completion(agent, payload, validate=None):
    """Call one agent and return a usable answer.

    `validate` turns a parsed answer into the value the caller needs and raises
    ValueError when the answer is unusable. Schema misses are retried with the
    reason attached, so a weaker model gets a second chance instead of a 502.
    """
    prompt = (PROMPTS / workflow()["agents"][agent]).read_text()
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    last = "LLM provider failed or returned invalid JSON"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        answer = None
        try:
            answer = await ask(messages)
            value = parse_json(answer)
            return validate(value) if validate else value
        except httpx.HTTPError as exc:
            last = f"Провайдер недоступен: {exc.__class__.__name__}"
        except (InvalidCompletion, ValueError) as exc:
            last = str(exc) or exc.__class__.__name__
            if answer is not None:
                # Show the model its own answer; repeating only the rule rarely helps.
                messages = messages[:2] + [
                    {"role": "assistant", "content": answer[:4000]},
                    {
                        "role": "user",
                        "content": (
                            f"Предыдущий ответ не подошёл: {last}. "
                            "Верни только JSON, строго по схеме, без пояснений и текста вокруг."
                        ),
                    },
                ]
        LOGGER.warning("Agent %s attempt %s/%s failed: %s", agent, attempt, MAX_ATTEMPTS, last)
        if attempt < MAX_ATTEMPTS and RETRY_DELAY:
            await asyncio.sleep(RETRY_DELAY * attempt)
    raise HTTPException(502, f"Модель не вернула корректный ответ: {last}")


# A 32k-token window holds roughly this much Russian text next to the schema and
# the instructions. Long content packs are selected down to fit instead of failing.
CONTEXT_BUDGET = max(2000, int(os.getenv("DESIGNER_CONTEXT_CHARS", "24000")))
CHUNK_SIZE = 1200

WORD = re.compile(r"\w{4,}", re.UNICODE)


def chunk_text(text, size=CHUNK_SIZE):
    """Split on blank lines, then pack paragraphs into chunks of about `size`."""
    chunks, current = [], ""
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        while len(paragraph) > size:
            # A single huge paragraph still has to be cut somewhere.
            cut = paragraph.rfind(" ", 0, size) or size
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if len(current) + len(paragraph) + 2 > size and current:
            chunks.append(current.strip())
            current = ""
        current += paragraph + "\n\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks


def relevance(chunk, terms):
    """Share of the query vocabulary present in this chunk."""
    if not terms:
        return 0.0
    words = set(WORD.findall(chunk.lower()))
    return len(words & terms) / len(terms)


def select_context(sources, query, budget=CONTEXT_BUDGET):
    """Fit the sources into the model's window, keeping what the brief asks about.

    Order inside a document is preserved, so the planner still sees a narrative,
    and every source keeps its id: dropped text never breaks source_refs.
    """
    total = sum(len(s["text"]) for s in sources)
    if total <= budget:
        return sources
    terms = set(WORD.findall(query.lower()))
    scored = []
    for source in sources:
        chunks = chunk_text(source["text"])
        for position, chunk in enumerate(chunks):
            # The opening of a document carries context a keyword match misses.
            head_bonus = 0.25 if position == 0 else 0.0
            scored.append(
                {
                    "source": source["id"],
                    "position": position,
                    "text": chunk,
                    "score": relevance(chunk, terms) + head_bonus,
                }
            )
    scored.sort(key=lambda item: (-item["score"], item["source"], item["position"]))
    kept, used = [], 0
    for item in scored:
        if used + len(item["text"]) > budget:
            continue
        kept.append(item)
        used += len(item["text"])
    result = []
    for source in sources:
        parts = sorted(
            (item for item in kept if item["source"] == source["id"]),
            key=lambda item: item["position"],
        )
        text = "\n\n[...]\n\n".join(item["text"] for item in parts)
        # A source that lost every chunk still appears, so its id stays valid.
        result.append({**source, "text": text or source["text"][:1000]})
    return result


NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


# Разряды в русском тексте разделяются пробелом: «1 400 рублей» — то же число,
# что и «1400» на слайде.
THOUSANDS = re.compile(r"(?<=\d)[\s  ](?=\d{3}(?!\d))")


def numbers_in(text):
    """Numbers as written, with digit grouping and decimal separator normalised."""
    joined = THOUSANDS.sub("", text)
    return {value.replace(",", ".") for value in NUMBER.findall(joined)}


def known_numbers(sources):
    return numbers_in("\n".join(source["text"] for source in sources))


# Модель пишет типографские символы, которых в фирменных гарнитурах обычно нет:
# неразрывный дефис в «дизайн‑система», узкий пробел в «1 400». В шаблоне на
# Play или Poppins такой символ выводится пустым прямоугольником, и аудит
# справедливо считает это ошибкой. Приводим их к простым эквивалентам: дефис
# остаётся дефисом, неразрывный пробел — обычным пробелом.
TYPOGRAPHY = str.maketrans(
    {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "−": "-",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        "​": "",
        "‌": "",
        "‍": "",
        "﻿": "",
    }
)


def tidy_label(text):
    """Подпись внутри визуализации: только типографика и лишние пробелы."""
    return " ".join(text.translate(TYPOGRAPHY).split())


def tidy_visual(visual):
    """Подписи диаграмм и таблиц — тот же текст на слайде, те же правила."""
    visual.categories = [tidy_label(value) for value in visual.categories]
    visual.columns = [tidy_label(value) for value in visual.columns]
    visual.steps = [tidy_label(value) for value in visual.steps]
    visual.rows = [[tidy_label(cell) for cell in row] for row in visual.rows]
    visual.unit = tidy_label(visual.unit)
    for series in visual.series:
        series.name = tidy_label(series.name)
    return visual


def tidy_line(text):
    """Тезис так, как его пишут в презентациях: с заглавной и без точки.

    Модель возвращает то строчную букву, то точку в конце, то и другое в одной
    колоде. Это не вопрос вкуса: разнобой сразу виден на слайде, а чинить его
    правилом дешевле, чем просить модель ещё раз.
    """
    value = tidy_label(text)
    if not value:
        return value
    if value[0].islower():
        value = value[0].upper() + value[1:]
    while value.endswith(".") and not value.endswith(".."):
        value = value[:-1].rstrip()
    return value


def unsupported_numbers(text, known, minimum=10):
    """Numbers on a slide that no source states literally.

    The brief demands that every figure on a slide exists in the materials, so a
    derived percentage is as wrong as an invented one.

    Однозначные числа не в счёт: «три команды» в материалах и «3 команды» на
    слайде — одно и то же, а ловить такое по цифрам значит заваливать генерацию
    на ровном месте. Их всё равно перепроверит детерминированный аудит.
    """
    found = numbers_in(text) - known
    return sorted(
        value
        for value in found
        if "." in value or float(value) >= minimum
    )


def number_label(value):
    """Число так, как его пишут в тексте: 4.0 → «4», 1.5 → «1.5»."""
    value = float(value)
    return str(int(value)) if value.is_integer() else repr(value)


def fabricated_chart(visual, known):
    """Диаграмма, чьи значения не взяты из материалов: (причина, порядковый ряд).

    Пустая причина — диаграмма построена по данным.

    Модели, которой нечего рисовать, проще всего пронумеровать этапы — 1, 2, 3,
    4 — и построить по номерам столбики. Проверка тезисов однозначные числа
    пропускает («три команды» и «3 команды» — одно и то же), поэтому значения
    диаграммы сверяются с материалами все, а порядковый ряд отклоняется, даже
    если такие цифры в тексте случайно встречаются.
    """
    data = visual if isinstance(visual, dict) else visual.model_dump()
    if data.get("kind") not in ("bar", "line"):
        return "", False
    for series in data.get("series") or []:
        values = [float(v) for v in series.get("values") or []]
        name = series.get("name") or "без названия"
        if len(values) >= 3 and values == [float(i + 1) for i in range(len(values))]:
            return f"ряд «{name}» — порядковые номера 1…{len(values)}, а не данные", True
        missing = sorted({number_label(v) for v in values} - known, key=float)
        if missing:
            return f"в ряду «{name}» значений {', '.join(missing[:5])} нет в материалах", False
    return "", False


def same_text(text):
    """Ключ для сравнения фраз: регистр, «ё», пунктуация и пробелы не в счёт."""
    value = text.lower().replace("ё", "е")
    return " ".join(re.sub(r"[^\w%]+", " ", value).split())


def repeated_items(slides):
    """Повторы внутри колоды: тезис, уже сказанный на другом слайде или в заголовке.

    Короткий бриф, растянутый на десять слайдов, выдаёт себя именно так: одна и
    та же строка стоит заголовком на одном слайде и тезисом на двух других.
    Сравнение точное с точностью до регистра и пунктуации — перефразирование
    не ловим, зато и ложных находок нет. Возвращает пары (номер слайда, текст)
    для каждого повтора после первого упоминания.
    """
    titles = {}
    for index, slide in enumerate(slides):
        titles.setdefault(same_text(slide["title"]), index)
    seen, repeats = {}, []
    for index, slide in enumerate(slides):
        own_title = same_text(slide["title"])
        visual = slide.get("visual") or {}
        for item in [*slide["bullets"], *visual.get("steps", [])]:
            key = same_text(item)
            if not key:
                continue
            if key == own_title or titles.get(key, index) != index:
                # Тезис повторяет заголовок — свой или чужого слайда.
                repeats.append((index, item))
            elif seen.get(key, index) != index:
                repeats.append((index, item))
            else:
                seen.setdefault(key, index)
    return repeats


def drop_repeats(outline):
    """Последняя попытка: убрать повторы, а не ронять колоду.

    Слайд, у которого после чистки не осталось ни тезисов, ни визуализации, уходит
    целиком — он и был повтором. Обложка остаётся всегда.
    """
    found = {}
    for index, item in repeated_items([s.model_dump() for s in outline.slides]):
        found.setdefault(index, set()).add(item)
    for index, items in found.items():
        slide = outline.slides[index]
        slide.bullets = [b for b in slide.bullets if b not in items]
        if slide.visual.kind in ("process", "icon", "cycle", "pyramid", "timeline"):
            steps = [step for step in slide.visual.steps if step not in items]
            slide.visual = (
                slide.visual.model_copy(update={"steps": steps}) if steps else Visual()
            )
    outline.slides = [
        slide
        for index, slide in enumerate(outline.slides)
        if index == 0 or slide.bullets or slide.visual.kind != "none"
    ]
    return outline


def sources_for(store, request: Brief):
    result = [{"id": "brief", "text": request.brief}]
    for identifier in request.content_pack_ids:
        item = store.get("content_packs", identifier)
        result.append({"id": identifier, "text": item["text"]})
    if sum(len(s["text"]) for s in result) > 120000:
        raise HTTPException(422, "Combined source text exceeds 120000 characters")
    return result


def outline_overflow(outline, capacity, max_bullets=6):
    """Слайды, где текста заметно больше, чем помещается."""
    heavy = []
    for index, slide in enumerate(outline["slides"]):
        text = len(slide["title"]) + sum(len(b) for b in slide["bullets"])
        # Визуализация занимает место: под текст остаётся примерно половина.
        room = capacity if slide["visual"]["kind"] == "none" else capacity * 0.45
        if text > room or len(slide["bullets"]) > max_bullets:
            heavy.append((index, int(room)))
    return heavy


def trim_slide(slide, room, max_bullets=6):
    """Детерминированный запас: подрезать по предложениям, не теряя первых мыслей."""
    bullets = slide["bullets"][:max_bullets]
    budget = max(40, int(room) - len(slide["title"]))
    kept = []
    for bullet in bullets:
        if budget <= 0:
            break
        if len(bullet) > budget:
            cut = bullet[:budget].rstrip()
            cut = cut[: cut.rfind(" ")] if " " in cut else cut
            if len(cut) >= 20:
                kept.append(cut)
            break
        kept.append(bullet)
        budget -= len(bullet)
    slide["bullets"] = kept or bullets[:1]
    return slide


async def balance_outline(outline, template, capacity=None):
    """Уложить тексты в то место, которое даёт шаблон.

    Сначала считаем вместимость по дизайн-системе шаблона, затем просим модель
    сократить перегруженные слайды, сохранив числа и факты. Если модель недоступна
    или ответила негодно, подрезаем детерминированно: лучше короткий слайд, чем
    текст, наползающий на соседний блок.
    """
    from .layout import slide_capacity

    capacity = capacity or slide_capacity(template)
    heavy = outline_overflow(outline, capacity)
    if not heavy:
        return outline
    payload = {
        "capacity_chars": capacity,
        "slides": [
            {
                "index": index,
                "title": outline["slides"][index]["title"],
                "bullets": outline["slides"][index]["bullets"],
                "limit_chars": room,
                "max_bullets": 6,
            }
            for index, room in heavy
        ],
    }
    rooms = dict(heavy)
    try:
        result = await completion("condense", payload)
        for item in result.get("slides", []):
            index = item.get("index")
            if not isinstance(index, int) or index not in rooms:
                continue
            slide = outline["slides"][index]
            bullets = [str(b).strip() for b in item.get("bullets", []) if str(b).strip()]
            if bullets:
                slide["bullets"] = bullets[:6]
            title = str(item.get("title") or "").strip()
            if title:
                slide["title"] = title
    except HTTPException as exc:
        LOGGER.warning("Condense agent unavailable: %s", exc.detail)
    for index, room in heavy:
        slide = outline["slides"][index]
        text = len(slide["title"]) + sum(len(b) for b in slide["bullets"])
        if text > room * 1.15 or len(slide["bullets"]) > 6:
            trim_slide(slide, room)
    return outline


async def generate_outline(request, sources, warnings=None):
    """План колоды по брифу и материалам.

    `warnings` — список, куда попадает то, о чём пользователь должен знать, но
    что не повод прерывать работу: например, что модель собрала меньше слайдов,
    чем просили. Задача кладёт этот список в интерфейс.
    """
    allowed = {s["id"] for s in sources}

    known = known_numbers(sources)
    # Счётчик попыток: на последней принимаем меньшее число слайдов, чем просили.
    # Колода из трёх слайдов лучше, чем ошибка вместо презентации; расхождение
    # видно в ответе и в интерфейсе.
    attempt = {"n": 0}

    def validate(result):
        attempt["n"] += 1
        last_chance = attempt["n"] >= MAX_ATTEMPTS
        outline = Outline.model_validate(result)
        count = len(outline.slides)
        # ТЗ задаёт целевой объём, и пользователь задаёт его явно. Перебор не
        # принимаем никогда: это верхняя граница. Недобор возвращаем модели с
        # понятной просьбой — разбить насыщенные слайды или добавить страницу с
        # таблицей либо схемой по материалам, — и соглашаемся на меньшее только
        # когда попытки кончились.
        if count > request.slide_count:
            if not last_chance:
                raise ValueError(
                    f"Слайдов {count}, а просили не больше {request.slide_count}. "
                    "Объедини близкие мысли, не выбрасывая факты."
                )
            outline.slides = outline.slides[: request.slide_count]
            count = len(outline.slides)
        if count < request.slide_count:
            if not last_chance:
                raise ValueError(
                    f"Слайдов {count}, а нужно {request.slide_count}. "
                    "Разбей самые насыщенные слайды на два по смыслу или добавь "
                    "слайды с таблицей либо схемой по материалам: сравнение "
                    "показателей, этапы, сроки. Новые слайды несут факты из "
                    "источников, а не воду."
                )
            LOGGER.warning(
                "Model insisted on %s slides instead of %s", count, request.slide_count
            )
            if warnings is not None:
                warnings.append(
                    f"Модель собрала {count} слайдов вместо {request.slide_count}: "
                    "в материалах не нашлось содержания на остальные. Добавьте "
                    "материалы или уменьшите запрошенный объём."
                )
        unknown = {ref for slide in outline.slides for ref in slide.source_refs} - allowed
        if unknown:
            raise ValueError(
                "Неизвестные source_refs: "
                + ", ".join(sorted(unknown))
                + ". Допустимые: "
                + ", ".join(sorted(allowed))
            )
        deck_text = " ".join(
            slide.title + " " + " ".join(slide.bullets) for slide in outline.slides
        )
        cyrillic = len(CYRILLIC.findall(deck_text)) > len(LATIN.findall(deck_text))
        strangers = sorted(
            {
                label
                for slide in outline.slides
                for label in foreign_labels(
                    visual_labels(slide.visual.model_dump()), cyrillic
                )
            }
        )
        if strangers and not last_chance:
            raise ValueError(
                "Подписи в визуализациях на другом языке: "
                + ", ".join(strangers[:8])
                + ". Переведи все подписи, названия серий и единицы на язык колоды."
            )
        if strangers:
            # Последняя попытка: колода без одной диаграммы лучше, чем ошибка
            # вместо колоды. Снимаем визуализации с чужими подписями и говорим
            # об этом в логе — аудит потом отметит слайд без визуализации.
            LOGGER.warning("Dropped visuals with foreign labels: %s", strangers[:8])
            for slide in outline.slides:
                if foreign_labels(visual_labels(slide.visual.model_dump()), cyrillic):
                    slide.visual = Visual()
        titles = [slide.title.strip().lower() for slide in outline.slides]
        repeated = {title for title in titles if titles.count(title) > 1}
        if repeated:
            # Повтор заголовка — это два слайда об одном и том же: аудит потом
            # отметит дубль, но лучше не доводить до готовой колоды.
            raise ValueError(
                "Заголовки повторяются: "
                + ", ".join(sorted(repeated)[:4])
                + ". Каждый слайд несёт свою мысль."
            )
        charts = [
            (index, fabricated_chart(slide.visual, known)[0])
            for index, slide in enumerate(outline.slides)
        ]
        charts = [(index, reason) for index, reason in charts if reason]
        if charts and not last_chance:
            raise ValueError(
                "; ".join(f"слайд {index + 1}: диаграмма без данных, {reason}" for index, reason in charts)
                + ". Значения диаграммы — только числа из материалов дословно. "
                "Нет данных — нет диаграммы: возьми схему, таблицу или список."
            )
        for index, reason in charts:
            # Последняя попытка: слайд без диаграммы лучше выдуманного графика.
            LOGGER.warning("Dropped chart without data on slide %s: %s", index + 1, reason)
            outline.slides[index].visual = Visual()
        repeats = repeated_items([slide.model_dump() for slide in outline.slides])
        if repeats and not last_chance:
            raise ValueError(
                "; ".join(
                    f"слайд {index + 1}: «{item}» уже есть в заголовке или на другом слайде"
                    for index, item in repeats[:6]
                )
                + ". Каждый факт звучит в колоде один раз, а тезис не повторяет "
                "заголовок. Если материала мало, лучше меньше слайдов."
            )
        if repeats:
            before = len(outline.slides)
            LOGGER.warning("Dropping repeated items on the last attempt: %s", repeats[:6])
            drop_repeats(outline)
            if warnings is not None and len(outline.slides) < before:
                warnings.append(
                    f"Модель повторяла одни и те же тезисы: {before - len(outline.slides)} "
                    "слайд(ов) без собственного содержания убраны."
                )
        invented = unsupported_numbers(
            "\n".join(
                slide.title + "\n" + "\n".join(slide.bullets)
                for slide in outline.slides
            ),
            known,
        )
        if invented and last_chance:
            # Последняя попытка: колода с помеченным числом полезнее, чем ошибка
            # вместо колоды. Детерминированный аудит покажет это число
            # пользователю как неподтверждённое — там его и видно.
            LOGGER.warning("Shipping outline with unverified numbers: %s", invented[:8])
        elif invented:
            # Ask again instead of shipping the figure: the audit would flag it and
            # the user would have to rewrite the slide by hand.
            raise ValueError(
                "Числа отсутствуют в источниках: "
                + ", ".join(invented[:8])
                + ". Используй только те цифры, что есть в материалах дословно, "
                "и не вычисляй проценты, кратности и суммы."
            )
        outline.title = tidy_line(outline.title)
        for slide in outline.slides:
            slide.title = tidy_line(slide.title)
            slide.bullets = [tidy_line(b) for b in slide.bullets if b.strip()]
            tidy_visual(slide.visual)
        return outline

    return await completion(
        "outline",
        {
            **request.model_dump(exclude={"outline", "template_id"}),
            "narrative": narrative(request.purpose),
            "sources": select_context(sources, request.brief),
            "schema": Outline.model_json_schema(),
        },
        validate=validate,
    )
