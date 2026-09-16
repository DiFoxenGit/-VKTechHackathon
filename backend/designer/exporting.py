"""Native PowerPoint export; LibreOffice renders the same deck to PDF/HTML."""

import copy
import html
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Pt

from .visuals import DIAGRAMS
from .parsing import (
    background_color,
    best_text_color,
    is_footer_placeholder,
    preserved_shape,
)


def _font(font, name, size, color, bold=False):
    font.name, font.size, font.bold = name, Pt(size), bold
    font.color.rgb = RGBColor.from_string(color)
    for tag in ("a:ea", "a:cs"):
        element = font._rPr.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            font._rPr.append(element)
        element.set("typeface", name)


def _clone_slide(deck, source):
    target = deck.slides.add_slide(source.slide_layout)
    for shape in list(target.shapes):
        shape._element.getparent().remove(shape._element)
    mapping = {}
    for rel in source.part.rels.values():
        if rel.reltype.endswith(("/slideLayout", "/notesSlide")):
            continue
        mapping[rel.rId] = target.part.relate_to(
            rel.target_ref if rel.is_external else rel.target_part,
            rel.reltype,
            is_external=rel.is_external,
        )
    if source._element.cSld.bg is not None:
        target._element.cSld.insert(0, copy.deepcopy(source._element.cSld.bg))
    for shape in source.shapes:
        # Keep artwork and footer/page-number placeholders; remove sample content.
        # The audit reads the same predicate to know what is on the finished slide.
        if not preserved_shape(shape, deck.slide_width, deck.slide_height):
            continue
        element = copy.deepcopy(shape._element)
        is_footer = is_footer_placeholder(shape)
        # Groups may contain sample text; do not copy their text into the result.
        for text in element.xpath(".//a:t"):
            if not is_footer:
                text.text = ""
        for node in element.iter():
            for key, value in list(node.attrib.items()):
                if (
                    key.startswith(
                        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
                    )
                    and value in mapping
                ):
                    node.set(key, mapping[value])
        target.shapes._spTree.insert_element_before(element, "p:extLst")
    return target


def diagram_style(font, accent, background, text_color, palette):
    """Кисти для библиотеки диаграмм: заливка, подпись внутри фигуры и под ней."""
    on_accent = best_text_color(accent, palette)

    def paint(shape, role):
        shape.line.fill.background()
        if role == "hole":
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor.from_string(background)
        elif role == "outline":
            shape.fill.background()
            shape.line.fill.solid()
            shape.line.fill.fore_color.rgb = RGBColor.from_string(accent)
            shape.line.width = Pt(1.25)
        else:
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor.from_string(accent)

    def label(shape, text, outline=False):
        shape.text_frame.word_wrap = True
        shape.text = text
        # Ширина фигуры известна: подбираем кегль, чтобы слово не рвалось по слогам.
        longest = max((len(word) for word in text.split()), default=1)
        usable = shape.width / 12700 * 0.82
        size = max(8.0, min(13.0, usable / (longest * 0.55)))
        colour = text_color if outline else on_accent
        for paragraph in shape.text_frame.paragraphs:
            paragraph.alignment = PP_ALIGN.CENTER
            _font(paragraph.font, font, size, colour)
            for run in paragraph.runs:
                _font(run.font, font, size, colour)

    def caption(shapes, box, text):
        left, top, width, height = box
        frame = shapes.add_textbox(left, top, width, max(height, Pt(12)))
        frame.text_frame.word_wrap = True
        frame.text_frame.text = text
        for paragraph in frame.text_frame.paragraphs:
            paragraph.alignment = PP_ALIGN.CENTER
            _font(paragraph.font, font, 12, text_color)
            for run in paragraph.runs:
                _font(run.font, font, 12, text_color)

    return {"paint": paint, "label": label, "caption": caption}


def export_pptx(template_path: Path, template, deck_data, output: Path):
    deck = Presentation(template_path)
    originals = list(deck.slides)
    original_ids = list(deck.slides._sldIdLst)
    palette = template["tokens"]["colors"]
    for slide_data in deck_data["slides"]:
        slide = _clone_slide(deck, originals[slide_data["pattern_index"]])
        background = slide_data.get("background") or background_color(
            slide, template["tokens"]["theme"]
        )
        # Layout already resolved the readable color; keep both layers in agreement.
        text_color = next(
            (
                e["color"]
                for e in slide_data["elements"]
                if e.get("color") and e["color"] != "auto"
            ),
            best_text_color(background, palette),
        )
        for element in slide_data["elements"]:
            x, y, w, h = [Pt(v) for v in element["box"]]
            kind = element["kind"]
            font, accent = element["font"], element["accent"]
            if kind == "text":
                shape = slide.shapes.add_textbox(x, y, w, h)
                shape.name = element["id"]
                frame = shape.text_frame
                frame.word_wrap = True
                frame.margin_left = frame.margin_right = Pt(6)
                frame.margin_top = frame.margin_bottom = Pt(4)
                for j, line in enumerate(element["text"].splitlines()):
                    p = frame.paragraphs[0] if j == 0 else frame.add_paragraph()
                    p.text = line
                    p.space_after = Pt(3)
                    _font(
                        p.font,
                        font,
                        element["font_size"],
                        text_color,
                        element["role"] == "title",
                    )
                    for run in p.runs:
                        _font(
                            run.font,
                            font,
                            element["font_size"],
                            text_color,
                            element["role"] == "title",
                        )
            elif kind in ("bar", "line"):
                visual = element["data"]
                data = CategoryChartData()
                data.categories = visual["categories"]
                for series in visual["series"]:
                    data.add_series(series["name"], series["values"])
                chart = slide.shapes.add_chart(
                    XL_CHART_TYPE.COLUMN_CLUSTERED
                    if kind == "bar"
                    else XL_CHART_TYPE.LINE,
                    x,
                    y,
                    w,
                    h,
                    data,
                ).chart
                chart.has_title = False
                chart.has_legend = True
                chart.legend.position = XL_LEGEND_POSITION.BOTTOM
                chart.legend.include_in_layout = False
                _font(chart.font, font, 12, text_color)
                for axis, label in (
                    (chart.value_axis, visual.get("unit", "")),
                    (chart.category_axis, "Категория"),
                ):
                    _font(axis.tick_labels.font, font, 11, text_color)
                    # An axis title is only truthful when the outline supplied a unit;
                    # a missing one is reported by the audit instead of invented here.
                    axis.has_title = bool(label)
                    if not label:
                        continue
                    axis.axis_title.text_frame.text = label
                    for p in axis.axis_title.text_frame.paragraphs:
                        _font(p.font, font, 11, text_color)
                for i, series in enumerate(chart.series):
                    color = template["tokens"]["theme"].get(f"accent{i + 1}", accent)
                    series.format.fill.solid()
                    series.format.fill.fore_color.rgb = RGBColor.from_string(color)
                    series.format.line.color.rgb = RGBColor.from_string(color)
            elif kind == "table":
                visual = element["data"]
                rows = [visual["columns"], *visual["rows"]]
                table = slide.shapes.add_table(
                    len(rows), len(rows[0]), x, y, w, h
                ).table
                for r, values in enumerate(rows):
                    for c, value in enumerate(values):
                        cell = table.cell(r, c)
                        cell.text = value
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = RGBColor.from_string(
                            accent if r == 0 else background
                        )
                        color = (
                            best_text_color(accent, palette) if r == 0 else text_color
                        )
                        for p in cell.text_frame.paragraphs:
                            _font(p.font, font, 13, color, r == 0)
            elif kind in DIAGRAMS:
                DIAGRAMS[kind](
                    slide.shapes,
                    (int(x), int(y), int(w), int(h)),
                    element["data"],
                    diagram_style(font, accent, background, text_color, palette),
                )
        slide.notes_slide.notes_text_frame.text = slide_data["content"]["notes"]
    for identifier in original_ids:
        deck.part.drop_rel(identifier.rId)
        deck.slides._sldIdLst.remove(identifier)
    deck.save(output)


def verify_pptx(path: Path, expected_slides: int):
    """Confirm the exported deck opens and carries editable objects.

    The brief rejects slides exported as one flat image, so the service proves the
    opposite on every export instead of asserting it in documentation.
    """
    report = {"opens": False, "slides": 0, "native_objects": 0, "raster_slides": []}
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Exported PPTX archive is corrupt")
    deck = Presentation(path)
    report["opens"] = True
    report["slides"] = len(deck.slides)
    for index, slide in enumerate(deck.slides):
        editable = 0
        pictures = 0
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text.strip():
                editable += 1
            elif shape.has_table or shape.has_chart:
                editable += 1
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                pictures += 1
            elif shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
                editable += 1
        report["native_objects"] += editable
        if not editable and pictures:
            report["raster_slides"].append(index)
    if report["slides"] != expected_slides:
        raise RuntimeError(
            f"Exported {report['slides']} slides, expected {expected_slides}"
        )
    if report["raster_slides"]:
        raise RuntimeError(
            "Slides exported without editable objects: "
            + ", ".join(str(i) for i in report["raster_slides"])
        )
    return report


def convert_pdf(pptx_path: Path, destination: Path):
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if not executable and mac.exists():
        executable = str(mac)
    if not executable:
        raise RuntimeError(
            "LibreOffice is required for PDF and faithful HTML export; use the backend Docker image"
        )
    with tempfile.TemporaryDirectory(prefix="designer-office-") as temp:
        temp = Path(temp)
        fontconfig = temp / "fonts.conf"
        font_dirs = [
            Path(__file__).parent / "assets/fonts",
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library/Fonts",
        ]
        fontconfig.write_text(
            '<?xml version="1.0"?><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
            + "".join(
                "<dir>" + html.escape(str(p.resolve())) + "</dir>"
                for p in font_dirs
                if p.exists()
            )
            + "<cachedir>"
            + str(temp / "font-cache")
            + "</cachedir></fontconfig>"
        )
        result = subprocess.run(
            [
                executable,
                "-env:UserInstallation=" + (temp / "profile").as_uri(),
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(temp),
                str(pptx_path.resolve()),
            ],
            capture_output=True,
            timeout=90,
            check=False,
            env={**os.environ, "FONTCONFIG_FILE": str(fontconfig)},
        )
        converted = temp / (pptx_path.stem + ".pdf")
        if result.returncode or not converted.exists():
            raise RuntimeError("LibreOffice failed to render presentation")
        shutil.copyfile(converted, destination)


def render_slides(pdf_path: Path, width=1280):
    """Слайды как PNG — то, что реально увидит зритель, а не наше представление."""
    import pymupdf

    pages = []
    with pymupdf.open(pdf_path) as document:
        for page in document:
            zoom = width / page.rect.width if page.rect.width else 1
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            pages.append(pixmap.tobytes("png"))
    return pages


def export_html(pdf_path: Path, destination: Path, title: str):
    import pymupdf

    with pymupdf.open(pdf_path) as pdf:
        pages = []
        for page in pdf:
            # Paths preserve exact appearance even if the browser lacks corporate fonts.
            svg = page.get_svg_image(text_as_path=True)
            pages.append('<section class="slide">' + svg + "</section>")
    destination.write_text(
        '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'
        + html.escape(title)
        + "</title><style>body{margin:0;background:#222}.slide{margin:24px auto;width:min(96vw,1280px);background:white}.slide svg{width:100%;height:auto;display:block}@media print{body{background:white}.slide{margin:0;width:100%;break-after:page}}</style>"
        + "".join(pages)
        + "</html>",
        encoding="utf-8",
    )
