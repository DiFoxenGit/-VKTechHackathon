"""Диаграммы и пиктограммы из нативных фигур PowerPoint.

Всё, что рисуется здесь, остаётся редактируемым объектом: фигуры шаблонных
геометрий, текст внутри них, цвета из палитры шаблона. Картинок не создаём —
ТЗ прямо не засчитывает слайд, выгруженный растром.

Координаты приходят в точках (Pt уже применён вызывающей стороной), поэтому
функции работают с числами и ничего не знают про единицы.
"""

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
    "точка": [
        (SHAPE.OVAL, 0.10, 0.10, 0.80, 0.80, "solid"),
    ],
}

# Слова, по которым подпись превращается в пиктограмму. Первое совпадение выигрывает,
# поэтому длинные и более конкретные корни идут раньше общих.
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("рост", ("рост", "выросл", "увелич", "прирост", "growth", "increase")),
    ("снижение", ("сниж", "паден", "сократ", "уменьш", "decline", "reduce")),
    ("время", ("врем", "срок", "быстр", "скорост", "часов", "недел", "квартал", "time")),
    ("команда", ("команд", "сотрудник", "пользоват", "клиент", "людей", "обучен", "поддержк", "team", "user", "support")),
    ("цель", ("цел", "задач", "фокус", "результат", "goal", "target")),
    ("идея", ("иде", "гипотез", "предлож", "концепц", "idea")),
    ("документ", ("документ", "отчёт", "отчет", "отчётн", "отчетн", "презентац", "полит", "регламент", "doc")),
    ("данные", ("данн", "база", "метрик", "аналит", "data")),
    ("решение", ("решени", "выбор", "вариант", "decision")),
    ("процесс", ("процесс", "автомат", "пайплайн", "интеграц", "настройк", "workflow", "process")),
    ("риск", ("риск", "проблем", "ошибк", "угроз", "risk", "issue")),
    ("качество", ("качеств", "оценк", "рейтинг", "лучш", "quality")),
    ("запуск", ("запуск", "старт", "релиз", "внедрен", "launch", "release")),
    ("деньги", ("деньг", "бюджет", "стоим", "выручк", "экономи", "руб", "cost", "budget")),
]


def pick_icon(label: str) -> str:
    """Пиктограмма по смыслу подписи; без совпадения — нейтральная точка."""
    text = label.lower()
    for name, roots in KEYWORDS:
        if any(root in text for root in roots):
            return name
    return "точка"


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


def draw_icons(shapes, box, data, style):
    """Ряд пиктограмм с подписями под ними."""
    x, y, w, h = box
    steps = data["steps"]
    gap = w * 0.04 / max(1, len(steps))
    cell = (w - gap * (len(steps) - 1)) / len(steps)
    glyph = min(cell * 0.62, h * 0.55)
    for index, label in enumerate(steps):
        left = x + index * (cell + gap)
        origin_x = left + (cell - glyph) / 2
        for preset, gx, gy, gw, gh, role in ICONS[pick_icon(label)]:
            shape = shapes.add_shape(
                preset,
                int(origin_x + gx * glyph),
                int(y + gy * glyph),
                int(max(1, gw * glyph)),
                int(max(1, gh * glyph)),
            )
            style["paint"](shape, role)
        style["caption"](
            shapes,
            (int(left), int(y + glyph + h * 0.06), int(cell), int(h - glyph - h * 0.06)),
            label,
        )


def draw_process(shapes, box, data, style):
    """Последовательность шагов стрелками-шевронами."""
    x, y, w, h = box
    steps = data["steps"]
    gap = w * 0.012
    cell = (w - gap * (len(steps) - 1)) / len(steps)
    # Стрелка шеврона вырезает по половине высоты с каждой стороны, поэтому
    # высокий шеврон почти не оставляет места тексту. Держим его низким.
    height = min(h, cell * 0.62)
    top = y + (h - height) / 2
    # Стрелка вырезает по половине высоты с каждой стороны: это и есть потеря
    # ширины под текст. Оценка честная, поэтому длинное слово не рвётся.
    usable = max(0.22, (cell - height) / cell)
    for index, label in enumerate(steps):
        shape = shapes.add_shape(
            SHAPE.PENTAGON if index == 0 else SHAPE.CHEVRON,
            int(x + index * (cell + gap)),
            int(top),
            int(cell),
            int(height),
        )
        style["paint"](shape, "solid")
        style["label"](shape, label, fit=usable)


def draw_cycle(shapes, box, data, style):
    """Замкнутый цикл: шаги по кругу, между ними изогнутые стрелки."""
    import math

    x, y, w, h = box
    steps = data["steps"]
    radius = min(w, h) * 0.34
    cx, cy = x + w / 2, y + h / 2
    node = min(radius * 1.15, min(w, h) * 0.34)
    for index, label in enumerate(steps):
        angle = -math.pi / 2 + index * 2 * math.pi / len(steps)
        nx = cx + radius * math.cos(angle) - node / 2
        ny = cy + radius * math.sin(angle) - node / 2
        shape = shapes.add_shape(SHAPE.OVAL, int(nx), int(ny), int(node), int(node))
        style["paint"](shape, "solid")
        style["label"](shape, label, fit=0.68)
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
        # Верхние уровни пирамиды узкие, подпись подстраивается под свой ярус.
        style["label"](shape, label, fit=0.55 if index == 0 else 0.72)


def draw_timeline(shapes, box, data, style):
    """Ось времени: линия и вехи с подписями."""
    x, y, w, h = box
    steps = data["steps"]
    line_y = y + h * 0.46
    line = shapes.add_shape(
        SHAPE.RECTANGLE, int(x), int(line_y), int(w), int(max(2, h * 0.03))
    )
    style["paint"](line, "solid")
    cell = w / len(steps)
    marker = min(cell * 0.3, h * 0.22)
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
        style["caption"](
            shapes,
            (int(center - cell / 2), int(top), int(cell), int(h * 0.38)),
            label,
        )


def draw_comparison(shapes, box, data, style):
    """Две колонки сравнения: заголовки и построчные пары."""
    x, y, w, h = box
    columns = data["columns"][:2]
    rows = [row[:2] for row in data["rows"]]
    gap = w * 0.03
    column = (w - gap) / 2
    header = min(h * 0.22, h / (len(rows) + 1))
    for index, title in enumerate(columns):
        shape = shapes.add_shape(
            SHAPE.ROUNDED_RECTANGLE,
            int(x + index * (column + gap)),
            int(y),
            int(column),
            int(header * 0.9),
        )
        style["paint"](shape, "solid")
        style["label"](shape, title)
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
            style["label"](shape, value, outline=True)


DIAGRAMS = {
    "icon": draw_icons,
    "process": draw_process,
    "cycle": draw_cycle,
    "pyramid": draw_pyramid,
    "timeline": draw_timeline,
    "comparison": draw_comparison,
}
