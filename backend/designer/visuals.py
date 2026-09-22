"""Диаграммы и пиктограммы из нативных фигур PowerPoint.

Всё, что рисуется здесь, остаётся редактируемым объектом: фигуры шаблонных
геометрий, текст внутри них, цвета из палитры шаблона. Картинок не создаём —
ТЗ прямо не засчитывает слайд, выгруженный растром.

Координаты приходят в EMU (вызывающая сторона уже применила Pt), поэтому
геометрия считается прямо в них. Кегли и ширина слова — в пунктах: для них есть
EMU_PER_PT, и путать единицы нельзя, иначе проверка переносов всегда «проходит».
"""

import math

from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE as SHAPE
from pptx.enum.text import PP_ALIGN

# Пиктограмма — композиция из простых фигур в единичном квадрате: (фигура, x, y,
# w, h, роль). Роль solid — заливка акцентом, outline — контур, hole — фон,
# чтобы получилось «кольцо» или циферблат.
ICONS: dict[str, list[tuple]] = {
    "рост": [
        (SHAPE.RECTANGLE, 0.10, 0.62, 0.16, 0.30, "solid"),
        (SHAPE.RECTANGLE, 0.34, 0.44, 0.16, 0.48, "solid"),
        (SHAPE.RECTANGLE, 0.58, 0.22, 0.16, 0.70, "solid"),
        (SHAPE.UP_ARROW, 0.78, 0.08, 0.20, 0.42, "solid"),
    ],
    "снижение": [
        (SHAPE.RECTANGLE, 0.10, 0.22, 0.16, 0.70, "solid"),
        (SHAPE.RECTANGLE, 0.34, 0.44, 0.16, 0.48, "solid"),
        (SHAPE.RECTANGLE, 0.58, 0.62, 0.16, 0.30, "solid"),
        (SHAPE.DOWN_ARROW, 0.78, 0.50, 0.20, 0.42, "solid"),
    ],
    "время": [
        (SHAPE.OVAL, 0.08, 0.08, 0.84, 0.84, "solid"),
        (SHAPE.OVAL, 0.18, 0.18, 0.64, 0.64, "hole"),
        (SHAPE.RECTANGLE, 0.48, 0.28, 0.04, 0.24, "solid"),
        (SHAPE.RECTANGLE, 0.48, 0.48, 0.22, 0.04, "solid"),
    ],
    "команда": [
        (SHAPE.OVAL, 0.06, 0.16, 0.30, 0.30, "solid"),
        (SHAPE.OVAL, 0.35, 0.08, 0.30, 0.30, "solid"),
        (SHAPE.OVAL, 0.64, 0.16, 0.30, 0.30, "solid"),
        (SHAPE.ROUNDED_RECTANGLE, 0.04, 0.52, 0.34, 0.40, "solid"),
        (SHAPE.ROUNDED_RECTANGLE, 0.33, 0.46, 0.34, 0.46, "solid"),
        (SHAPE.ROUNDED_RECTANGLE, 0.62, 0.52, 0.34, 0.40, "solid"),
    ],
    "цель": [
        (SHAPE.OVAL, 0.04, 0.04, 0.92, 0.92, "solid"),
        (SHAPE.OVAL, 0.20, 0.20, 0.60, 0.60, "hole"),
        (SHAPE.OVAL, 0.34, 0.34, 0.32, 0.32, "solid"),
        (SHAPE.OVAL, 0.44, 0.44, 0.12, 0.12, "hole"),
    ],
    "идея": [
        (SHAPE.OVAL, 0.22, 0.04, 0.56, 0.56, "solid"),
        (SHAPE.RECTANGLE, 0.38, 0.58, 0.24, 0.18, "solid"),
        (SHAPE.RECTANGLE, 0.40, 0.80, 0.20, 0.08, "solid"),
    ],
    "документ": [
        (SHAPE.FLOWCHART_DOCUMENT, 0.12, 0.08, 0.76, 0.84, "solid"),
    ],
    "данные": [
        (SHAPE.FLOWCHART_MAGNETIC_DISK, 0.12, 0.08, 0.76, 0.84, "solid"),
    ],
    "решение": [
        (SHAPE.FLOWCHART_DECISION, 0.06, 0.10, 0.88, 0.80, "solid"),
    ],
    "процесс": [
        (SHAPE.GEAR_6, 0.04, 0.04, 0.62, 0.62, "solid"),
        (SHAPE.GEAR_6, 0.46, 0.42, 0.50, 0.50, "solid"),
    ],
    "риск": [
        (SHAPE.ISOSCELES_TRIANGLE, 0.04, 0.10, 0.92, 0.80, "solid"),
        (SHAPE.RECTANGLE, 0.46, 0.38, 0.08, 0.26, "hole"),
        (SHAPE.OVAL, 0.45, 0.70, 0.10, 0.10, "hole"),
    ],
    "качество": [
        (SHAPE.STAR_5_POINT, 0.04, 0.06, 0.92, 0.88, "solid"),
    ],
    "запуск": [
        (SHAPE.LIGHTNING_BOLT, 0.22, 0.04, 0.56, 0.92, "solid"),
    ],
    "деньги": [
        (SHAPE.OVAL, 0.06, 0.06, 0.88, 0.88, "solid"),
        (SHAPE.OVAL, 0.16, 0.16, 0.68, 0.68, "hole"),
        (SHAPE.RECTANGLE, 0.46, 0.22, 0.08, 0.56, "solid"),
        (SHAPE.RECTANGLE, 0.32, 0.34, 0.36, 0.08, "solid"),
    ],
    # Нейтральная пиктограмма для подписи, которая ни на что не похожа:
    # кольцо с засечкой читается как значок, а не как забытая заливка.
    "пункт": [
        (SHAPE.OVAL, 0.06, 0.06, 0.88, 0.88, "solid"),
        (SHAPE.OVAL, 0.20, 0.20, 0.60, 0.60, "hole"),
        (SHAPE.OVAL, 0.36, 0.36, 0.28, 0.28, "solid"),
    ],
}

# Слова, по которым подпись превращается в пиктограмму. Первое совпадение выигрывает,
# поэтому длинные и более конкретные корни идут раньше общих.
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("рост", ("рост", "выросл", "увелич", "прирост", "growth", "increase")),
    ("снижение", ("сниж", "паден", "сократ", "уменьш", "decline", "reduce")),
    ("время", ("врем", "срок", "быстр", "скорост", "часов", "минут", "день", "дней", "недел", "квартал", "time")),
    ("команда", ("команд", "отдел", "сотрудник", "пользоват", "клиент", "людей", "обучен", "поддержк", "team", "user", "support")),
    ("цель", ("цел", "задач", "фокус", "результат", "план", "дорожн", "шаг", "goal", "target", "roadmap")),
    ("идея", ("иде", "гипотез", "предлож", "концепц", "idea")),
    ("документ", ("документ", "отчёт", "отчет", "отчётн", "отчетн", "презентац", "колод", "слайд", "шаблон", "макет", "материал", "файл", "экспорт", "polit", "регламент", "doc", "template", "export")),
    ("данные", ("данн", "база", "метрик", "аналит", "источник", "data")),
    ("решение", ("решени", "выбор", "вариант", "decision")),
    ("процесс", ("процесс", "автомат", "пайплайн", "конвейер", "генерац", "сборк", "вёрстк", "верстк", "интеграц", "настройк", "workflow", "process")),
    ("риск", ("риск", "проблем", "ошибк", "угроз", "ограничен", "risk", "issue")),
    ("качество", ("качеств", "аудит", "провер", "контрол", "оценк", "рейтинг", "лучш", "quality")),
    ("запуск", ("запуск", "старт", "релиз", "пилот", "масштаб", "внедрен", "launch", "release")),
    ("деньги", ("деньг", "бюджет", "стоим", "выручк", "экономи", "руб", "cost", "budget")),
]


def pick_icon(label: str) -> str:
    """Пиктограмма по смыслу подписи; без совпадения — нейтральный знак.

    Раньше запасным вариантом был закрашенный круг: на рендере он читался как
    пустая синяя заливка, «забытая заготовка». Нейтральная пиктограмма — тоже
    рисунок, поэтому ряд значков выглядит рядом значков при любой подписи.
    """
    text = label.lower()
    for name, roots in KEYWORDS:
        if any(root in text for root in roots):
            return name
    return "пункт"


def _style(shape, role, accent, background, palette, contrast):
    shape.line.fill.background()
    shape.fill.solid()
    if role == "hole":
        shape.fill.fore_color.rgb = background
    elif role == "outline":
        shape.fill.background()
        shape.line.fill.solid()
        shape.line.fill.fore_color.rgb = accent
    else:
        shape.fill.fore_color.rgb = accent
    return contrast if role != "hole" else palette


MIN_LABEL_SIZE = 10.0
MAX_LABEL_SIZE = 14.0
# Доля кегля на знак. Замерено по рендеру: в Play кириллическое слово из девяти
# знаков при 10 pt занимает около 70 pt, то есть 0.78 кегля на знак. Оценка
# должна быть щедрой: недооценка ширины и есть перенос посреди слова.
CHAR_WIDTH = 0.78
# Запас на кернинг и на разницу гарнитур: без него слово впритык всё-таки рвётся.
LABEL_PADDING = 2.0
# Сколько рядов значков допустимо, прежде чем схема перестанет читаться.
MAX_ICON_ROWS = 3
# Геометрия схем приходит в EMU, а кегль измеряется в пунктах.
EMU_PER_PT = 12700
# Насколько подпись вехи шире своей ячейки. Соседняя стоит по другую сторону
# линии, поэтому места полторы ячейки; запас нужен для крайних подписей, которые
# подрезаются границей области и сдвигаются внутрь.
TIMELINE_CAPTION_SPAN = 1.5


def longest_word(texts):
    """Самое длинное слово набора: именно оно решает, порвётся ли подпись."""
    return max((max((len(word) for word in t.split()), default=1) for t in texts), default=1)


def label_size(texts, width, fit=1.0):
    """Единый кегль подписей одной схемы.

    Раньше кегль считался для каждой фигуры отдельно, и в одном ряду шевронов
    «Аудит» оказывался крупнее соседей, а нижней границей было 6 pt. Теперь
    решает самое длинное слово всей схемы, а ниже 10 pt подпись не опускается:
    вместо этого схема получает больше места или другую раскладку.
    """
    usable = max(1.0, width * fit - LABEL_PADDING)
    return max(
        MIN_LABEL_SIZE,
        min(MAX_LABEL_SIZE, usable / (longest_word(texts) * CHAR_WIDTH)),
    )


def word_fits(texts, width, fit=1.0, size=MIN_LABEL_SIZE):
    """Помещается ли самое длинное слово целиком при этом кегле."""
    return longest_word(texts) * size * CHAR_WIDTH <= width * fit - LABEL_PADDING


def icon_row(width, count):
    """Промежуток и ячейка ряда из count значков; единицы — как у width."""
    gap = width * 0.04 / max(1, count)
    return gap, (width - gap * (count - 1)) / count


def icon_grid(steps, width_pt):
    """Сколько рядов значков нужно, чтобы подписи не рвались посреди слова.

    Ширина — в пунктах: сравнивать её приходится с кеглем.
    """
    for rows in range(1, min(MAX_ICON_ROWS, len(steps)) + 1):
        per_row = math.ceil(len(steps) / rows)
        if word_fits(steps, icon_row(width_pt, per_row)[1]):
            return rows, per_row
    return MAX_ICON_ROWS, math.ceil(len(steps) / MAX_ICON_ROWS)


def draw_icons(shapes, box, data, style):
    """Ряды пиктограмм с подписями под ними.

    Если подписи не помещаются в ряд целыми словами, значков в ряду становится
    меньше, а рядов — больше: шрифт мельче 10 pt не опускается.
    """
    x, y, w, h = box
    steps = data["steps"]
    rows, per_row = icon_grid(steps, w / EMU_PER_PT)
    gap, cell = icon_row(w, per_row)
    band = h / rows
    glyph = min(cell * 0.62, band * 0.5)
    size = label_size(steps, cell / EMU_PER_PT)
    for index, label in enumerate(steps):
        row, column = divmod(index, per_row)
        left = x + column * (cell + gap)
        top = y + row * band
        origin_x = left + (cell - glyph) / 2
        # Иконка из библиотеки ассетов, если вёрстка её подобрала; композиция
        # фигур — запасной вариант.
        draw = style.get("glyph")
        if draw and draw(shapes, index, (int(origin_x), int(top), int(glyph), int(glyph))):
            style["caption"](
                shapes,
                (int(left), int(top + glyph + band * 0.06), int(cell), int(band - glyph - band * 0.06)),
                label,
                size,
            )
            continue
        for preset, gx, gy, gw, gh, role in ICONS[pick_icon(label)]:
            shape = shapes.add_shape(
                preset,
                int(origin_x + gx * glyph),
                int(top + gy * glyph),
                int(max(1, gw * glyph)),
                int(max(1, gh * glyph)),
            )
            style["paint"](shape, role)
        style["caption"](
            shapes,
            (
                int(left),
                int(top + glyph + band * 0.06),
                int(cell),
                int(band - glyph - band * 0.06),
            ),
            label,
            size,
        )


def draw_process(shapes, box, data, style):
    """Последовательность шагов стрелками-шевронами.

    Когда подписи не влезают в ряд целыми словами, шевроны разворачиваются в
    столбик: у каждого шага появляется вся ширина области.
    """
    x, y, w, h = box
    steps = data["steps"]
    gap = w * 0.012
    cell = (w - gap * (len(steps) - 1)) / len(steps)
    # Стрелка шеврона вырезает по половине высоты с каждой стороны, поэтому
    # высокий шеврон почти не оставляет места тексту. Держим его низким.
    height = min(h, cell * 0.62)
    # Стрелка вырезает по половине высоты с каждой стороны: это и есть потеря
    # ширины под текст. Оценка честная, поэтому длинное слово не рвётся.
    usable = max(0.22, (cell - height) / cell)
    if not word_fits(steps, cell / EMU_PER_PT, usable):
        band = h / len(steps)
        row_height = min(band * 0.86, h * 0.3)
        row_fit = max(0.22, (w - row_height) / w)
        size = label_size(steps, w / EMU_PER_PT, row_fit)
        for index, label in enumerate(steps):
            shape = shapes.add_shape(
                SHAPE.PENTAGON if index == 0 else SHAPE.CHEVRON,
                int(x),
                int(y + index * band + (band - row_height) / 2),
                int(w),
                int(row_height),
            )
            style["paint"](shape, "solid")
            style["label"](shape, label, size)
        return
    top = y + (h - height) / 2
    size = label_size(steps, cell / EMU_PER_PT, usable)
    for index, label in enumerate(steps):
        shape = shapes.add_shape(
            SHAPE.PENTAGON if index == 0 else SHAPE.CHEVRON,
            int(x + index * (cell + gap)),
            int(top),
            int(cell),
            int(height),
        )
        style["paint"](shape, "solid")
        style["label"](shape, label, size)


def draw_cycle(shapes, box, data, style):
    """Замкнутый цикл: шаги по кругу, между ними изогнутые стрелки."""
    x, y, w, h = box
    steps = data["steps"]
    radius = min(w, h) * 0.34
    cx, cy = x + w / 2, y + h / 2
    node = min(radius * 1.15, min(w, h) * 0.34)
    size = label_size(steps, node / EMU_PER_PT, 0.68)
    for index, label in enumerate(steps):
        angle = -math.pi / 2 + index * 2 * math.pi / len(steps)
        nx = cx + radius * math.cos(angle) - node / 2
        ny = cy + radius * math.sin(angle) - node / 2
        shape = shapes.add_shape(SHAPE.OVAL, int(nx), int(ny), int(node), int(node))
        style["paint"](shape, "solid")
        style["label"](shape, label, size)
    arrow = shapes.add_shape(
        SHAPE.CIRCULAR_ARROW,
        int(cx - radius * 0.45),
        int(cy - radius * 0.45),
        int(radius * 0.9),
        int(radius * 0.9),
    )
    style["paint"](arrow, "solid")


def draw_pyramid(shapes, box, data, style):
    """Пирамида: от основания к вершине, верхний уровень — первый шаг."""
    x, y, w, h = box
    steps = data["steps"]
    levels = len(steps)
    band = h / levels
    # Кегль один на всю схему, и считается он по самому узкому ярусу — верхнему.
    size = label_size(steps, w * (0.34 + 0.66 / levels) / EMU_PER_PT, 0.55)
    for index, label in enumerate(steps):
        width = w * (0.34 + 0.66 * (index + 1) / levels)
        shape = shapes.add_shape(
            SHAPE.ISOSCELES_TRIANGLE if index == 0 else SHAPE.TRAPEZOID,
            int(x + (w - width) / 2),
            int(y + index * band),
            int(width),
            int(band * 0.94),
        )
        style["paint"](shape, "solid")
        style["label"](shape, label, size)


def draw_timeline(shapes, box, data, style):
    """Ось времени: линия и вехи с подписями.

    Подписи стоят по разные стороны линии через одну, поэтому соседние друг
    другу не мешают: рамка подписи шире ячейки, и дата не рвётся по слогам.
    """
    x, y, w, h = box
    steps = data["steps"]
    line_y = y + h * 0.46
    line = shapes.add_shape(
        SHAPE.RECTANGLE, int(x), int(line_y), int(w), int(max(2, h * 0.03))
    )
    style["paint"](line, "solid")
    cell = w / len(steps)
    # Соседняя подпись — по другую сторону линии, поэтому занять можно больше
    # ячейки. По краям области рамка подрезается, чтобы не уехать со слайда.
    caption_w = cell if len(steps) < 2 else min(w, cell * TIMELINE_CAPTION_SPAN)
    marker = min(cell * 0.3, h * 0.22)
    size = label_size(steps, caption_w / EMU_PER_PT)
    for index, label in enumerate(steps):
        center = x + cell * (index + 0.5)
        dot = shapes.add_shape(
            SHAPE.OVAL,
            int(center - marker / 2),
            int(line_y - marker / 2 + h * 0.015),
            int(marker),
            int(marker),
        )
        style["paint"](dot, "solid")
        top = y if index % 2 == 0 else line_y + marker
        left = min(max(x, center - caption_w / 2), x + w - caption_w)
        style["caption"](
            shapes,
            (int(left), int(top), int(caption_w), int(h * 0.38)),
            label,
            size,
        )


def draw_comparison(shapes, box, data, style):
    """Две колонки сравнения: заголовки и построчные пары."""
    x, y, w, h = box
    columns = data["columns"][:2]
    rows = [row[:2] for row in data["rows"]]
    gap = w * 0.03
    column = (w - gap) / 2
    header = min(h * 0.22, h / (len(rows) + 1))
    # Один кегль на всю схему: заголовки колонок и ячейки набраны одинаково.
    size = label_size(
        [*columns, *(v for row in rows for v in row)], column / EMU_PER_PT
    )
    for index, title in enumerate(columns):
        shape = shapes.add_shape(
            SHAPE.ROUNDED_RECTANGLE,
            int(x + index * (column + gap)),
            int(y),
            int(column),
            int(header * 0.9),
        )
        style["paint"](shape, "solid")
        style["label"](shape, title, size)
    if not rows:
        return
    band = (h - header) / len(rows)
    for line, values in enumerate(rows):
        for index, value in enumerate(values):
            shape = shapes.add_shape(
                SHAPE.ROUNDED_RECTANGLE,
                int(x + index * (column + gap)),
                int(y + header + line * band),
                int(column),
                int(band * 0.88),
            )
            style["paint"](shape, "outline")
            style["label"](shape, value, size, outline=True)


def _plan(texts, width, fit=1.0):
    size = label_size(texts, width, fit)
    return {"size": round(size, 2), "word_break": not word_fits(texts, width, fit, size)}


def label_plan(kind, box, data):
    """Кегль подписей схемы и признак переноса внутри слова.

    Одна формула на экспорт и на аудит: иначе вёрстка выдаёт слайды, которые её
    же проверка отклоняет. Ширина считается так же, как в соответствующей
    функции рисования, поэтому цифры совпадают с тем, что попадёт в файл.
    """
    _, _, w, h = box
    steps = list(data.get("steps") or [])
    if kind == "icon" and steps:
        return _plan(steps, icon_row(w, icon_grid(steps, w)[1])[1])
    if kind == "process" and steps:
        cell = (w - w * 0.012 * (len(steps) - 1)) / len(steps)
        height = min(h, cell * 0.62)
        fit = max(0.22, (cell - height) / cell)
        if word_fits(steps, cell, fit):
            return _plan(steps, cell, fit)
        row_height = min(h / len(steps) * 0.86, h * 0.3)
        return _plan(steps, w, max(0.22, (w - row_height) / w))
    if kind == "timeline" and steps:
        cell = w / len(steps)
        return _plan(steps, cell if len(steps) < 2 else min(w, cell * TIMELINE_CAPTION_SPAN))
    if kind == "cycle" and steps:
        node = min(min(w, h) * 0.34 * 1.15, min(w, h) * 0.34)
        return _plan(steps, node, 0.68)
    if kind == "pyramid" and steps:
        return _plan(steps, w * (0.34 + 0.66 / len(steps)), 0.55)
    if kind == "comparison":
        columns = (data.get("columns") or [])[:2]
        rows = [v for row in data.get("rows") or [] for v in row[:2]]
        texts = [*columns, *rows]
        if texts:
            return _plan(texts, (w - w * 0.03) / 2)
    return None


DIAGRAMS = {
    "icon": draw_icons,
    "process": draw_process,
    "cycle": draw_cycle,
    "pyramid": draw_pyramid,
    "timeline": draw_timeline,
    "comparison": draw_comparison,
}
