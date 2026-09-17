"""PPTX design extraction; never executes embedded content or external links."""

import csv
import io
import json
import zipfile
from collections import Counter
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn
from pypdf import PdfReader

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}

# Region a designer fills with content, as a fraction of the slide. Shapes that
# carry sample content here are replaced during export; everything else is branding.
CONTENT_REGION = (0.05, 0.23, 0.95, 0.87)

# Версия разбора. Меняется, когда правила извлечения меняют результат: шаблоны,
# разобранные старой версией, переразбираются при старте, иначе экспорт и аудит
# работали бы по устаревшему «паспорту» файла.
PARSER_VERSION = 8


def is_footer_placeholder(shape):
    return shape.is_placeholder and any(
        name in str(shape.placeholder_format.type)
        for name in ("FOOTER", "DATE", "SLIDE_NUMBER")
    )


def shape_key(shape, width, height):
    """Положение фигуры с точностью, достаточной, чтобы узнать её на другом слайде."""
    return (
        round(shape.left / width, 3),
        round(shape.top / height, 3),
        round(shape.width / width, 3),
        round(shape.height / height, 3),
    )


def branding_boxes(slides, width, height, share=0.4):
    """Фигуры, повторяющиеся на многих слайдах: логотип, плашка, колонтитул.

    Всё остальное на конкретном слайде — образец содержания: серые кружки под
    фото, рамки под иконки, демонстрационные иллюстрации. Единственный честный
    признак брендинга — повторяемость, а не координаты: в разных шаблонах
    логотип живёт где угодно.
    """
    counts = Counter()
    for slide in slides:
        seen = set()
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text.strip():
                continue
            if shape.is_placeholder:
                continue
            seen.add(shape_key(shape, width, height))
        counts.update(seen)
    threshold = max(2, int(len(slides) * share))
    return {box for box, count in counts.items() if count >= threshold}


def master_text_defaults(master, theme):
    """Типографика уровня мастера: p:txStyles — последний источник правды.

    Стиль заголовка и текста в шаблоне часто не написан ни на слайде, ни на
    макете: он объявлен один раз в мастере. Без него мы бы подставляли свой
    кегль и цвет, то есть ломали дизайн-систему шаблона.
    """
    defaults = {}
    styles = master._element.find(qn("p:txStyles"))
    if styles is None:
        return defaults
    for role, tag in (("title", "p:titleStyle"), ("body", "p:bodyStyle")):
        node = styles.find(qn(tag))
        if node is None:
            continue
        level = node.find(qn("a:lvl1pPr"))
        if level is None:
            continue
        style = {"font": None, "size": None, "bold": None, "color": None, "align": None}
        if level.get("algn"):
            style["align"] = level.get("algn")
        run = level.find(qn("a:defRPr"))
        if run is not None:
            if run.get("sz"):
                style["size"] = round(int(run.get("sz")) / 100, 2)
            if run.get("b") is not None:
                style["bold"] = run.get("b") in ("1", "true")
            latin = run.find(qn("a:latin"))
            if latin is not None and latin.get("typeface"):
                face = latin.get("typeface")
                style["font"] = None if face.startswith("+") else face
            srgb = run.find(f"{qn('a:solidFill')}/{qn('a:srgbClr')}")
            scheme = run.find(f"{qn('a:solidFill')}/{qn('a:schemeClr')}")
            if srgb is not None:
                style["color"] = srgb.get("val")
            elif scheme is not None:
                style["color"] = theme.get(scheme.get("val"))
        defaults[role] = style
    return defaults


def frame_defaults(shape, theme):
    """Стиль, объявленный в самой рамке: <a:lstStyle> первого уровня.

    В шаблонах формат заголовка обычно живёт здесь — на плейсхолдере макета, а не
    в runs слайда, где текста может не быть вовсе.
    """
    style = {"font": None, "size": None, "bold": None, "color": None, "align": None}
    if not shape.has_text_frame:
        return style
    body = shape.text_frame._txBody
    level = body.find(f"{qn('a:lstStyle')}/{qn('a:lvl1pPr')}")
    if level is None:
        return style
    if level.get("algn"):
        style["align"] = level.get("algn")
    run = level.find(qn("a:defRPr"))
    if run is None:
        return style
    if run.get("sz"):
        style["size"] = round(int(run.get("sz")) / 100, 2)
    if run.get("b") is not None:
        style["bold"] = run.get("b") in ("1", "true")
    latin = run.find(qn("a:latin"))
    if latin is not None and latin.get("typeface"):
        face = latin.get("typeface")
        style["font"] = None if face.startswith("+") else face
    srgb = run.find(f"{qn('a:solidFill')}/{qn('a:srgbClr')}")
    scheme = run.find(f"{qn('a:solidFill')}/{qn('a:schemeClr')}")
    if srgb is not None:
        style["color"] = srgb.get("val")
    elif scheme is not None:
        style["color"] = theme.get(scheme.get("val"))
    return style


def text_style(shape, theme):
    """Как шаблон оформляет текст в этой рамке.

    Мы не изобретаем типографику: заголовок нового слайда получает кегль, цвет,
    начертание и выравнивание того блока, который занимал его место в шаблоне.
    Берём первый непустой абзац — он задаёт тон всей рамке.
    """
    style = {
        "font": None,
        "size": None,
        "bold": None,
        "color": None,
        "align": None,
        "caps": False,
    }
    for paragraph in shape.text_frame.paragraphs:
        if not paragraph.text.strip() and not paragraph.runs:
            continue
        if paragraph.alignment is not None:
            style["align"] = str(paragraph.alignment).split(" ")[0].lower()
        for font in [*(run.font for run in paragraph.runs), paragraph.font]:
            if style["font"] is None and font.name and not font.name.startswith("+"):
                style["font"] = font.name
            if style["size"] is None and font.size:
                style["size"] = round(font.size.pt, 2)
            if style["bold"] is None and font.bold is not None:
                style["bold"] = bool(font.bold)
            if style["color"] is None:
                value = color_value(font.color, theme)
                if value:
                    style["color"] = value
        break
    for key, value in frame_defaults(shape, theme).items():
        if style.get(key) is None:
            style[key] = value
    text = shape.text.strip()
    style["caps"] = bool(text) and text == text.upper() and any(c.isalpha() for c in text)
    return style


def preserved_shape(shape, width, height, branding=None):
    """True when export keeps this template shape: artwork, footers, page numbers.

    Export and audit must agree on what survives cloning, otherwise the audit
    would check collisions against shapes that are not on the finished slide.
    """
    if shape.has_table or shape.has_chart:
        return False
    # Плейсхолдер — это место под контент, а не украшение. Пустая рамка под фото
    # или иконку, перенесённая в результат, читается как мусор на слайде.
    # Исключение — колонтитул, дата и номер: они часть фирменного оформления.
    if shape.is_placeholder:
        return is_footer_placeholder(shape)
    x, y, w, h = (
        shape.left / width,
        shape.top / height,
        shape.width / width,
        shape.height / height,
    )
    left, top, right, bottom = CONTENT_REGION
    inside = min(y + h, bottom) > max(y, top) and min(x + w, right) > max(x, left)
    # Заполненный текст — всегда образец: его заменяет новый контент.
    if shape.has_text_frame and shape.text.strip():
        return False
    # Остальное — фигуры без текста: фон, плашки, кружки-заглушки под фото.
    # Автофигура тоже имеет текстовую рамку, поэтому решает не наличие рамки,
    # а повторяемость по колоде.
    if branding is not None:
        # Фон во всю страницу остаётся всегда, остальное — только если
        # повторяется по колоде.
        return w * h >= 0.85 or shape_key(shape, width, height) in branding
    # Без статистики по шаблону остаётся прежнее правило про рабочую область.
    return not (w * h < 0.85 and inside)


def relative_luminance(value):
    rgb = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    rgb = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return sum(c * k for c, k in zip(rgb, (0.2126, 0.7152, 0.0722)))


def contrast_ratio(first, second):
    """WCAG contrast between two RRGGBB colors; 1.0 when identical, 21.0 black on white."""
    try:
        a, b = relative_luminance(first), relative_luminance(second)
    except (ValueError, IndexError, TypeError):
        return 21.0
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def best_text_color(background, palette):
    """Most readable palette color on this background, so text stays inside the brand."""
    return max(
        palette or ["000000", "FFFFFF"],
        key=lambda c: contrast_ratio(background, c),
    )


def background_info(slide, theme):
    """Чем залит слайд: сплошной цвет, градиент или картинка.

    Для сплошного цвета можно честно посчитать контраст текста. Для градиента и
    фотографии цвет в конкретной точке неизвестен, поэтому вёрстка обязана
    положить под текст подложку, а не надеяться на удачу.
    """
    for owner in (slide, slide.slide_layout, slide.slide_layout.slide_master):
        bg = owner._element.cSld.bg
        if bg is None:
            continue
        if bg.xpath(".//a:blipFill"):
            return {"color": theme.get("lt1", "FFFFFF"), "kind": "image"}
        rgb = bg.xpath(".//a:solidFill/a:srgbClr/@val")
        if rgb:
            return {"color": rgb[0], "kind": "solid"}
        scheme = bg.xpath(".//a:solidFill/a:schemeClr/@val")
        if scheme and scheme[0] in theme:
            return {"color": theme[scheme[0]], "kind": "solid"}
        stops = bg.xpath(".//a:gsLst/a:gs//a:srgbClr/@val")
        if stops:
            # У градиента берём самый светлый край: подложка всё равно обязательна.
            return {
                "color": max(stops, key=relative_luminance),
                "kind": "gradient",
            }
    return {"color": theme.get("lt1", "FFFFFF"), "kind": "solid"}


def background_color(slide, theme):
    """Цвет фона слайда; для картинки и градиента — приближение."""
    return background_info(slide, theme)["color"]


def check_zip(data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 10000
            or sum(x.file_size for x in entries) > 300 * 1024 * 1024
        ):
            raise ValueError("Archive expands beyond 300 MB or 10000 entries")
        if any(x.flag_bits & 1 for x in entries):
            raise ValueError("Encrypted archives are not supported")


def color_value(color, theme):
    try:
        if color.type is not None:
            if color.type == 1:
                return str(color.rgb)
            key = str(color.theme_color).split(" (")[0].lower()
            key = {
                "dark_1": "dk1",
                "dark_2": "dk2",
                "light_1": "lt1",
                "light_2": "lt2",
                "text_1": "dk1",
                "text_2": "dk2",
                "background_1": "lt1",
                "background_2": "lt2",
            }.get(key, key)
            return theme.get(key)
    except (AttributeError, ValueError):
        pass
    return None


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * (len(ordered) - 1) + 0.5))]


def derive_geometry(patterns):
    """Safe area and vertical guides inferred from where the template puts text.

    The service must fit an unseen template, so margins come from the file rather
    than from constants. Values are fractions of the slide; defaults apply when a
    template carries too little text to measure.
    """
    boxes = [
        shape["box"]
        for pattern in patterns
        for shape in pattern["shapes"]
        if shape["text"].strip() and 0.004 < shape["box"]["w"] * shape["box"]["h"] < 0.6
    ]
    safe_area = {"x": 0.055, "y": 0.055, "w": 0.89, "h": 0.825}
    # Outer limit: no template element sits closer to an edge than this. The safe
    # area is the design rhythm used for placement; margins are the hard boundary
    # the audit enforces, so a title that legitimately rides high is not flagged.
    margins = {"x": 0.04, "y": 0.04, "w": 0.92, "h": 0.9}
    guides = []
    if len(boxes) >= 3:
        outer_left = min(0.1, max(0.02, min(b["x"] for b in boxes)))
        outer_top = min(0.1, max(0.02, min(b["y"] for b in boxes)))
        outer_right = min(0.98, max(0.9, max(b["x"] + b["w"] for b in boxes)))
        outer_bottom = min(0.98, max(0.9, max(b["y"] + b["h"] for b in boxes)))
        margins = {
            "x": round(outer_left, 5),
            "y": round(outer_top, 5),
            "w": round(outer_right - outer_left, 5),
            "h": round(outer_bottom - outer_top, 5),
        }
        left = min(0.14, max(0.03, percentile([b["x"] for b in boxes], 0.1)))
        right = min(0.97, max(0.86, percentile([b["x"] + b["w"] for b in boxes], 0.9)))
        top = min(0.14, max(0.03, percentile([b["y"] for b in boxes], 0.1)))
        bottom = min(0.97, max(0.86, percentile([b["y"] + b["h"] for b in boxes], 0.9)))
        safe_area = {
            "x": round(left, 5),
            "y": round(top, 5),
            "w": round(right - left, 5),
            "h": round(bottom - top, 5),
        }
        # An edge repeated across slides is a guide the designer actually used.
        edges = Counter()
        for pattern in patterns:
            seen = {
                round(value, 3)
                for shape in pattern["shapes"]
                if shape["text"].strip()
                for value in (shape["box"]["x"], shape["box"]["x"] + shape["box"]["w"])
            }
            edges.update(seen)
        # Cluster near-identical edges so one guide is one design decision.
        guides = []
        for value in sorted(v for v in edges if 0 <= v <= 1):
            if guides and value - guides[-1][0] <= 0.008:
                guides[-1][1] += edges[value]
            else:
                guides.append([value, edges[value]])
        guides = [round(value, 4) for value, count in guides if count >= 3]
    return {"safe_area": safe_area, "margins": margins, "guides": guides}


def parse_template(data: bytes, name: str):
    check_zip(data)
    deck = Presentation(io.BytesIO(data))
    if not deck.slides or len(deck.slides) > 200:
        raise ValueError("Template must contain 1 to 200 slides")
    theme = {}
    fonts, sizes, colors = Counter(), Counter(), Counter()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for filename in archive.namelist():
            if filename.startswith("ppt/theme/theme") and filename.endswith(".xml"):
                root = etree.fromstring(
                    archive.read(filename),
                    etree.XMLParser(resolve_entities=False, no_network=True),
                )
                for entry in root.findall(".//a:clrScheme/*", NS):
                    if len(entry):
                        value = (
                            entry[0].get("val")
                            if entry[0].tag.endswith("srgbClr")
                            else entry[0].get("lastClr")
                        )
                        if value:
                            key = etree.QName(entry).localname
                            theme[key] = value
                            theme[key.replace("accent", "accent_")] = value
                            colors[value] += 1
                for element in root.findall(".//a:fontScheme//a:latin", NS):
                    if element.get("typeface"):
                        fonts[element.get("typeface")] += 1
    width, height = int(deck.slide_width), int(deck.slide_height)

    def scan(shapes):
        results = []
        for shape in shapes:
            box = {
                "x": round(shape.left / width, 5),
                "y": round(shape.top / height, 5),
                "w": round(shape.width / width, 5),
                "h": round(shape.height / height, 5),
            }
            item = {
                "id": shape.shape_id,
                "name": shape.name,
                "type": str(shape.shape_type),
                "box": box,
                "text": "",
            }
            if shape.has_text_frame:
                item["text"] = shape.text[:2000]
                item["style"] = text_style(shape, theme)
                for p in shape.text_frame.paragraphs:
                    for font in [p.font, *(r.font for r in p.runs)]:
                        if font.name and not font.name.startswith("+"):
                            fonts[font.name] += 1
                        if font.size:
                            sizes[round(font.size.pt, 2)] += 1
                        value = color_value(font.color, theme)
                        if value:
                            colors[value] += 1
            if hasattr(shape, "fill"):
                try:
                    if shape.fill.type == 1:
                        value = color_value(shape.fill.fore_color, theme)
                        if value:
                            colors[value] += 1
                except (AttributeError, ValueError):
                    pass
            if shape.shape_type == 6:
                item["children"] = scan(shape.shapes)
            if shape.is_placeholder:
                item["placeholder"] = str(shape.placeholder_format.type)
            results.append(item)
        return results

    patterns = []
    layouts = list(deck.slide_layouts)
    branding = branding_boxes(list(deck.slides), width, height)
    master_defaults = {}
    for master in deck.slide_masters:
        master_defaults = master_text_defaults(master, theme) or master_defaults
        if master_defaults:
            break

    def inherit_styles(slide, shapes):
        """Стиль плейсхолдера живёт в макете: на слайде он часто пустой.

        Без этого заголовок нового слайда получил бы кегль по умолчанию вместо
        фирменного, хотя шаблон его задаёт — просто уровнем выше.
        """
        layout_styles = {}
        for shape in slide.slide_layout.placeholders:
            if shape.has_text_frame:
                layout_styles[shape.placeholder_format.idx] = text_style(shape, theme)
        for shape in slide.slide_layout.slide_master.placeholders:
            if shape.has_text_frame:
                master_style = text_style(shape, theme)
                role = "title" if "TITLE" in str(shape.placeholder_format.type) else "body"
                master_defaults.setdefault(role, {})
                for key, value in master_style.items():
                    if master_defaults[role].get(key) is None:
                        master_defaults[role][key] = value
        for item, shape in zip(shapes, slide.shapes):
            if not shape.is_placeholder or "style" not in item:
                continue
            role = (
                "title"
                if "TITLE" in str(shape.placeholder_format.type)
                else "body"
            )
            for parent in (
                layout_styles.get(shape.placeholder_format.idx),
                master_defaults.get(role),
            ):
                if not parent:
                    continue
                for key, value in parent.items():
                    if item["style"].get(key) is None:
                        item["style"][key] = value
        return shapes

    for index, slide in enumerate(deck.slides):
        shapes = inherit_styles(slide, scan(slide.shapes))
        text_shapes = [s for s in shapes if s["text"].strip()]
        title = next(
            (s for s in text_shapes if "TITLE" in s.get("placeholder", "")), None
        )
        if title is None and text_shapes:
            title = min(text_shapes, key=lambda s: s["box"]["y"])
        # Score layout decorations inside the content area, excluding full-page backgrounds.
        decoration_area = 0.0
        decoration_count = 0
        for sh in slide.slide_layout.shapes:
            if sh.is_placeholder:
                continue
            x, y, w, h = (
                sh.left / width,
                sh.top / height,
                sh.width / width,
                sh.height / height,
            )
            if w * h < 0.85:
                covered = max(0, min(x + w, 0.95) - max(x, 0.05)) * max(
                    0, min(y + h, 0.87) - max(y, 0.23)
                )
                decoration_area += covered
                if covered > 0:
                    decoration_count += 1
        # Фотофон: на таком слайде обычный тёмный текст просто не читается.
        background = background_info(slide, theme)
        image_cover = 1.0 if background["kind"] != "solid" else 0.0
        for sh in list(slide.shapes) + list(slide.slide_layout.shapes):
            if sh.shape_type == 13:  # PICTURE
                image_cover = max(
                    image_cover, (sh.width / width) * (sh.height / height)
                )
        # Shapes that survive cloning: artwork, footers, page numbers. Content must
        # not collide with them, so the audit needs their boxes.
        reserved = []
        kept = [
            sh for sh in slide.shapes if preserved_shape(sh, width, height, branding)
        ]
        # Layout artwork is inherited by the cloned slide even though it is not copied.
        kept += [sh for sh in slide.slide_layout.shapes if not sh.is_placeholder]
        for sh in kept:
            box = {
                "x": round(sh.left / width, 5),
                "y": round(sh.top / height, 5),
                "w": round(sh.width / width, 5),
                "h": round(sh.height / height, 5),
            }
            left, top, right, bottom = CONTENT_REGION
            covered = max(
                0.0, min(box["x"] + box["w"], right) - max(box["x"], left)
            ) * max(0.0, min(box["y"] + box["h"], bottom) - max(box["y"], top))
            area = box["w"] * box["h"]
            # Branding is what sits outside the content zone: logos, footers, edge
            # decor. A panel that covers the content zone is a frame the new content
            # is meant to sit on, so colliding with it is not a defect.
            if area < 0.85 and covered < 0.5 * area:
                reserved.append(box)
        slots = []
        for item in text_shapes:
            role = "title" if title and item["id"] == title["id"] else "body"
            slots.append(
                {
                    "role": role,
                    "box": item["box"],
                    "style": item.get("style") or {},
                    "length": len(item["text"]),
                }
            )
        # Порядок чтения: сверху вниз, слева направо — как человек смотрит слайд.
        slots.sort(key=lambda s: (s["role"] != "title", s["box"]["y"], s["box"]["x"]))
        patterns.append(
            {
                "slots": slots,
                "background": background["color"],
                "background_kind": background["kind"],
                "reserved": reserved,
                "decoration_area": round(decoration_area, 5),
                "image_cover": round(min(1.0, image_cover), 4),
                "decoration_count": decoration_count,
                "index": index,
                "layout_index": layouts.index(slide.slide_layout)
                if slide.slide_layout in layouts
                else 0,
                "layout_name": slide.slide_layout.name,
                "title_box": title["box"] if title else None,
                "shapes": shapes,
                "text_slots": len(text_shapes),
            }
        )
    geometry = derive_geometry(patterns)
    for layout in layouts:
        scan(layout.shapes)
    for master in deck.slide_masters:
        scan(master.shapes)
    return {
        "name": Path(name).stem,
        "width": width,
        "height": height,
        "tokens": {
            "fonts": [f for f, _ in fonts.most_common()],
            "font_sizes": sorted(sizes),
            "colors": [c for c, _ in colors.most_common()],
            "theme": theme,
        },
        "parser": PARSER_VERSION,
        "geometry": geometry,
        # Экспорт должен сохранять ровно то же, что учёл аудит.
        "branding": sorted(branding),
        "layouts": [
            {"index": i, "name": layout.name} for i, layout in enumerate(layouts)
        ],
        "patterns": patterns,
    }


def parse_content(data: bytes, name: str):
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        text = "\n".join(
            p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages
        )
    elif suffix == ".pptx":
        check_zip(data)
        text = "\n".join(
            s.text
            for slide in Presentation(io.BytesIO(data)).slides
            for s in slide.shapes
            if s.has_text_frame
        )
    elif suffix == ".docx":
        check_zip(data)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = etree.fromstring(
                z.read("word/document.xml"),
                etree.XMLParser(resolve_entities=False, no_network=True),
            )
            text = "\n".join(
                root.xpath("//*[local-name()='p']//*[local-name()='t']/text()")
            )
    elif suffix in (".txt", ".md", ".csv", ".json"):
        text = data.decode("utf-8-sig")
        if suffix == ".json":
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        if suffix == ".csv":
            text = "\n".join(" | ".join(row) for row in csv.reader(io.StringIO(text)))
    else:
        raise ValueError("Supported content: txt, md, csv, json, pdf, docx, pptx")
    if not text.strip():
        raise ValueError("No extractable text; scanned PDFs require OCR before upload")
    if len(text) > 100000:
        raise ValueError("Content exceeds 100000 characters; split the document")
    return text
