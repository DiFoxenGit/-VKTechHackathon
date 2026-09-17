"""Shared geometry model for editing, audit and native export. Units: points."""

import copy
import math

from .parsing import best_text_color

DEFAULT_SAFE_AREA = {"x": 0.055, "y": 0.055, "w": 0.89, "h": 0.825}
DEFAULT_MARGINS = {"x": 0.04, "y": 0.04, "w": 0.92, "h": 0.9}
# Below this a two-column split leaves both columns nearly empty.
MIN_BULLETS_FOR_COLUMNS = 4
# Разброс светлоты, после которого фон считается пёстрым: по нему текст не читается.
BUSY_BACKGROUND = 0.12


def estimated_text_height(element):
    """Rough height of a text block: the same estimate for layout and audit.

    Layout uses it to pick a size that fits, audit to report what does not. They
    must share one formula, otherwise the composer produces slides its own audit
    rejects.
    """
    _, _, w, _ = element["box"]
    size = element["font_size"]
    chars = max(1, (w - 12) / (size * 0.55))
    return (
        sum(max(1, math.ceil(len(line) / chars)) for line in element["text"].splitlines())
        * size
        * 1.3
        + 8
    )


def ink_area(element):
    """Area a block actually covers once rendered; a text box is usually emptier."""
    _, _, w, h = element["box"]
    if element["kind"] == "text":
        return w * min(h, estimated_text_height(element))
    return w * h


def grow_text(elements, scale, slide_area, target=0.3, maximum=60):
    """Raise the type size while the slide still reads as empty.

    The focus variant carries one thought per slide. With the body size of a dense
    layout such a slide covers a fifth of the page, which the audit rightly calls
    empty; a pitch slide answers that with bigger type, not with filler text.
    """
    if not slide_area:
        return elements
    steps = sorted(s for s in scale if s <= maximum)
    for _ in range(4):
        if sum(ink_area(e) for e in elements) / slide_area >= target:
            break
        grew = False
        for element in elements:
            if element["kind"] != "text":
                continue
            larger = [s for s in steps if s > element["font_size"]]
            if not larger:
                continue
            candidate = dict(element, font_size=larger[0])
            if estimated_text_height(candidate) <= element["box"][3]:
                element["font_size"] = larger[0]
                grew = True
        if not grew:
            break
    return elements


def center_content(elements, top, bottom):
    """Прижать разреженный контент к оптической середине области.

    Три строки, прибитые к верхнему краю большой пустой области, читаются как
    недоделанный слайд. Если содержимое занимает меньше половины места, опускаем
    его на треть свободного пространства — так слайд выглядит собранным.
    """
    # Блоки в рамках шаблона не двигаем: их положение — решение дизайнера.
    body = [
        e for e in elements if e.get("role") != "title" and not e.get("from_template")
    ]
    if not body:
        return elements
    used_top = min(e["box"][1] for e in body)
    used_bottom = max(
        e["box"][1]
        + (min(e["box"][3], estimated_text_height(e)) if e["kind"] == "text" else e["box"][3])
        for e in body
    )
    available = bottom - top
    used = used_bottom - used_top
    if available <= 0 or used >= available * 0.55:
        return elements
    # Рамка ужимается до фактической высоты текста, иначе сдвиг вынесет пустой
    # низ блока за пределы слайда, и аудит справедливо это заметит.
    for element in body:
        if element["kind"] == "text":
            element["box"][3] = min(
                element["box"][3], max(24.0, estimated_text_height(element))
            )
    shift = (available - used) / 3
    for element in body:
        element["box"][1] += shift
    return elements


def dodge_decor(elements, reserved, bottom, gap):
    """Опустить блок, который наехал на мелкий декор шаблона.

    Иконка над подписью, разделитель, уголок — их положение задал дизайнер, и
    правильный ответ не «убрать декор», а начать текст ниже него. Двигаем только
    вниз и только пока блок остаётся в отведённой области: уехавший за край
    текст хуже, чем близкое соседство с линией.
    """
    for element in elements:
        if element.get("role") == "title" or element.get("from_template"):
            continue
        x, y, w, h = element["box"]
        for bx, by, bw, bh in reserved:
            if bx >= x + w or bx + bw <= x or by >= y + h or by + bh <= y:
                continue
            if (bw * bh) > 0.5 * (w * h):
                # Крупная плашка — это фон страницы, а не помеха.
                continue
            shifted = by + bh + gap
            if shifted + h > bottom or shifted <= y:
                continue
            # Уйти от декора на чужой блок — не решение: проверяем, свободно ли
            # место, куда двигаем.
            clash = any(
                other is not element
                and other["box"][0] < x + w
                and other["box"][0] + other["box"][2] > x
                and other["box"][1] < shifted + h
                and other["box"][1] + other["box"][3] > shifted
                for other in elements
            )
            if clash:
                continue
            element["box"][1] = shifted
            y = shifted
    return elements


def fit_text(element, scale, minimum=12):
    """Step the font down the template's own scale until the text fits its box."""
    height = element["box"][3]
    if estimated_text_height(element) <= height:
        return element
    for size in sorted({s for s in scale if minimum <= s <= element["font_size"]}, reverse=True):
        element["font_size"] = size
        if estimated_text_height(element) <= height:
            break
    return element


def content_demand(content, position=1, total=1):
    """How much room this slide needs and what kind of room."""
    bullets = content["bullets"]
    return {
        "lines": sum(1 + len(b) // 60 for b in bullets),
        "has_visual": content["visual"]["kind"] != "none",
        "title_length": len(content["title"]),
        # Первый слайд — обложка: у шаблона для неё свои страницы, с крупным
        # заголовком по центру и почти без текстовых блоков. Но если модель
        # начала колоду сразу с содержания, обложечная страница ему не подходит:
        # четыре тезиса поверх фонового фото — не титул.
        "cover": position == 0 and len(bullets) <= 1,
        "closing": total > 2 and position == total - 1,
        # Сколько карточек пригодилось бы этому слайду.
        "cards": 0 if content["visual"]["kind"] != "none" else len(bullets),
    }


# Band where composed content actually lands; branding here is what collides.
CONTENT_BAND = (0.05, 0.22, 0.95, 0.9)


def free_area(pattern):
    """Share of the slide left for content once template branding is placed."""
    used = sum(b["w"] * b["h"] for b in pattern.get("reserved", []))
    return max(0.0, 1.0 - min(1.0, used))


def branding_in_band(pattern):
    """Branding area that sits where the content will go, as a slide fraction.

    A logo in the corner costs nothing; a decorative panel across the middle of
    the page makes every block on that pattern collide with the template.
    """
    left, top, right, bottom = CONTENT_BAND
    total = 0.0
    for box in pattern.get("reserved", []):
        if box["w"] * box["h"] >= 0.6:
            # Иллюстрация во весь слайд — это фон страницы, а не препятствие:
            # её учитывает image_cover, а читаемость — подложка под текстом.
            continue
        overlap_w = max(0.0, min(box["x"] + box["w"], right) - max(box["x"], left))
        overlap_h = max(0.0, min(box["y"] + box["h"], bottom) - max(box["y"], top))
        total += overlap_w * overlap_h
    return round(total, 5)


def candidate_patterns(patterns):
    """Content pages a new slide can be built on, best first.

    Strict picks are full-width title pages. Some templates carry only one such
    slide, so the pool is widened until there is something to choose from:
    repeating one pattern twelve times is a worse outcome than a looser match.
    """

    def usable(pattern, min_slots, max_title_y, min_title_w):
        box = pattern.get("title_box")
        return bool(
            pattern["text_slots"] >= min_slots
            and box
            and box["y"] < max_title_y
            and box["w"] > min_title_w
        )

    # Обложка и финал шаблона почти никогда не проходят по строгим признакам
    # контентной страницы: заголовок стоит низко, текстовых рамок одна-две.
    # Но именно там дизайнер оставил место под название и автора, поэтому они
    # входят в пул отдельно, а штрафы по роли не дают взять их под тезисы.
    special = [
        p
        for p in patterns
        if p.get("role") in ("cover", "closing") and p.get("title_box")
    ]

    def widen(found):
        extra = [p for p in special if p["index"] not in {f["index"] for f in found}]
        return [*found, *extra]

    for rule in ((2, 0.2, 0.65), (2, 0.3, 0.45), (1, 0.45, 0.3)):
        found = [p for p in patterns if usable(p, *rule)]
        # Сначала страницы без украшений в рабочей области: заглушки под фото
        # наследуются от макета и остаются на готовом слайде пустыми кругами.
        clean = [
            p
            for p in found
            if not p.get("decoration_count") and branding_in_band(p) < 0.12
        ]
        if len(clean) >= 3:
            return widen(clean)
        if len(found) >= 3:
            return widen(found)
    return widen([p for p in patterns if p.get("title_box")]) or patterns


def score_pattern(pattern, demand, recent, uses=0):  # noqa: C901 - правила подбора
    """Rank a template pattern for one slide.

    Selection must be explainable on stage: a busy pattern loses points when the
    slide is dense, a pattern with room wins when a chart has to fit, and repeating
    the neighbour's pattern is penalised so the deck does not look like one slide
    printed twelve times.
    """
    dense = demand["has_visual"] or demand["lines"] > 4
    role = pattern.get("role", "content")
    # Страница, нарисованная ровно под эту задачу: обложка под обложку, финал
    # под финал. Её фотофон и композиция — замысел дизайнера, а не помеха.
    designed = (demand.get("cover") and role == "cover") or (
        demand.get("closing") and role == "closing"
    )
    score = 1.0
    score -= pattern.get("decoration_area", 0.0) * (2.4 if dense else 0.8)
    # Шаблон может держать в макете россыпь мелких украшений: на пустом слайде
    # они остаются висеть и читаются как забытые заглушки.
    score -= min(0.4, 0.05 * pattern.get("decoration_count", 0))
    # Страница с фотографией во весь слайд — обложка или раздел, а не место для
    # текста: контраст там непредсказуем.
    score -= 0.0 if designed else 1.6 * pattern.get("image_cover", 0.0)
    score -= 1.2 * max(0.0, pattern.get("bg_spread", 0.0) - BUSY_BACKGROUND)
    # Декор внутри рабочей зоны — главный источник наездов текста на графику.
    # Дешевле взять другую страницу шаблона, чем воевать с ней геометрией.
    score -= branding_in_band(pattern) * (0.8 if designed else 5.0)
    score += free_area(pattern) * (0.5 if demand["has_visual"] else 0.2)
    score += 0.05 * min(pattern.get("text_slots", 0), 4)
    title_box = pattern.get("title_box")
    if title_box:
        score += 0.12 if title_box["w"] > 0.6 else 0.0
        # A shallow title band cannot hold a long conclusion-style headline.
        if demand["title_length"] > 60 and title_box["h"] < 0.1:
            score -= 0.15
    if demand.get("cover"):
        # Обложка шаблона — именно та страница, где дизайнер оставил место под
        # название и автора.
        score += 1.2 if role == "cover" else 0.0
        score -= 1.6 if role in ("agenda", "team", "closing") else 0.0
    elif demand.get("closing"):
        score += 0.8 if role == "closing" else 0.0
        score -= 0.6 if role == "cover" else 0.0
    else:
        # Контентные страницы: обложки, разделители и визитка команды сюда не годятся.
        score -= {
            "cover": 0.9,
            "section": 0.5,
            "agenda": 1.2,
            "closing": 0.7,
            "team": 1.5,
        }.get(role, 0.0)
    cards = demand.get("cards")
    if cards:
        grid = len(card_slots(pattern.get("slots") or [], 1.0, 1.0))
        if grid:
            # Сетка под число тезисов: пустые карточки читаются как недоделка,
            # а тезисы, не поместившиеся в карточки, слипаются в последней.
            score += 0.45 if grid == cards else -0.18 * abs(grid - cards)
    if demand.get("cover"):
        # Обложка шаблона: мало текстовых рамок, заголовок крупный и не у самого
        # верха. Обычная контентная страница на её месте выглядит как ошибка.
        title_box = pattern.get("title_box") or {}
        score += 0.5 if pattern.get("text_slots", 0) <= 3 else -0.3
        score += 0.4 if title_box.get("y", 0) > 0.2 else 0.0
        score += 0.3 if title_box.get("h", 0) > 0.15 else 0.0
    if recent and pattern["index"] == recent[-1]:
        score -= 0.6
    # Reuse is allowed, but every repeat costs more, so a deck spreads over the
    # patterns the template actually offers.
    score -= 0.22 * uses
    return round(score, 6)


def choose_pattern(candidates, content, recent, usage=None, position=1, total=1):
    demand = content_demand(content, position, total)
    usage = usage or {}
    scored = [
        (score_pattern(p, demand, recent, usage.get(p["index"], 0)), -p["index"], p)
        for p in candidates
    ]
    # Deterministic: equal scores resolve by the lowest pattern index.
    best = max(scored, key=lambda item: (item[0], item[1]))
    return best[2], best[0]


def decor_free_band(reserved, top, bottom, left, right, minimum=0.45):
    """Самая большая полоса без декора шаблона.

    Нужна варианту «фокус»: он занимает почти весь слайд одной мыслью, и любая
    линия шаблона проходит прямо по тексту. Если свободная полоса выходит слишком
    узкой, оставляем как было — тесный текст хуже, чем замечание аудита.
    """
    blockers = [
        b
        for b in reserved
        if b[1] < bottom and b[1] + b[3] > top and b[0] < right and b[0] + b[2] > left
    ]
    if not blockers:
        return top, bottom
    bands, cursor = [], top
    for box in sorted(blockers, key=lambda b: b[1]):
        if box[1] - cursor > 0:
            bands.append((cursor, box[1]))
        cursor = max(cursor, box[1] + box[3])
    if bottom - cursor > 0:
        bands.append((cursor, bottom))
    if not bands:
        return top, bottom
    best = max(bands, key=lambda band: band[1] - band[0])
    if best[1] - best[0] < (bottom - top) * minimum:
        return top, bottom
    return best


def union_box(boxes):
    """Общий прямоугольник для набора рамок прототипа."""
    if not boxes:
        return None
    left = min(b["x"] for b in boxes)
    top = min(b["y"] for b in boxes)
    right = max(b["x"] + b["w"] for b in boxes)
    bottom = max(b["y"] + b["h"] for b in boxes)
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def slot_size(style, scale, fallback, minimum=12, maximum=96):
    """Кегль из шаблона, если он вменяемый; иначе наш расчёт по шкале.

    Мастер иногда объявляет заголовок 14 pt, хотя на слайдах он вдвое крупнее:
    значение унаследовано из офисных умолчаний и ничего не говорит о дизайне.
    Такой кегль отбрасываем — лучше расчёт по высоте слайда и шкале шаблона.
    """
    size = style.get("size")
    if not size or size < minimum or size > maximum:
        return fallback
    # Заметно мельче расчётного — признак умолчания, а не решения дизайнера.
    if size < fallback * 0.55:
        return fallback
    return size


def card_slots(body_slots, width, height, minimum=2, maximum=6):
    """Одинаковые блоки прототипа — готовая карточная сетка шаблона.

    Шаблоны почти всегда содержат страницы с рядом карточек. Разложить тезисы по
    ним куда лучше, чем печатать их списком: слайд сразу выглядит как страница
    той же презентации, а не как текст на пустом фоне.
    """
    # Мелкие подписи тоже повторяются рядами, но это не карточки: текст в них
    # окажется микроскопическим, а слайд — пустым. Берём только крупную сетку
    # внутри рабочей области.
    # Дизайнеры паркуют запасные блоки за краем страницы: в сетку они не
    # годятся, текст в них уедет со слайда.
    boxes = [
        s["box"]
        for s in body_slots
        if s.get("role", "body") == "body"
        and s["box"]["y"] >= 0.18
        and s["box"]["x"] >= -0.01
        and s["box"]["x"] + s["box"]["w"] <= 1.01
        and s["box"]["y"] + s["box"]["h"] <= 1.01
    ]
    if len(boxes) < minimum:
        return []
    # Каталог иконок — это тоже ряды одинаковых рамок, но не карточки: класть
    # туда тезисы бессмысленно.
    if len(boxes) > 10:
        return []
    median_w = sorted(b["w"] for b in boxes)[len(boxes) // 2]
    median_h = sorted(b["h"] for b in boxes)[len(boxes) // 2]
    # Карточка — блок, куда помещается фраза: примерно от 2% площади слайда.
    if median_w * median_h < 0.02 or median_w < 0.12:
        return []
    cards = [
        b
        for b in boxes
        if abs(b["w"] - median_w) <= median_w * 0.25
        and abs(b["h"] - median_h) <= max(median_h * 0.6, 0.03)
    ]
    if len(cards) < minimum:
        return []
    cards.sort(key=lambda b: (round(b["y"], 2), b["x"]))
    cards = cards[:maximum]
    # Сетка должна занимать заметную часть слайда, иначе контент повиснет в углу.
    if sum(b["w"] * b["h"] for b in cards) < 0.12:
        return []
    return [
        [b["x"] * width, b["y"] * height, b["w"] * width, b["h"] * height]
        for b in cards
    ]


def slot_align(style):
    """Выравнивание абзаца шаблона в терминах экспорта."""
    value = (style.get("align") or "").lower()
    if value.startswith("ctr") or value.startswith("center"):
        return "center"
    if value.startswith("r"):
        return "right"
    if value.startswith("just"):
        return "justify"
    return "left"


def slide_capacity(template, size=None):
    """Сколько символов помещается в контентную область этого шаблона.

    Оценка нужна до вёрстки: если текста больше, его лучше сократить целиком по
    колоде, чем потом уменьшать кегль на конкретном слайде и ломать типографику.
    """
    width = template["width"] / 12700
    height = template["height"] / 12700
    geometry = template.get("geometry") or {}
    safe = geometry.get("safe_area") or DEFAULT_SAFE_AREA
    scale = [s for s in template["tokens"]["font_sizes"] if 10 <= s <= 60]
    body = size or (
        min(scale, key=lambda s: abs(s - height * 0.045)) if scale else 18
    )
    # Контент занимает область ниже заголовка: примерно две трети рабочей высоты.
    area_width = width * safe["w"]
    area_height = height * safe["h"] * 0.62
    per_line = max(1, (area_width - 12) / (body * 0.55))
    lines = max(1, area_height / (body * 1.35))
    return int(per_line * lines * 0.85)


def compose(outline, template, variant):
    width, height = template["width"] / 12700, template["height"] / 12700
    tokens = template["tokens"]
    geometry = template.get("geometry", {})
    safe = geometry.get("safe_area") or DEFAULT_SAFE_AREA
    margins = geometry.get("margins") or DEFAULT_MARGINS
    font = next(
        (f for f in tokens["fonts"] if f not in ("Wingdings", "Symbol")), "Arial"
    )
    palette = tokens["colors"] or ["000000", "FFFFFF"]
    # Use the template's type scale, bounded by physical slide height.
    scale = [s for s in tokens["font_sizes"] if 10 <= s <= 60]
    title_size = min(scale, key=lambda s: abs(s - height * 0.075)) if scale else 28
    body_size = min(scale, key=lambda s: abs(s - height * 0.045)) if scale else 18
    # Акцент берём из фактических цветов шаблона: офисная тема по умолчанию
    # покрасила бы диаграммы чужим синим.
    accents = tokens.get("accents") or []
    accent = accents[0] if accents else tokens["theme"].get("accent1", palette[0])
    slides = []
    candidates = candidate_patterns(template["patterns"])
    # Prefer reusable content pages over covers, speaker cards, and icon catalogues.
    candidates = sorted(
        candidates,
        key=lambda p: (p.get("decoration_area", 0), abs(p["text_slots"] - 4)),
    )
    recent: list[int] = []
    usage: dict[int, int] = {}
    for i, content in enumerate(outline["slides"]):
        pattern, pattern_score = choose_pattern(
            candidates, content, recent, usage, i, len(outline["slides"])
        )
        recent = [*recent, pattern["index"]][-3:]
        usage[pattern["index"]] = usage.get(pattern["index"], 0) + 1
        # Слоты прототипа — готовая композиция шаблона: заголовок и текстовые
        # блоки стоят там, где их поставил дизайнер. Это точнее любой сетки,
        # выведенной статистикой, поэтому берём их, когда они есть.
        slots = pattern.get("slots") or []
        title_slot = next((s for s in slots if s["role"] == "title"), None)
        # Слот за краем страницы — заготовка дизайнера: в композицию он не идёт,
        # иначе тянет за собой границы контентной области.
        body_slots = [
            s
            for s in slots
            if s["role"] == "body"
            and s["box"]["x"] + s["box"]["w"] <= 1.01
            and s["box"]["y"] + s["box"]["h"] <= 1.01
            and s["box"]["x"] >= -0.01
        ]
        content_slot = union_box([s["box"] for s in body_slots])
        title_style = (title_slot or {}).get("style") or {}
        body_style = (body_slots[0] if body_slots else {}).get("style") or {}
        # Margins come from the template's own safe area, not from constants, so an
        # unseen template keeps its own rhythm.
        right = width * min(1.0, safe["x"] + safe["w"])
        title_box = pattern.get("title_box")
        # Заголовок встаёт туда, где его поставил дизайнер. Для обложек и
        # разделов это середина страницы, а не верхняя полоса, поэтому по
        # вертикали допускается почти половина слайда.
        from_template_title = bool(
            title_box and title_box["y"] < 0.45 and title_box["w"] > 0.3
        )
        if from_template_title:
            # Honour the template's title indent, but apply it to every block on the
            # slide: mismatched left edges are the misalignment the audit looks for.
            margin = min(max(width * safe["x"], width * title_box["x"]), width * 0.25)
            ty = max(height * margins["y"], height * title_box["y"])
            tw = min(right - margin, width * title_box["w"])
        else:
            margin = width * safe["x"]
            ty, tw = height * safe["y"], right - margin
        tx = margin
        has_visual = content["visual"]["kind"] != "none"
        # Карточки шаблона стоят на своих местах: заголовок обязан закончиться
        # выше первой из них, иначе длинный заголовок ложится прямо на карточку.
        cards = (
            card_slots(body_slots, width, height)
            if not has_visual and variant != "focus"
            else []
        )
        # Compose around branding the template keeps on every slide: narrow the
        # title away from a corner logo, and drop below a full-width wordmark.
        reserved = [
            (width * b["x"], height * b["y"], width * b["w"], height * b["h"])
            for b in pattern.get("reserved", [])
            if b["w"] * b["h"] < 0.6 and not b.get("icons")
        ]
        if not from_template_title:
            for bx, by, _, bh in reserved:
                if by < height * 0.3 and tx + tw * 0.35 < bx < tx + tw:
                    tw = max(width * 0.3, bx - width * 0.012 - tx)
        # Кегль заголовка — шаблонный, если он объявлен; шкала остаётся запасным
        # вариантом для файлов, где типографика не описана.
        current_title_size = slot_size(title_style, scale, title_size, minimum=18)
        slide_body_size = slot_size(body_style, scale, body_size, minimum=10, maximum=40)

        def title_height(size, title_width=tw, title_text=content["title"]):
            chars = max(1, (title_width - 12) / (size * 0.60))
            return math.ceil(len(title_text) / chars) * size * 1.3 + 10

        for size in sorted(
            {s for s in scale if s <= current_title_size}, reverse=True
        ):
            current_title_size = size
            if title_height(size) <= height * 0.24:
                break
        th = max(height * 0.12, title_height(current_title_size))
        if cards:
            limit = min(box[1] for box in cards) - ty - height * 0.025
            if limit >= height * 0.08:
                for size in sorted(
                    {s for s in scale if s <= current_title_size}, reverse=True
                ):
                    current_title_size = size
                    if title_height(size) <= limit:
                        break
                th = min(th, limit)
        for bx, by, bw, bh in reserved:
            if by < ty + th and by + bh > ty and bx < tx + tw and bx + bw > tx:
                ty = min(height * 0.35, max(ty, by + bh + height * 0.02))
        top = max(height * 0.26, ty + th + height * 0.035)
        bottom = height * min(1.0, safe["y"] + safe["h"])
        if content_slot and content_slot["w"] * content_slot["h"] >= 0.12:
            # Контент занимает ту же область, что и на слайде-прототипе.
            slot_top = height * content_slot["y"]
            slot_bottom = height * (content_slot["y"] + content_slot["h"])
            if slot_top >= ty + th * 0.6:
                # Берём вертикальный ритм прототипа: где у шаблона начинается и
                # заканчивается контент. Горизонталь остаётся на направляющих
                # шаблона — так левые края блоков совпадают, и аудит это видит.
                # Вертикальный ритм шаблона — но без провала под заголовком:
                # у страниц с мелкими подписями внизу верх контента уезжает
                # к середине слайда, и колода читается как полупустая.
                top = max(slot_top, ty + th + height * 0.02)
                top = min(top, ty + th + height * 0.1)
                bottom = max(top + height * 0.2, slot_bottom)
            # Шаблон отдал правую часть страницы под иллюстрацию — текст идёт
            # по ширине своего слота, а не на всю полосу: иначе он ложится
            # поверх картинки, которую клонирование сохранило.
            slot_right = width * (content_slot['x'] + content_slot['w'])
            if slot_right < right - width * 0.08 and slot_right - margin >= width * 0.32:
                right = slot_right
        if variant == "focus" or has_visual:
            # Крупный блок — одна мысль или диаграмма — не должен ложиться на
            # линии шаблона: ищем свободную полосу, если она достаточно широкая.
            top, bottom = decor_free_band(reserved, top, bottom, margin, right)
        w, h, gap = right - margin, bottom - top, width * 0.03
        elements = [
            {
                "id": "title",
                "kind": "text",
                "role": "title",
                "text": content["title"],
                "box": [tx, ty, tw, th],
                "font_size": current_title_size,
                "bold": True if title_style.get("bold") is None else title_style["bold"],
                "align": slot_align(title_style),
            }
        ]
        bullets = content["bullets"]
        visual = content["visual"]

        def text_box(identifier, items, box, elements=elements, marker=True):
            """marker=False — для карточек шаблона: маркер там уже нарисован
            фигурой, и второй «•» читается как ошибка вёрстки."""
            if items:
                elements.append(
                    {
                        "id": identifier,
                        "kind": "text",
                        "role": "body",
                        # Одинокий маркер читается как ошибка вёрстки: у одного
                        # тезиса его не рисуем.
                        "text": "\n".join(
                            ("• " + s if marker and len(items) > 1 else s)
                            for s in items
                        ),
                        "box": box,
                        "font_size": slide_body_size,
                        "bold": bool(body_style.get("bold")),
                        # Маркированный список выравнивается по левому краю, даже
                        # если в образце рамка была центрирована: иначе маркеры
                        # разъезжаются и текст читается тяжело.
                        "align": "left" if len(items) > 1 else slot_align(body_style),
                    }
                )

        if variant == "split":
            bw = (w - gap) / 2
            if has_visual:
                text_box("body", bullets, [margin, top, bw, h])
                elements.append(
                    {
                        "id": "visual",
                        "kind": visual["kind"],
                        "box": [margin + bw + gap, top, bw, h],
                        "data": visual,
                    }
                )
            elif len(bullets) >= MIN_BULLETS_FOR_COLUMNS:
                pivot = math.ceil(len(bullets) / 2)
                text_box("body_left", bullets[:pivot], [margin, top, bw, h])
                text_box("body_right", bullets[pivot:], [margin + bw + gap, top, bw, h])
            else:
                # Two thin columns holding one line each read as an empty slide and
                # the audit flags them. Few bullets stay in one full-width block.
                text_box("body", bullets, [margin, top, w, h])
        elif has_visual:
            text_h = (
                min(
                    h * 0.4,
                    sum(
                        max(1, math.ceil(len(b) / (w / (body_size * 0.55))))
                        for b in bullets
                    )
                    * body_size
                    * 1.3
                    + 12,
                )
                if bullets
                else 0
            )
            visual_h = h - text_h - (height * 0.025 if bullets else 0)
            if variant == "focus":
                elements.append(
                    {
                        "id": "visual",
                        "kind": visual["kind"],
                        "box": [margin, top, w, visual_h],
                        "data": visual,
                    }
                )
                text_box("body", bullets, [margin, bottom - text_h, w, text_h])
            else:
                text_box("body", bullets, [margin, top, w, text_h])
                elements.append(
                    {
                        "id": "visual",
                        "kind": visual["kind"],
                        "box": [margin, bottom - visual_h, w, visual_h],
                        "data": visual,
                    }
                )
        elif variant == "focus" and bullets:
            # Акцентный блок встаёт на ту же вертикаль, что и заголовок: свой
            # отступ здесь читался бы как съехавшая вёрстка, и аудит был прав,
            # когда его находил. Разница варианта — в кегле и в одной мысли на
            # слайде, а не в самодельных полях.
            lead_x, lead_w = tx, min(tw, w)
            if len(bullets) == 1:
                # Одна мысль занимает всю площадь: тогда кегль есть куда растить.
                text_box("lead", bullets, [lead_x, top, lead_w, h])
            else:
                text_box("lead", bullets[:1], [lead_x, top, lead_w, h * 0.3])
                text_box(
                    "body",
                    bullets[1:],
                    [lead_x, top + h * 0.36, lead_w, h * 0.64],
                )
        elif cards and len(bullets) >= 2:
            # Тезисы расходятся по карточкам шаблона: по одному на карточку,
            # остаток дописывается в последнюю, чтобы ничего не потерять.
            groups = [[b] for b in bullets[: len(cards)]]
            for extra in bullets[len(cards) :]:
                groups[-1].append(extra)
            for index, (group, box) in enumerate(zip(groups, cards)):
                # Отступ внутри карточки: текст не липнет к её рамке.
                pad = min(12.0, box[2] * 0.08, box[3] * 0.12)
                text_box(
                    f"card_{index}",
                    group,
                    [box[0] + pad, box[1] + pad, box[2] - pad * 2, box[3] - pad * 2],
                    marker=False,
                )
                elements[-1]["from_template"] = True
        else:
            text_box("body", bullets, [margin, top, w, h])
        # Resolve the text color once, against this slide's real background, so
        # layout, export and the contrast audit all agree on what will be rendered.
        # Подогнать текст до аудита: пользователь не должен чинить руками то,
        # что вёрстка умеет посчитать сама.
        for element in elements:
            if element["kind"] == "text":
                fit_text(element, scale)
        # Сначала кегль, потом положение: центрирование ужимает рамки по факту
        # текста, и расти после него уже некуда.
        grow_text(
            elements,
            scale,
            width * height,
            target=0.4 if variant == "focus" else 0.3,
            maximum=(
                max(slide_body_size, body_size) * 2.0
                if variant == "focus"
                else max(slide_body_size, body_size) * 1.25
            ),
        )
        center_content(elements, top, bottom)
        dodge_decor(elements, reserved, bottom, height * 0.015)
        background = pattern.get("background") or tokens["theme"].get("lt1", "FFFFFF")
        luma = pattern.get("bg_luma")
        if luma is not None:  # noqa: SIM108 - читаемее развёрнуто
            # Измеренная светлота важнее XML: фон может прийти от мастера или от
            # полноэкранной фигуры, и тогда объявленный цвет ничего не значит.
            background = "FFFFFF" if luma >= 0.5 else "111111"
        # Пёстрый фон — фотография или градиент: точечный цвет неизвестен, поэтому
        # под текст кладётся подложка, а контраст считается против неё.
        # Подложка нужна там, где текст иначе не прочесть: тёмный или пёстрый
        # фон. На светлой фирменной странице с декором она только портит вид.
        spread = pattern.get("bg_spread")
        if spread is None:
            needs_scrim = pattern.get("background_kind", "solid") != "solid"
        else:
            dark = (luma if luma is not None else 1.0) < 0.62
            needs_scrim = spread > BUSY_BACKGROUND and dark
        if needs_scrim and luma is None:
            # Фон не измерен: о его светлоте ничего не известно, поэтому под
            # текст кладётся светлая подложка — самый безопасный вариант.
            background = tokens["theme"].get("lt1", "FFFFFF")
        text_color = best_text_color(background, palette)
        slide_font = title_style.get("font") or body_style.get("font") or font
        for element in elements:
            element.update(font=slide_font, color=text_color, accent=accent)
            element.setdefault("bold", element.get("role") == "title")
            element.setdefault("align", "left")
        slides.append(
            {
                "background": background,
                "bg_luma": pattern.get("bg_luma"),
                "index": i,
                "pattern_index": pattern["index"],
                "image_cover": pattern.get("image_cover", 0.0),
                "background_kind": pattern.get("background_kind", "solid"),
                "needs_scrim": needs_scrim,
                # Kept so the UI and the pitch can answer "why this layout?".
                "pattern_choice": {
                    "score": pattern_score,
                    "decoration_area": pattern.get("decoration_area", 0.0),
                    "free_area": round(free_area(pattern), 5),
                    "branding_in_band": branding_in_band(pattern),
                    "text_slots": pattern.get("text_slots", 0),
                },
                "layout_index": pattern["layout_index"],
                "content": copy.deepcopy(content),
                "elements": elements,
            }
        )
    return {"width": width, "height": height, "variant": variant, "slides": slides}
