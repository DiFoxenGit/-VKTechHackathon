"""Shared geometry model for editing, audit and native export. Units: points."""

import copy
import math
import re

from .assets import asset_ref, library, pick_icons, pick_picture
from .fonts import printable, printable_visual
from .parsing import best_text_color, stage_clutter

DEFAULT_SAFE_AREA = {"x": 0.055, "y": 0.055, "w": 0.89, "h": 0.825}
DEFAULT_MARGINS = {"x": 0.04, "y": 0.04, "w": 0.92, "h": 0.9}
# Below this a two-column split leaves both columns nearly empty.
MIN_BULLETS_FOR_COLUMNS = 4
# Разброс светлоты, после которого фон считается пёстрым: по нему текст не читается.
BUSY_BACKGROUND = 0.12
# Меньше этой доли рабочей области диаграмма перестаёт читаться: ось сливается,
# короткий столбец пропадает. Приложение 1 ТЗ требует читаемых подписей осей.
MIN_VISUAL_SHARE = 0.35
# Минимальная рабочая полоса на слайде с визуализацией, долей высоты слайда.
MIN_VISUAL_BAND = 0.42
# Ширина текстовой колонки рядом с диаграммой, когда вместе по высоте не влезают.
SIDE_COLUMN_SHARE = 0.4
# Доля рабочей области под акцентный блок варианта focus: от трети до половины,
# по объёму его текста. Ниже нижней границы акценту негде вырасти, выше верхней
# остальным тезисам не остаётся места.
LEAD_SHARE_RANGE = (0.34, 0.52)
LEAD_SHARE_BONUS = 0.12
# Ниже этого кегля текст на слайде не читается: тот же ориентир, что у подписей
# схем и у проверки text_too_small.
MIN_BODY_SIZE = 10.0
# Запасная типографическая лестница для шаблонов, которые не объявляют кегли.
# Ширина знака в долях кегля для самого длинного слова — как у аудита
# (visuals.CHAR_WIDTH): оценка щедрая, иначе слово всё-таки рвётся.
WORD_CHAR_WIDTH = 0.78
DEFAULT_SCALE = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 28.0, 32.0, 40.0, 48.0]


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
            # Рост не должен рвать слово: та же мера, что у проверки word_break.
            longest = max((len(word) for word in element["text"].split()), default=1)
            fits_word = longest * larger[0] * WORD_CHAR_WIDTH <= element["box"][2] - 12
            if fits_word and estimated_text_height(candidate) <= element["box"][3]:
                element["font_size"] = larger[0]
                grew = True
        if not grew:
            break
    return elements


def focus_accent(elements, scale):
    """Вариант focus: акцент — один блок, остальные тезисы равны между собой.

    Кегль растился поэлементно, и у блока с большей рамкой он выходил крупнее.
    На слайде получалось наоборот задуманному: акцент мельче обычных тезисов, а
    следующий буллет набран почти как заголовок. Здесь порядок восстанавливается
    и не зависит от того, какие слоты нашлись у прототипа.
    """
    lead = next((e for e in elements if e["id"] == "lead"), None)
    body = [
        e
        for e in elements
        if e["kind"] == "text" and e.get("role") == "body" and e is not lead
    ]
    if body:
        # Одинаковый кегль у всех тезисов: берём наименьший из подобранных, он
        # заведомо помещается в свою рамку.
        size = min(e["font_size"] for e in body)
        for element in body:
            element["font_size"] = size
    if not lead or not body:
        return elements
    floor = max(e["font_size"] for e in body)
    for size in sorted(s for s in scale if s >= floor):
        candidate = dict(lead, font_size=size)
        if estimated_text_height(candidate) > lead["box"][3]:
            break
        lead["font_size"] = size
    # Акцент не может быть мельче обычного тезиса, даже если рамка тесная:
    # тогда рамка и растёт — иначе слайд читается задом наперёд.
    if lead["font_size"] < floor:
        lead["font_size"] = floor
        lead["box"][3] = max(lead["box"][3], estimated_text_height(lead))
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


# ---------------------------------------------------------------- фактоиды

NUMBER_TEXT = r"\d+(?:[.,]\d+)?(?:[\s ]\d{3})*"
# Единица после числа и как её показать крупно: «4 минут» → «4 мин».
UNITS = [
    (r"%", "%"),
    (r"мин(?:ут[аы]?|\.)?", "мин"),
    (r"час(?:ов|а)?|ч\.?", "ч"),
    (r"дн(?:ей|я)|день", None),
    (r"недел(?:ь|и|ю|я)", "нед."),
    (r"месяц(?:ев|а)?|мес\.?", "мес."),
    (r"руб(?:л(?:ей|я|ь))?\.?|₽", "₽"),
    (r"млрд|млн|тыс\.?", None),
    (r"[гтм]б", None),
    (r"v?cpu", "vCPU"),
    (r"раз(?:а)?", "×"),
]
UNIT = "(?:" + "|".join(pattern for pattern, _ in UNITS) + r")(?![а-яa-z])"
STAT_PATTERNS = [
    # «с 186 до 4 минут» — главное новое значение.
    re.compile(rf"\bс\s+{NUMBER_TEXT}\s*(?:{UNIT})?\s+до\s+(?P<v>{NUMBER_TEXT})\s*(?P<u>{UNIT})?", re.I),
    # «4 минуты вместо 186», «38 запросов вместо 11».
    re.compile(rf"(?P<v>{NUMBER_TEXT})\s*(?P<u>{UNIT})?(?:\s+[а-яё]+)?\s+вместо\s+{NUMBER_TEXT}", re.I),
    # «2 из 68» — доля читается только целиком.
    re.compile(rf"(?P<v>{NUMBER_TEXT}\s+из\s+{NUMBER_TEXT})", re.I),
    re.compile(rf"(?P<v>{NUMBER_TEXT})\s*(?P<u>{UNIT})", re.I),
    re.compile(r"(?<![\w.,])(?P<v>\d{2,}(?:[.,]\d+)?(?:[\s ]\d{3})*)(?![\w.,])"),
]
# Больше — и фактоид превращается в абзац, а крупная цифра теряется.
MAX_STAT_CAPTION = 110
STAT_BAR = 4.0
STAT_INSET = 14.0


def unit_label(unit):
    if not unit:
        return ""
    lowered = unit.lower()
    for pattern, label in UNITS:
        if re.fullmatch(pattern, lowered, re.I):
            return label if label is not None else (unit.upper() if len(unit) == 2 else unit)
    return unit


def stat_value(text):
    """Число, которое тезис несёт крупно: «4 мин», «2 из 68», «23%».

    Число берётся из текста дословно — фактоид не может сообщить больше, чем
    тезис. Если в тезисе нет весомого числа, фактоида нет.
    """
    for pattern in STAT_PATTERNS:
        found = pattern.search(text)
        if not found:
            continue
        value = " ".join(found.group("v").split()).replace(" ", " ")
        unit = unit_label(found.groupdict().get("u") or "")
        if unit in ("%",):
            return value + unit
        if unit == "×":
            return value + "×"
        return f"{value} {unit}" if unit else value
    return None


def stat_plan(bullets):
    """Годится ли слайд под фактоиды: две-четыре цифры и не больше одной фразы без них."""
    values = [stat_value(b) for b in bullets]
    count = sum(v is not None for v in values)
    if not 2 <= count <= 4 or len(bullets) - count > 1 or len(bullets) > 5:
        return None
    if any(v and len(b) > MAX_STAT_CAPTION for v, b in zip(values, bullets)):
        return None
    return values


def slide_mode(content, variant, position, total, assets, used):
    """Как подать слайд с тезисами без визуализации: фактоиды, иконки, картинка.

    Выбор объясним: цифры в тезисах → крупные фактоиды; перечень, к которому
    нашлись иконки по смыслу → список с иконками (classic); немного текста и
    подходящая иллюстрация → текст рядом с картинкой (split, focus). Обложку и
    финал не трогаем: там композицию задаёт страница шаблона.
    """
    bullets = content["bullets"]
    if (
        content["visual"]["kind"] != "none"
        or not bullets
        or position == 0
        or (total > 2 and position == total - 1)
    ):
        return None
    values = stat_plan(bullets)
    if values:
        return {"kind": "stats", "values": values}
    text = " ".join(bullets)
    if variant == "classic" and 2 <= len(bullets) <= 5:
        icons, matched = pick_icons(bullets, assets, used["icons"])
        if icons[0] is not None and matched >= math.ceil(len(bullets) / 2):
            return {"kind": "icons", "icons": icons}
    limit = {"split": 4, "focus": 2, "classic": 1}[variant]
    if len(bullets) <= limit and sum(len(b) for b in bullets) <= 320:
        picture = pick_picture(text, assets, used=used["pictures"], title=content["title"])
        if picture:
            return {"kind": "picture", "asset": picture}
    return None


def content_demand(content, position=1, total=1, mode=None):
    """How much room this slide needs and what kind of room."""
    bullets = content["bullets"]
    return {
        "lines": sum(1 + len(b) // 60 for b in bullets),
        # Фактоиды и картинка требуют свободной площади так же, как диаграмма.
        "has_visual": content["visual"]["kind"] != "none"
        or bool(mode and mode["kind"] in ("stats", "picture")),
        "title_length": len(content["title"]),
        "cover": position == 0,
        "closing": total > 1 and position == total - 1,
        # Сколько карточек пригодилось бы этому слайду.
        "cards": 0 if content["visual"]["kind"] != "none" or mode else len(bullets),
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
        branded = [p for p in patterns if p.get('role') == 'content'
                   and p.get('branding_score', 0) > 0 and usable(p, 2, .3, .3)]
        extra = [p for p in [*special, *branded] if p["index"] not in {f["index"] for f in found}]
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
    # Visible logos, footers and a corporate background survive export. At the
    # same capacity they should beat a white specimen page without identity.
    score += 0.3 * pattern.get('branding_score', 0)
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
        if demand['lines']:
            score += .35 if any(s['role'] == 'body' for s in pattern.get('slots', [])) else -.2
    if recent and pattern["index"] == recent[-1]:
        score -= 0.6
    # Reuse is allowed, but every repeat costs more, so a deck spreads over the
    # patterns the template actually offers.
    score -= 0.22 * uses
    return round(score, 6)


def choose_pattern(candidates, content, recent, usage=None, position=1, total=1, mode=None):
    demand = content_demand(content, position, total, mode)
    usage = usage or {}
    wanted = 'cover' if demand['cover'] else 'closing' if demand['closing'] else None
    designed = [p for p in candidates if p.get('role') == wanted] if wanted else []
    if designed:
        candidates = designed
    elif not demand['cover']:
        reusable = [p for p in candidates if p.get('role') not in ('cover', 'closing')]
        candidates = reusable or candidates
    scored = [
        (score_pattern(p, demand, recent, usage.get(p["index"], 0)), -p["index"], p)
        for p in candidates
    ]
    # Deterministic: equal scores resolve by the lowest pattern index.
    best = max(scored, key=lambda item: (item[0], item[1]))
    return best[2], best[0]


def special_page_region(reserved, left, top, right, bottom, width, height):
    """Largest usable rectangle around cover/closing artwork and logos.

    These pages must be used even with dense content. Their low title and QR
    blocks cannot be treated as a full-width content-page layout.
    """
    blockers = [b for b in reserved if b[0] < right and b[0] + b[2] > left
                and b[1] < bottom and b[1] + b[3] > top]
    xs = sorted({left, right, *(max(left, b[0] - width * .01) for b in blockers),
                 *(min(right, b[0] + b[2] + width * .01) for b in blockers)})
    candidates = []
    for x in xs:
        for r in xs:
            if r - x < width * .3:
                continue
            bands = sorted((max(top, by - height * .01), min(bottom, by + bh + height * .01))
                           for bx, by, bw, bh in blockers if bx < r and bx + bw > x)
            cursor = top
            for start, end in [*bands, (bottom, bottom)]:
                if start - cursor >= height * .3:
                    candidates.append((x, cursor, r, start))
                cursor = max(cursor, end)
    return max(candidates, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]),
               default=(left, top, right, bottom))


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
    # Шкала шаблона — кластеры близких кеглей, и объявленные 24 pt могут жить в
    # ней как 24.38. Прижимаем к ближайшей ступени: иначе вёрстка встаёт между
    # ступенями и её же аудит сообщает font_size_off_scale.
    return min(scale, key=lambda s: abs(s - size)) if scale else size


def card_depth(box, cards, reserved, bottom, gap=8.0):
    """Высота текстовой рамки карточки с учётом места под ней.

    Рамка текста в карточке шаблона обычно рассчитана на подпись в две строки,
    а сама карточка — фигура или просто колонка — тянется ниже. PowerPoint
    растит такую рамку вниз по мере набора; мы делаем то же заранее, но не
    дальше следующей карточки в колонке, не дальше фигуры, внутри которой лежит
    рамка, и не за рабочую область. Тогда кеглю есть куда расти, и три коротких
    тезиса не остаются мелкой строкой посреди пустого слайда.
    """
    x, y, w, h = box
    limit = bottom
    for other in cards:
        if other is box or other[1] <= y + 1:
            continue
        if other[0] < x + w and other[0] + other[2] > x:
            limit = min(limit, other[1] - gap)
    for bx, by, bw, bh in reserved:
        overlaps = bx < x + w and bx + bw > x
        if not overlaps:
            continue
        if by >= y + h - 1:
            # Значок или линия ниже рамки — дальше неё не идём.
            limit = min(limit, by - gap)
        elif by <= y + 1 and by + bh >= y + h - 1 and bx <= x + 1 and bx + bw >= x + w - 1:
            # Фигура-подложка карточки: текст остаётся внутри неё.
            limit = min(limit, by + bh)
    return max(h, limit - y)


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


def stat_elements(values, bullets, variant, area, scale, body_size, height):
    """Фактоиды: крупное число из тезиса и сам тезис подписью под ним.

    classic — ряд плиток, split — сетка в две колонки, focus — одна цифра
    героем во всю ширину, остальные тезисы текстом ниже. Кегли — ступени шкалы
    шаблона: крупная цифра — верхние ступени, подпись — кегль тела слайда.
    """
    left, top, w, h = area
    gap = w * 0.04
    steps = sorted(scale)
    elements = []
    plain = [b for v, b in zip(values, bullets) if v is None]
    stats = [(v, b) for v, b in zip(values, bullets) if v is not None]
    rest = []
    if variant == "focus":
        rest = [b for _, b in stats[1:]] + plain
        stats, plain = stats[:1], []
    if plain:
        note = {
            "id": "body",
            "kind": "text",
            "role": "body",
            "text": plain[0],
            "box": [left, top, w, h],
            "font_size": body_size,
            "bold": False,
            "align": "left",
        }
        note["box"][3] = min(h * 0.3, estimated_text_height(note))
        elements.append(note)
        top += note["box"][3] + height * 0.03
        h -= note["box"][3] + height * 0.03
    rest_h = 0.0
    if rest:
        rest_h = h * 0.42
        h -= rest_h + height * 0.03
    columns = {"classic": len(stats), "split": 2 if len(stats) > 1 else 1, "focus": 1}[variant]
    rows = math.ceil(len(stats) / columns)
    tile_w = (w - gap * (columns - 1)) / columns
    row_gap = height * 0.04
    row_h = (h - row_gap * (rows - 1)) / rows
    text_w = tile_w - STAT_INSET
    ceiling = height * (0.2 if variant == "focus" else 0.13)
    longest = max(len(v) for v, _ in stats)
    # Цифры уже букв: 0.56 кегля на знак, иначе крупная цифра зря мельчает.
    fitting = [s for s in steps if s <= ceiling and longest * s * 0.56 <= text_w - 12]
    value_size = fitting[-1] if fitting else steps[0]
    value_h = value_size * 1.25
    caption_size = body_size
    for size in sorted((s for s in steps if MIN_BODY_SIZE <= s <= body_size), reverse=True):
        caption_size = size
        needed = max(
            estimated_text_height({"box": [0, 0, text_w, 0], "font_size": size, "text": b})
            for _, b in stats
        )
        if value_h + needed <= row_h:
            break
    for index, (value, bullet) in enumerate(stats):
        row, column = divmod(index, columns)
        caption_h = estimated_text_height(
            {"box": [0, 0, text_w, 0], "font_size": caption_size, "text": bullet}
        )
        elements.append(
            {
                "id": f"stat_{index}",
                "kind": "stat",
                "role": "body",
                "value": value,
                "text": bullet,
                "box": [
                    left + column * (tile_w + gap),
                    top + row * (row_h + row_gap),
                    tile_w,
                    min(row_h, value_h + caption_h),
                ],
                "value_size": value_size,
                "font_size": caption_size,
                # Плитки встают равномерной сеткой от левого края области: их
                # выравнивание — шаг сетки, а не направляющие шаблона.
                "grid": column > 0,
                "bold": False,
                "align": "left",
            }
        )
    if rest:
        elements.append(
            {
                "id": "body",
                "kind": "text",
                "role": "body",
                "text": "\n".join(("• " + b if len(rest) > 1 else b) for b in rest),
                "box": [left, top + h + height * 0.03, w, rest_h],
                "font_size": body_size,
                "bold": False,
                "align": "left",
            }
        )
    return elements


def icon_rows(bullets, icons, area, body_size, height):
    """Список с иконками: значок слева от каждого тезиса, тезисы на одной вертикали."""
    left, top, w, h = area
    count = len(bullets)
    size = max(26.0, min(body_size * 2.4, height * 0.085, h / count * 0.8))
    gap = size * 0.45
    row = h / count
    elements = []
    for index, (bullet, icon) in enumerate(zip(bullets, icons)):
        y = top + index * row
        elements.append(
            {
                "id": f"icon_{index}",
                "kind": "image",
                "role": "icon",
                "box": [left, y, size, size],
                "asset": asset_ref(icon),
                "fit": "contain",
            }
        )
        elements.append(
            {
                "id": f"item_{index}",
                "kind": "text",
                "role": "body",
                "text": bullet,
                "box": [left + size + gap, y, w - size - gap, max(size, row - height * 0.02)],
                "font_size": body_size,
                "bold": False,
                "align": "left",
            }
        )
    return elements


def align_icons(elements):
    """Значок встаёт по центру своего тезиса, после того как тезис нашёл место.

    Центрирование и обход декора двигают текст; значок, оставшийся на старом
    месте, читается как съехавшая вёрстка.
    """
    for element in elements:
        if not element["id"].startswith("icon_"):
            continue
        text = next((e for e in elements if e["id"] == "item_" + element["id"][5:]), None)
        if not text:
            continue
        size = element["box"][3]
        used = min(text["box"][3], estimated_text_height(text))
        if used >= size:
            element["box"][1] = text["box"][1] + (used - size) / 2
        else:
            element["box"][1] = text["box"][1]
            text["box"][1] += (size - used) / 2
            text["box"][3] = max(used, text["box"][3] - (size - used) / 2)
    return elements


def swap_icons(elements, slots, assets, used, width, height):
    """Иконки образца над карточками — заменить на подходящие по смыслу.

    Место и цвет значка задал дизайнер, поэтому новая иконка встаёт ровно в
    рамку образца и красится в его цвет. Значок над карточкой ищется по
    горизонтали: его центр лежит над карточкой, выше неё или в её верхней части.
    """
    cards = [e for e in elements if e["id"].startswith("card_")]
    pairs, taken = [], set()
    for card in cards:
        x, y, w, h = card["box"]
        best = None
        for slot in slots:
            if slot["id"] in taken:
                continue
            bx, by = slot["box"]["x"] * width, slot["box"]["y"] * height
            bw, bh = slot["box"]["w"] * width, slot["box"]["h"] * height
            cx, cy = bx + bw / 2, by + bh / 2
            if not (x - w * 0.1 <= cx <= x + w * 1.1):
                continue
            if not (y - height * 0.3 <= cy <= y + h * 0.5):
                continue
            # Значок, лежащий под текстом карточки, заменять нельзя: новая
            # иконка наедет на тезис.
            if bx < x + w and bx + bw > x and by < y + h and by + bh > y:
                continue
            distance = abs(cx - (x + w / 2)) + abs(cy - y)
            if best is None or distance < best[0]:
                best = (distance, slot, [bx, by, bw, bh])
        if best:
            taken.add(best[1]["id"])
            pairs.append((card, best[1], best[2]))
    if not pairs:
        return elements
    icons, _ = pick_icons([card["text"] for card, _, _ in pairs], assets, used["icons"])
    for index, ((card, slot, box), icon) in enumerate(zip(pairs, icons)):
        if icon is None:
            continue
        used["icons"].add(icon["id"])
        elements.append(
            {
                "id": f"swap_{index}",
                "kind": "image",
                "role": "icon",
                "box": box,
                "asset": asset_ref(icon),
                "fit": "contain",
                "tint": slot["color"],
                "from_template": True,
            }
        )
    return elements


def align_to_picture(elements):
    """Текст рядом с картинкой — по её вертикальному центру, а не прибитым к верху."""
    picture = next((e for e in elements if e["id"] == "picture"), None)
    texts = [e for e in elements if e["kind"] == "text" and e.get("role") != "title"]
    if not picture or not texts:
        return elements
    top = min(e["box"][1] for e in texts)
    bottom = max(e["box"][1] + min(e["box"][3], estimated_text_height(e)) for e in texts)
    shift = picture["box"][1] + picture["box"][3] / 2 - (top + bottom) / 2
    # Двигаем только вниз: вверху текст упирается в заголовок.
    if shift > 0:
        for element in texts:
            element["box"][3] = min(element["box"][3], estimated_text_height(element))
            element["box"][1] += shift
    return elements


def picture_box(asset, box):
    """Рамка картинки по её пропорциям: по вертикали по центру, по правому краю.

    Правый край области — направляющая шаблона; картинка, повисшая между
    колонками, читается как невыровненная.
    """
    x, y, w, h = box
    ratio = asset.get("ratio") or 1.0
    if w / h > ratio:
        cw, ch = h * ratio, h
    else:
        cw, ch = w, w / ratio
    return [x + w - cw, y + (h - ch) / 2, cw, ch]


def compose(outline, template, variant, assets=None):
    """assets — библиотека картинок колоды (шаблон, пакеты, встроенный набор)."""
    if assets is None:
        assets = library(template)
    used = {"icons": set(), "pictures": set()}
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
    # Шаблон может не объявлять кегли вовсе (весь текст наследует их от темы).
    # Тогда шагать некуда: ни уменьшить блок, ни вырастить. Запасная лестница
    # нужна именно для таких файлов.
    scale = [s for s in tokens["font_sizes"] if 10 <= s <= 60] or DEFAULT_SCALE
    title_size = min(scale, key=lambda s: abs(s - height * 0.075)) if scale else 28
    body_size = min(scale, key=lambda s: abs(s - height * 0.045)) if scale else 18
    # Акцент берём из фактических цветов шаблона: офисная тема по умолчанию
    # покрасила бы диаграммы чужим синим.
    coverage = tokens.get("font_coverage") or {}
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
        mode = slide_mode(content, variant, i, len(outline["slides"]), assets, used)
        pattern, pattern_score = choose_pattern(
            candidates, content, recent, usage, i, len(outline["slides"]), mode
        )
        if mode and mode["kind"] == "icons":
            # Карточная страница с местом под значок над каждой карточкой — это
            # тот же список с иконками, только нарисованный дизайнером. Берём её.
            body = [s for s in pattern.get("slots") or [] if s["role"] == "body"]
            grid = card_slots(body, width, height)
            size = slot_size((body[0] if body else {}).get("style") or {}, scale, 14.0)
            roomy = all(
                estimated_text_height({"box": box, "font_size": size, "text": bullet}) <= box[3]
                and max(len(word) for word in bullet.split()) * size * 0.78 <= box[2] - 12
                for box, bullet in zip(grid, content["bullets"])
            )
            if (
                roomy
                and len(grid) == len(content["bullets"])
                and len(pattern.get("icon_slots") or []) >= len(grid)
            ):
                mode = None
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
        # Столбцы и линии живут по своим правилам: ось и короткий столбец
        # требуют высоты, которой схемам из фигур не нужно.
        is_chart = content["visual"]["kind"] in ("bar", "line")
        # Карточки шаблона стоят на своих местах: заголовок обязан закончиться
        # выше первой из них, иначе длинный заголовок ложится прямо на карточку.
        cards = (
            card_slots(body_slots, width, height)
            if not has_visual and variant != "focus" and not mode
            else []
        )
        # Compose around branding the template keeps on every slide: narrow the
        # title away from a corner logo, and drop below a full-width wordmark.
        # Диаграмма и своя композиция (фактоиды, иконки, картинка) занимают
        # сцену целиком: стрелки и значки образца рядом с ними — мусор.
        staged = bool(mode) or content["visual"]["kind"] != "none"
        # Своя композиция (фактоиды, иконки, картинка) убирает со сцены мелкие
        # образцы страницы: экспорт их не переносит, обходить их незачем.
        branding = template.get("branding") or ()
        reserved = [
            (width * b["x"], height * b["y"], width * b["w"], height * b["h"])
            for b in pattern.get("reserved", [])
            if b["w"] * b["h"] < 0.6
            and not b.get("icons")
            and not (staged and stage_clutter(b, branding))
        ]
        special_region = None
        if pattern.get('role') in ('cover', 'closing') and (has_visual or len(content['bullets']) > 1):
            special_region = special_page_region(
                reserved, width * safe['x'], height * safe['y'], right,
                height * min(1.0, safe['y'] + safe['h']), width, height,
            )
            margin, ty, right, _ = special_region
            tx, tw = margin, right - margin
        if not from_template_title:
            for bx, by, _, bh in reserved:
                if by < height * 0.3 and tx + tw * 0.35 < bx < tx + tw:
                    tw = max(width * 0.3, bx - width * 0.012 - tx)
        # Кегль заголовка — шаблонный, если он объявлен; шкала остаётся запасным
        # вариантом для файлов, где типографика не описана.
        current_title_size = slot_size(title_style, scale, title_size, minimum=18)
        slide_body_size = slot_size(body_style, scale, body_size, minimum=10, maximum=40)
        if mode:
            # Своя композиция не наследует мелкий кегль подписи образца: тезис
            # рядом с картинкой или под цифрой набирается кеглем тела шаблона.
            slide_body_size = max(slide_body_size, body_size)

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
        if special_region:
            bottom = special_region[3]
        # Своей композиции нужна вся рабочая область, а не рамка текста образца.
        elif not staged and content_slot and content_slot["w"] * content_slot["h"] >= 0.12:
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
                # Нижнюю границу прототипа focus не наследует: у страницы с
                # рядом мелких подписей она отрезает полосу в пятую часть
                # слайда, и одна крупная мысль набирается кеглем подписи.
                if variant != "focus":
                    bottom = max(top + height * 0.2, slot_bottom)
            # Шаблон отдал правую часть страницы под иллюстрацию — текст идёт
            # по ширине своего слота, а не на всю полосу: иначе он ложится
            # поверх картинки, которую клонирование сохранило.
            slot_right = width * (content_slot['x'] + content_slot['w'])
            if slot_right < right - width * 0.08 and slot_right - margin >= width * 0.32:
                right = slot_right
        if variant == "focus" or has_visual or mode:
            # Крупный блок — одна мысль или диаграмма — не должен ложиться на
            # линии шаблона: ищем свободную полосу, если она достаточно широкая.
            top, bottom = decor_free_band(reserved, top, bottom, margin, right)
        if is_chart:
            # Вертикальный ритм прототипа и обход декора могут оставить под
            # диаграмму полоску в десятую слайда: ось там не читается. Рабочая
            # область возвращается к минимуму — сначала вниз, до безопасного
            # края, потом вверх, но не выше конца заголовка.
            floor = height * MIN_VISUAL_BAND
            if bottom - top < floor:
                limit = special_region[3] if special_region else height * min(1.0, safe["y"] + safe["h"])
                bottom = min(limit, top + floor)
            if bottom - top < floor:
                top = max(ty + th + height * 0.02, bottom - floor)
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

        if mode and mode["kind"] == "stats":
            elements.extend(
                stat_elements(
                    mode["values"], bullets, variant, [margin, top, w, h],
                    scale, slide_body_size, height,
                )
            )
        elif mode and mode["kind"] == "icons":
            elements.extend(
                icon_rows(bullets, mode["icons"], [margin, top, w, h], slide_body_size, height)
            )
            used["icons"].update(icon["id"] for icon in mode["icons"])
        elif mode and mode["kind"] == "picture":
            # Текст слева, картинка справа: колонка текста шире, чтобы тезисы
            # не ломались на короткие строки.
            column = (w - gap) * (0.52 if variant == "focus" else 0.56)
            if variant == "focus":
                text_box("lead", bullets[:1], [margin, top, column, h * (0.55 if len(bullets) > 1 else 1.0)])
                text_box("body", bullets[1:], [margin, top + h * 0.6, column, h * 0.4])
            else:
                text_box("body", bullets, [margin, top, column, h])
            asset = mode["asset"]
            elements.append(
                {
                    "id": "picture",
                    "kind": "image",
                    "role": "picture",
                    "box": picture_box(asset, [margin + column + gap, top, w - column - gap, h])
                    if asset["kind"] != "photo"
                    else [margin + column + gap, top, w - column - gap, h],
                    "asset": asset_ref(asset),
                    "fit": "cover" if asset["kind"] == "photo" else "contain",
                }
            )
            used["pictures"].add(asset["id"])
        elif variant == "split" and (not special_region or w >= width * 0.7):
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
            needed_h = (
                sum(
                    max(1, math.ceil(len(b) / (w / (body_size * 0.55))))
                    for b in bullets
                )
                * body_size
                * 1.3
                + 12
                if bullets
                else 0
            )
            text_h = min(h * 0.4, needed_h)
            visual_h = h - text_h - (height * 0.025 if bullets else 0)
            # Тезисы, которым нужно больше отведённой полосы, сейчас просто
            # уменьшаются в кегле: диаграмма остаётся целой, зато текст под ней
            # набран мельче шкалы. Такой слайд лучше собрать в две колонки.
            if is_chart and bullets and needed_h > h * (1 - MIN_VISUAL_SHARE):
                # Диаграмма не ужимается под текст: сжатая до полоски, она не
                # читается вовсе. Тезисы уходят в колонку слева — так у обоих
                # блоков остаётся полная высота рабочей области.
                column = (w - gap) * SIDE_COLUMN_SHARE
                text_box("body", bullets, [margin, top, column, h])
                elements.append(
                    {
                        "id": "visual",
                        "kind": visual["kind"],
                        "box": [margin + column + gap, top, w - column - gap, h],
                        "data": visual,
                    }
                )
            elif variant == "focus":
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
                # Акценту нужна своя площадь: в фиксированной трети слайда он не
                # мог вырасти и выходил мельче обычных тезисов под ним. Долю
                # считаем по объёму текста, чтобы длинный акцент не жался.
                lead_len = len(bullets[0])
                rest = sum(len(b) for b in bullets[1:])
                share = min(
                    LEAD_SHARE_RANGE[1],
                    max(
                        LEAD_SHARE_RANGE[0],
                        lead_len / max(1, lead_len + rest) + LEAD_SHARE_BONUS,
                    ),
                )
                lead_h = h * share
                text_box("lead", bullets[:1], [lead_x, top, lead_w, lead_h])
                text_box(
                    "body",
                    bullets[1:],
                    [
                        lead_x,
                        top + lead_h + h * 0.06,
                        lead_w,
                        h - lead_h - h * 0.06,
                    ],
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
                    [
                        box[0] + pad,
                        box[1] + pad,
                        box[2] - pad * 2,
                        card_depth(box, cards, reserved, bottom) - pad * 2,
                    ],
                    marker=False,
                )
                elements[-1]["from_template"] = True
        else:
            text_box("body", bullets, [margin, top, w, h])
        # A sparse opening slide follows the cover's own title/subtitle frames,
        # including titles below the middle of the page. Content geometry must
        # not lift it into the logo band or stretch it across the brand artwork.
        if i == 0 and pattern.get('role') == 'cover' and not has_visual and len(bullets) <= 1:
            cover_box = pattern.get('title_box')
            if cover_box:
                cx = max(width * margins['x'], width * cover_box['x'])
                cy = height * cover_box['y']
                cw = min(width * cover_box['w'], width * (1 - margins['x']) - cx)
                ch = min(height * cover_box['h'], height * .9 - cy)
                elements[0]['box'] = [cx, cy, cw, ch]
                elements[0]['from_template'] = True
                # Кегль обложки — тот, что задал дизайнер в рамке заголовка
                # титульной страницы (обычно 48–60 pt), а не кегль заголовка
                # обычного слайда, подобранный под ширину полосы. Рамка растёт
                # вниз, как у заголовка с автоподбором в PowerPoint, но
                # оставляет место подзаголовку; не влезло — ступень шкалы ниже.
                cover_bottom = height * min(.95, margins['y'] + margins['h'])
                room = cover_bottom - cy - (height * .12 if bullets else 0)
                cover_size = slot_size(title_style, scale, current_title_size, minimum=18)
                title = elements[0]
                for size in sorted({s for s in scale if s <= cover_size} | {cover_size}, reverse=True):
                    if size <= title['font_size']:
                        break
                    candidate = dict(title, font_size=size)
                    longest = max((len(word) for word in title['text'].split()), default=1)
                    if (estimated_text_height(candidate) <= max(ch, room)
                            and longest * size * WORD_CHAR_WIDTH <= cw - 12):
                        title['font_size'] = size
                        title['box'][3] = max(ch, estimated_text_height(candidate))
                        break
                ch = title['box'][3]
                if bullets:
                    below = [s for s in body_slots if s['box']['y'] >= cover_box['y'] + cover_box['h'] * .8]
                    subtitle = min(below, key=lambda s: s['box']['y'])['box'] if below else None
                    by = max(cy + ch + height * .02, height * subtitle['y'] if subtitle else 0)
                    body = next(e for e in elements if e['id'] != 'title')
                    body['box'] = [cx, by, cw, max(10, cover_bottom - by)]
                    body['from_template'] = True
        slots = pattern.get("icon_slots") or []
        if slots:
            swap_icons(elements, slots, assets, used, width, height)
        for element in elements:
            if element["kind"] == "icon":
                # Пиктограммы схемы — из того же набора, что и списки с иконками.
                icons, _ = pick_icons(element["data"]["steps"], assets, used["icons"])
                if icons[0] is not None:
                    element["icons"] = [asset_ref(icon) for icon in icons]
                    used["icons"].update(icon["id"] for icon in icons)
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
            target=0.4 if variant == "focus" or mode else 0.3,
            maximum=(
                max(slide_body_size, body_size) * 2.0
                if variant == "focus"
                else max(slide_body_size, body_size) * 1.25
            ),
        )
        # Карточки одного ряда читаются как равные: кегль у всех один, по
        # самой тесной. Иначе рост кегля по рамкам даёт 18, 24 и 18 рядом.
        cards_text = [e for e in elements if e["id"].startswith("card_")]
        if cards_text:
            size = min(e["font_size"] for e in cards_text)
            for element in cards_text:
                element["font_size"] = size
        if variant == "focus":
            focus_accent(elements, scale)
        if i == 0 and pattern.get('role') == 'cover' and not has_visual and len(bullets) <= 1:
            # На обложке подзаголовок подчинён заголовку: рост кегля и акцент
            # focus не должны сделать его крупнее названия колоды.
            title_size = elements[0]["font_size"]
            ceiling = max([s for s in scale if s <= title_size * 0.75] or [MIN_BODY_SIZE])
            for element in elements[1:]:
                if element["kind"] == "text" and element["font_size"] > ceiling:
                    element["font_size"] = ceiling
        center_content(elements, top, bottom)
        dodge_decor(elements, reserved, bottom, height * 0.015)
        align_icons(elements)
        align_to_picture(elements)
        # Последнее слово за вместимостью рамки: рост кегля и центрирование
        # двигают и рамки, и текст, поэтому блок, который после них перестал
        # помещаться, уменьшается до следующей ступени шкалы, а не выходит за
        # карточку шаблона.
        for element in elements:
            if element["kind"] != "text":
                continue
            fit_text(element, scale, minimum=MIN_BODY_SIZE)
            needed = estimated_text_height(element)
            if needed <= element["box"][3] or element.get("from_template"):
                # Блок в карточке шаблона остаётся в её границах: там решает
                # дизайнер, а лишний текст ловит проверка text_overflow.
                continue
            # Мельче ступени шкалы уже нельзя. Тогда растёт рамка — вниз до
            # границы рабочей области, а если там уже край, блок поднимается:
            # центрирование сдвинуло его вниз и место осталось сверху.
            ceiling = max(
                [
                    e["box"][1] + e["box"][3]
                    for e in elements
                    if e is not element
                    and e["box"][1] + e["box"][3] <= element["box"][1] + 1
                ]
                + [top],
            )
            # Полпункта запаса: оценка высоты и сравнение в аудите идут по одной
            # формуле, и рамка «ровно по тексту» всё равно даёт text_overflow на
            # разнице последнего знака.
            needed += 0.5
            element["box"][1] = max(ceiling, min(element["box"][1], bottom - needed))
            element["box"][3] = min(needed, bottom - element["box"][1])
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
        native_cover = i == 0 and pattern.get('role') == 'cover' and not has_visual and len(bullets) <= 1
        if native_cover:
            sampled = pattern.get('title_background')
            if sampled:
                background = sampled['color']
                needs_scrim = sampled['spread'] > BUSY_BACKGROUND
            elif (pattern.get('background_kind', 'solid') == 'solid'
                  and pattern.get('image_cover', 0) < 0.5):
                background = pattern.get('background', background)
                needs_scrim = False
            else:
                # Without a reliable local sample, retain the readability panel.
                needs_scrim = True
        text_color = best_text_color(background, palette, minimum=4.5)
        for element in elements:
            role = "title" if element.get("role") == "title" else "body"
            preferred = tokens.get("font_choice", {}).get(role, {})
            style = title_style if role == "title" else body_style
            slide_font = preferred.get("selected") or style.get("font") or font
            element.update(font=slide_font, color=text_color, accent=accent)
            if element["kind"] == "text":
                # Символ, которого нет в гарнитуре, выводится пустым
                # прямоугольником: меняем его на читаемый эквивалент здесь, пока
                # известна и гарнитура слайда, и покрытие из разбора шаблона.
                element["text"] = printable(element["text"], slide_font, coverage)
            elif element.get("data"):
                # Подписи внутри диаграмм и схем — тот же текст на слайде.
                printable_visual(element["data"], slide_font, coverage)
            element.setdefault("bold", element.get("role") == "title")
            element.setdefault("align", "left")
        slides.append(
            {
                "background": background,
                "bg_luma": pattern.get("bg_luma"),
                "bg_spread": pattern.get("bg_spread"),
                "index": i,
                "pattern_index": pattern["index"],
                "image_cover": pattern.get("image_cover", 0.0),
                "background_kind": pattern.get("background_kind", "solid"),
                "needs_scrim": needs_scrim,
                "native_cover": native_cover,
                # Слайд собран своей композицией: мелкие образцы страницы сняты.
                "clear_stage": staged,
                # Значки образца страницы: на слайд они не переносятся, на их
                # местах стоят подобранные иконки (swap_*), если нашлись.
                "drop_shapes": [slot["id"] for slot in slots],
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
