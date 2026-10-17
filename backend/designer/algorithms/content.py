import re
from copy import deepcopy
from ..models import Outline, SlideContent, Visual
from ..workflow import narrative_beats

TOPIC_MAX_WORDS = 2

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

THOUSANDS = re.compile(r"(?<=\d)[\s  ](?=\d{3}(?!\d))")

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

def fit_schema_limits(result):
    """Обрезать списки плана до пределов схемы — только для последней попытки.

    Модель иногда присылает седьмой шаг процесса при пределе в шесть. На первых
    попытках это причина переспросить, а на последней — не повод остаться без
    колоды: лишнее отрезается, остальное проходит проверку как обычно.
    """
    from annotated_types import MaxLen

    def limit(model, name):
        field = model.model_fields.get(name)
        if field is None:
            return None
        return next((m.max_length for m in field.metadata if isinstance(m, MaxLen)), None)

    if not isinstance(result, dict):
        return result
    result = deepcopy(result)
    slides = result.get("slides")
    if isinstance(slides, list):
        cap = limit(Outline, "slides")
        if cap is not None:
            del slides[cap:]
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            cap = limit(SlideContent, "bullets")
            if cap is not None and isinstance(slide.get("bullets"), list):
                slide["bullets"] = slide["bullets"][:cap]
            visual = slide.get("visual")
            if not isinstance(visual, dict):
                continue
            for name, value in list(visual.items()):
                cap = limit(Visual, name)
                if cap is not None and isinstance(value, list):
                    visual[name] = value[:cap]
    return result

def beat_title(title, beats=None):
    """Шаг каркаса, которым открывается заголовок, или None.

    «Ожидаемый эффект: скорость сборки» — это подпись раздела, а не вывод:
    модель берёт название шага из каркаса и ставит его префиксом. Проверка
    намеренно узкая — только шаги каркаса с двоеточием или тире после них,
    чтобы не трогать заголовки-выводы вроде «Итог: сборка ускорилась в 46 раз».
    """
    text = (title or "").strip().lower().rstrip(".!?…")
    for beat in beats if beats is not None else narrative_beats():
        head = beat.lower()
        # Шаг целиком («Предложение», «Что мы просим решить») — тоже подпись раздела.
        if text == head:
            return beat
        if text.startswith(head) and re.match(r"\s*[:—–-]", text[len(head):]):
            return beat
    return None

def topic_title(title, beats=None):
    """Почему заголовок — тема, а не вывод, или None.

    Две причины: заголовок открывается шагом каркаса или равен ему, либо в нём
    не больше двух слов и нет ни одного числа.
    """
    beat = beat_title(title, beats)
    if beat:
        return f"название раздела «{beat}»"
    words = re.findall(r"[\wЁё]+", title or "")
    if words and len(words) <= TOPIC_MAX_WORDS and not any(ch.isdigit() for ch in title):
        return "короткая подпись без вывода"
    return None

def strip_beat(title, beats=None):
    """Заголовок без названия раздела впереди или пустая строка, если остаётся мало.

    «Ожидаемый эффект: скорость сборки» → «Скорость сборки». Если после снятия
    остаётся одно слово, заголовок не трогаем: огрызок хуже подписи раздела.
    """
    beat = beat_title(title, beats)
    if not beat:
        return ""
    rest = re.sub(r"^\s*[:—–-]\s*", "", title.strip()[len(beat):]).strip()
    if len(rest.split()) < 2:
        return ""
    return rest[0].upper() + rest[1:]

def numbers_in(text):
    """Numbers as written, with digit grouping and decimal separator normalised."""
    joined = THOUSANDS.sub("", text)
    return {value.replace(",", ".") for value in NUMBER.findall(joined)}

def known_numbers(sources):
    return numbers_in("\n".join(source["text"] for source in sources))

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

