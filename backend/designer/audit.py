import hashlib
import math
import re

from fastapi import HTTPException

from .generation import completion
from .layout import DEFAULT_MARGINS, DEFAULT_SAFE_AREA, estimated_text_height
from .parsing import best_text_color, contrast_ratio

MIN_CONTRAST = 4.5
MAX_BULLETS = 6
MAX_BULLET_WORDS = 15
MAX_TABLE_ROWS = 7
MAX_TABLE_COLUMNS = 5
MAX_SERIES = 5
MAX_FONT_FAMILIES = 2
MIN_FONT_SIZE = 12
# A slide below the first value reads as empty, above the second as a wall of text.
FILL_RANGE = (0.25, 0.75)
ALIGN_TOLERANCE = 2.0
EDGE_TOLERANCE = 1.0

CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LATIN = re.compile(r"[A-Za-z]")
# Units, tickers and abbreviations that stay Latin inside a Russian deck.
LATIN_ALLOWED = {
    "kpi", "it", "ai", "ml", "b2b", "b2c", "api", "sla", "roi", "mvp", "crm", "erp",
    "usd", "eur", "rub", "gb", "tb", "mb", "ms", "vk", "q1", "q2", "q3", "q4", "na",
}


def visual_labels(visual):
    """Every piece of text a viewer reads inside a chart, table or diagram."""
    labels = [*visual.get("categories", []), *visual.get("columns", []), *visual.get("steps", [])]
    labels += [series["name"] for series in visual.get("series", [])]
    labels += [cell for row in visual.get("rows", []) for cell in row]
    if visual.get("unit"):
        labels.append(visual["unit"])
    return [str(label) for label in labels if str(label).strip()]


def foreign_labels(labels, cyrillic_deck):
    """Labels written in the wrong script for this deck.

    The brief asks for one language per deck, and chart labels are exactly where a
    model silently switches back to English. Deterministic: script, not meaning.
    """
    if not cyrillic_deck:
        return []
    found = []
    for label in labels:
        if CYRILLIC.search(label) or not LATIN.search(label):
            continue
        # Digits stay with their word so "Q1" is recognised as an abbreviation.
        words = [
            w
            for w in re.split(r"[^A-Za-z0-9]+", label.lower())
            if w and any(c.isalpha() for c in w)
        ]
        if words and all(word in LATIN_ALLOWED for word in words):
            continue
        found.append(label)
    return found


def intersection(first, second):
    x, y, w, h = first
    ox, oy, ow, oh = second
    return max(0.0, min(x + w, ox + ow) - max(x, ox)) * max(
        0.0, min(y + h, oy + oh) - max(y, oy)
    )


def inside(box, container, tolerance=EDGE_TOLERANCE):
    x, y, w, h = box
    cx, cy, cw, ch = container
    return (
        x >= cx - tolerance
        and y >= cy - tolerance
        and x + w <= cx + cw + tolerance
        and y + h <= cy + ch + tolerance
    )


def clamp_box(box, container):
    x, y, w, h = box
    cx, cy, cw, ch = container
    w, h = min(w, cw), min(h, ch)
    return [
        max(cx, min(x, cx + cw - w)),
        max(cy, min(y, cy + ch - h)),
        w,
        h,
    ]


def ink_area(element):
    """Area a block actually covers once rendered.

    A text box is allocated generously and usually holds less; measuring the
    estimated text height instead of the frame keeps the fill ratio honest.
    """
    _, _, w, h = element["box"]
    if element["kind"] == "text":
        return w * min(h, estimated_text_height(element))
    return w * h


def issue(
    slide,
    element,
    code,
    message,
    box=None,
    fixable=False,
    category="deterministic",
    severity="warning",
):
    identifier = hashlib.sha256(f"{slide}:{element}:{code}".encode()).hexdigest()[:20]
    return {
        "id": identifier,
        "slide_index": slide,
        "element_id": element,
        "code": code,
        "message": message,
        "box": box,
        "fixable": fixable,
        "category": category,
        "severity": severity,
    }


def audit(deck, template, sources):
    issues = []
    seen = set()
    width, height = deck["width"], deck["height"]
    geometry = template.get("geometry") or {}
    safe = geometry.get("safe_area") or DEFAULT_SAFE_AREA
    margins = geometry.get("margins") or DEFAULT_MARGINS
    slide_box = (0.0, 0.0, width, height)
    margin_box = (
        width * margins["x"],
        height * margins["y"],
        width * margins["w"],
        height * margins["h"],
    )
    slide_area = width * height
    scale = [s for s in template["tokens"]["font_sizes"] if s > 0]
    palette = {c.upper() for c in template["tokens"]["colors"]}
    known_layouts = {item["index"] for item in template.get("layouts", [])}
    patterns = {p["index"]: p for p in template["patterns"]}
    families = set()
    allowed_refs = {s["id"] for s in sources}
    deck_text = " ".join(
        slide["content"]["title"] + " " + " ".join(slide["content"]["bullets"])
        for slide in deck["slides"]
    )
    # The script the deck is written in decides what counts as a foreign label.
    cyrillic_deck = len(CYRILLIC.findall(deck_text)) > len(LATIN.findall(deck_text))
    source_text = "\n".join(s["text"] for s in sources)
    source_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", source_text))
    for slide in deck["slides"]:
        index = slide["index"]
        content = slide["content"]
        elements = slide["elements"]
        title_key = (content["title"], tuple(content["bullets"]))
        if title_key in seen:
            issues.append(
                issue(
                    index,
                    None,
                    "duplicate_slide",
                    "Повторяется заголовок и текст другого слайда",
                )
            )
        seen.add(title_key)
        if not content["bullets"] and content["visual"]["kind"] == "none":
            issues.append(
                issue(index, None, "empty_content", "На слайде только заголовок")
            )
        if not content["source_refs"] or set(content["source_refs"]) - allowed_refs:
            issues.append(
                issue(
                    index,
                    None,
                    "source_reference",
                    "Нет корректных ссылок на исходные материалы",
                )
            )
        if len(content["bullets"]) > 6:
            issues.append(
                issue(
                    index,
                    None,
                    "bullet_count",
                    "Больше 6 тезисов; отредактируйте содержание",
                )
            )
        for j, bullet in enumerate(content["bullets"]):
            if len(bullet.split()) > 15:
                issues.append(
                    issue(
                        index, f"bullet_{j}", "bullet_length", "Тезис длиннее 15 слов"
                    )
                )
        text = content["title"] + "\n" + "\n".join(content["bullets"])
        if re.search(
            r"lorem ipsum|\bXXX\b|\bTODO\b|вставьте текст", text, re.IGNORECASE
        ):
            issues.append(
                issue(
                    index,
                    None,
                    "placeholder",
                    "В содержании остался текст-заглушка",
                    severity="error",
                )
            )
        visual = content["visual"]
        strangers = foreign_labels(visual_labels(visual), cyrillic_deck)
        if strangers:
            issues.append(
                issue(
                    index,
                    "visual",
                    "foreign_language",
                    "Подписи в визуализации на другом языке: "
                    + ", ".join(sorted(set(strangers))[:5]),
                )
            )
        if visual["kind"] == "table":
            if (
                len(visual["columns"]) > MAX_TABLE_COLUMNS
                or len(visual["rows"]) > MAX_TABLE_ROWS
            ):
                issues.append(
                    issue(
                        index,
                        None,
                        "table_size",
                        f"Таблица {len(visual['rows'])}×{len(visual['columns'])}; "
                        f"ориентир — не более {MAX_TABLE_ROWS} строк и {MAX_TABLE_COLUMNS} колонок",
                    )
                )
        if visual["kind"] in ("bar", "line"):
            if len(visual["series"]) > MAX_SERIES:
                issues.append(
                    issue(
                        index,
                        None,
                        "chart_series",
                        f"На диаграмме {len(visual['series'])} серий; ориентир — не более {MAX_SERIES}",
                    )
                )
            if not visual.get("unit", "").strip():
                issues.append(
                    issue(
                        index,
                        None,
                        "chart_labels",
                        "У диаграммы не указана единица измерения по оси значений",
                    )
                )
        if slide.get("layout_index") not in known_layouts:
            issues.append(
                issue(
                    index,
                    None,
                    "layout_not_from_template",
                    "Слайд собран не на макете из шаблона",
                    severity="error",
                )
            )
        fill = sum(ink_area(e) for e in elements) / slide_area if slide_area else 0
        if fill < FILL_RANGE[0] or fill > FILL_RANGE[1]:
            issues.append(
                issue(
                    index,
                    None,
                    "fill_ratio",
                    f"Слайд заполнен на {round(fill * 100)}%; ориентир — от "
                    f"{round(FILL_RANGE[0] * 100)}% до {round(FILL_RANGE[1] * 100)}%",
                )
            )
        background = slide.get("background") or template["tokens"]["theme"].get(
            "lt1", "FFFFFF"
        )
        numbers = set(re.findall(r"\d+(?:[.,]\d+)?", text))
        if numbers - source_numbers:
            issues.append(
                issue(
                    index,
                    None,
                    "unverified_number",
                    "Числа не найдены дословно в источниках: "
                    + ", ".join(sorted(numbers - source_numbers)),
                )
            )
        reserved = [
            (width * b["x"], height * b["y"], width * b["w"], height * b["h"])
            for b in patterns.get(slide.get("pattern_index"), {}).get("reserved", [])
        ]
        edges = [e["box"][0] for e in elements]
        for element in elements:
            x, y, w, h = element["box"]
            if not inside(element["box"], slide_box, 0.1):
                issues.append(
                    issue(
                        index,
                        element["id"],
                        "out_of_bounds",
                        "Блок выходит за границы слайда",
                        element["box"],
                        True,
                        severity="error",
                    )
                )
            elif not inside(element["box"], margin_box):
                issues.append(
                    issue(
                        index,
                        element["id"],
                        "margin_encroachment",
                        "Блок заходит в поля у краёв слайда",
                        element["box"],
                        True,
                    )
                )
            # A block should share a left edge with another block or sit on the
            # safe-area edge; a lone offset reads as a layout mistake.
            aligned = (
                len(elements) < 2
                or abs(x - width * safe["x"]) <= ALIGN_TOLERANCE
                or abs(x + w - width * (safe["x"] + safe["w"])) <= ALIGN_TOLERANCE
                or abs(x + w / 2 - width / 2) <= ALIGN_TOLERANCE
                or sum(abs(x - other) <= ALIGN_TOLERANCE for other in edges) > 1
            )
            if not aligned:
                issues.append(
                    issue(
                        index,
                        element["id"],
                        "misaligned",
                        "Блок не выровнен по направляющим макета",
                        element["box"],
                        True,
                    )
                )
            for box in reserved:
                overlap_area = intersection(element["box"], box)
                if overlap_area > 0.12 * min(w * h, box[2] * box[3]):
                    issues.append(
                        issue(
                            index,
                            element["id"],
                            "branding_overlap",
                            "Блок перекрывает элемент шаблона: логотип, колонтитул или декор",
                            element["box"],
                        )
                    )
                    break
            if element["kind"] == "text":
                families.add(element["font"])
                if scale and not any(
                    abs(element["font_size"] - size) < 0.6 for size in scale
                ):
                    issues.append(
                        issue(
                            index,
                            element["id"],
                            "font_size_off_scale",
                            f"Кегль {element['font_size']} pt отсутствует в типографической шкале шаблона",
                            element["box"],
                            True,
                        )
                    )
                color = (element.get("color") or "").upper()
                if palette and color and color not in palette:
                    issues.append(
                        issue(
                            index,
                            element["id"],
                            "color_not_in_palette",
                            "Цвет текста отсутствует в палитре шаблона",
                            element["box"],
                            True,
                        )
                    )
                if color and contrast_ratio(background, color) < MIN_CONTRAST:
                    issues.append(
                        issue(
                            index,
                            element["id"],
                            "low_contrast",
                            f"Контраст текста к фону ниже {MIN_CONTRAST}:1",
                            element["box"],
                            severity="error",
                        )
                    )
                if estimated_text_height(element) > h:
                    issues.append(
                        issue(
                            index,
                            element["id"],
                            "text_overflow",
                            "Оценка: текст может не поместиться в рамку",
                            element["box"],
                            True,
                        )
                    )
                if (
                    template["tokens"]["fonts"]
                    and element["font"] not in template["tokens"]["fonts"]
                ):
                    issues.append(
                        issue(
                            index,
                            element["id"],
                            "font_not_in_template",
                            "Шрифт отсутствует в шаблоне",
                            element["box"],
                        )
                    )
            for other in elements:
                if element["id"] >= other["id"]:
                    continue
                ox, oy, ow, oh = other["box"]
                if (
                    min(x + w, ox + ow) - max(x, ox) > 1
                    and min(y + h, oy + oh) - max(y, oy) > 1
                ):
                    issues.append(
                        issue(
                            index,
                            element["id"] + ":" + other["id"],
                            "overlap",
                            "Пересечение контентных блоков",
                            element["box"],
                        )
                    )
    if len(families) > MAX_FONT_FAMILIES:
        # Deck-level findings carry no slide index; the preview endpoint skips them.
        issues.append(
            issue(
                None,
                None,
                "font_variety",
                "В колоде больше двух гарнитур: " + ", ".join(sorted(families)),
            )
        )
    return {
        "issues": issues,
        "counts": {
            "errors": sum(i["severity"] == "error" for i in issues),
            "warnings": sum(i["severity"] == "warning" for i in issues),
        },
        "contextual": {"status": "not_run"},
        "geometry_units": "pt",
        "limitations": [
            "Text fit is estimated, not pixel-measured",
            "Collision checks use template shape boxes, not rendered pixels",
            "Fill ratio estimates rendered ink inside the template content area",
            "Contextual audit uses text, not slide images",
        ],
    }


async def contextual_audit(deck, sources):
    result = await completion(
        "audit", {"slides": [s["content"] for s in deck["slides"]], "sources": sources}
    )
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("issues"), list)
        or any(not isinstance(item, dict) for item in result["issues"])
    ):
        raise HTTPException(502, "LLM audit does not match the required schema")
    issues = []
    for j, item in enumerate(result["issues"][:200]):
        index = item.get("slide_index")
        if isinstance(index, int) and 0 <= index < len(deck["slides"]):
            issues.append(
                issue(
                    index,
                    f"context_{j}",
                    str(item.get("code", "content"))[:100],
                    str(item.get("message", ""))[:2000],
                    category="contextual",
                )
            )
    return issues


def apply_fixes(deck, report, issue_ids, template):
    known = {i["id"]: i for i in report["issues"]}
    if any(i not in known or not known[i]["fixable"] for i in issue_ids):
        raise ValueError("Select only existing fixable issues from this revision")
    width, height = deck["width"], deck["height"]
    geometry = template.get("geometry") or {}
    safe = geometry.get("safe_area") or DEFAULT_SAFE_AREA
    margins = geometry.get("margins") or DEFAULT_MARGINS
    margin_box = (
        width * margins["x"],
        height * margins["y"],
        width * margins["w"],
        height * margins["h"],
    )
    palette = template["tokens"]["colors"]
    scale = [s for s in template["tokens"]["font_sizes"] if s >= MIN_FONT_SIZE]
    for identifier in issue_ids:
        finding = known[identifier]
        slide = deck["slides"][finding["slide_index"]]
        element = next(e for e in slide["elements"] if e["id"] == finding["element_id"])
        if finding["code"] == "out_of_bounds":
            element["box"] = clamp_box(element["box"], (0.0, 0.0, width, height))
        elif finding["code"] == "margin_encroachment":
            element["box"] = clamp_box(element["box"], margin_box)
        elif finding["code"] == "misaligned":
            # Snap to the nearest edge other blocks already use, keeping the width.
            targets = [e["box"][0] for e in slide["elements"] if e is not element]
            targets.append(width * safe["x"])
            element["box"][0] = min(targets, key=lambda t: abs(t - element["box"][0]))
        elif finding["code"] == "font_size_off_scale" and scale:
            element["font_size"] = min(
                scale, key=lambda s: abs(s - element["font_size"])
            )
        elif finding["code"] == "color_not_in_palette" and palette:
            background = slide.get("background") or template["tokens"]["theme"].get(
                "lt1", "FFFFFF"
            )
            element["color"] = best_text_color(background, palette)
        elif finding["code"] == "text_overflow":
            sizes = sorted(
                {
                    s
                    for s in template["tokens"]["font_sizes"]
                    if 12 <= s < element["font_size"]
                },
                reverse=True,
            )
            for size in sizes:
                element["font_size"] = size
                if estimated_text_height(element) <= element["box"][3]:
                    break
    return deck
