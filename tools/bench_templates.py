"""Прогнать вёрстку по шаблонам без обращения к модели.

На финале шаблон будет незнакомый, поэтому проверять надо не один файл, а
устойчивость: сколько времени занимает разбор и сборка, сколько находок у
аудита, используются ли карточные сетки шаблона, остаются ли слайды из
редактируемых объектов. План колоды фиксированный — значит, различия в отчёте
объясняются шаблоном, а не капризом модели.

Метрики качества считаются по реально записанному PPTX, а не по модели вёрстки:
в файл попадает то, что увидит зритель, включая подписи внутри диаграмм.

    python tools/bench_templates.py templates                  # отчёт в консоль
    python tools/bench_templates.py templates --render out/    # ещё pptx, pdf и PNG
    python tools/bench_templates.py templates --sheets out/    # и контакт-листы 3xN

Регрессионный прогон — план на 12 слайдов со всеми видами визуализаций
(tools/regress_outline.json), числа сверяются с исходным материалом:

    python tools/bench_templates.py <папка> \\
        --outline tools/regress_outline.json \\
        --source samples/source/материал-инициатива.md \\
        --render out/ --sheets out/

Шаблоны для регресса в репозиторий не коммитятся (файлы организаторов). На
машинах команды они лежат рядом с проектом:

    ../backend-audit/Датасет/                 три шаблона кейса: VK Tech,
                                              VK WorkSpace, VK Education
    ../backend-audit/Презентация/ЛЦТ2026 Шаблон презентации.pptx
                                              «незнакомый» шаблон

Можно передать сразу папки и отдельные файлы:

    python tools/bench_templates.py ../backend-audit/Датасет \\
        "../backend-audit/Презентация/ЛЦТ2026 Шаблон презентации.pptx" \\
        --outline tools/regress_outline.json --render out/ --sheets out/

В CI шаблонов кейса нет, там регресс идёт на синтетических шаблонах из
tools/make_fixture_templates.py. Подробности — docs/regression.md.
"""

import argparse
import collections
import json
import math
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from designer.audit import audit  # noqa: E402
from designer.exporting import (  # noqa: E402
    convert_pdf,
    export_pptx,
    render_slides,
    verify_pptx,
)
from designer.layout import compose  # noqa: E402
from designer.models import Outline  # noqa: E402
from designer.parsing import parse_template  # noqa: E402

DEFAULT_OUTLINE = Path(__file__).with_name("bench_outline.json")

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
SAFE_XML = etree.XMLParser(resolve_entities=False, no_network=True)

# Контакт-лист: миниатюры в три колонки, как колоду смотрят глазами.
SHEET_COLUMNS = 3
SHEET_TILE_WIDTH = 480
SHEET_GAP = 12


def discover(paths):
    """Шаблоны из папок и отдельных файлов — в стабильном порядке, без повторов."""
    found = []
    for path in paths:
        if path.is_dir():
            found.extend(sorted(path.glob("*.pptx")))
        elif path.suffix.lower() == ".pptx" and path.is_file():
            found.append(path)
        else:
            print(f"пропущено, это не .pptx и не папка: {path}")
    unique = []
    for path in found:
        if path.resolve() not in {p.resolve() for p in unique}:
            unique.append(path)
    return unique


def _xml(archive, name):
    return etree.fromstring(archive.read(name), SAFE_XML)


def _relations(archive, part):
    """Куда ссылается часть пакета: rId → путь внутри архива."""
    folder, file = part.rsplit("/", 1)
    rels = f"{folder}/_rels/{file}.rels"
    if rels not in archive.namelist():
        return {}
    result = {}
    for rel in _xml(archive, rels).findall("rel:Relationship", NS):
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        parts = [*folder.split("/"), *target.split("/")]
        stack = []
        for piece in parts:
            if piece == "..":
                stack.pop()
            elif piece and piece != ".":
                stack.append(piece)
        result[rel.get("Id")] = "/".join(stack)
    return result


def _smallest(current, size, where):
    if current is None or size < current[0]:
        return (size, where)
    return current


def inspect_pptx(path: Path):
    """Что на самом деле записано в файл: кегли, гарнитуры, диаграммы.

    Кегль в OOXML — в сотых долях пункта. Учитываются только явно заданные
    размеры у фрагментов с текстом: унаследованный кегль колонтитулов шаблона
    без полного разбора цепочки стилей честно не посчитать, поэтому такие
    фрагменты считаются отдельно.
    """
    with zipfile.ZipFile(path) as archive:
        presentation = "ppt/presentation.xml"
        root = _xml(archive, presentation)
        slide_height = int(root.find("p:sldSz", NS).get("cy"))
        rels = _relations(archive, presentation)
        order = [
            rels[item.get(f"{{{NS['r']}}}id")]
            for item in root.findall("p:sldIdLst/p:sldId", NS)
        ]
        smallest = None
        implicit = 0
        fonts = set()
        charts = []
        for number, part in enumerate(order, 1):
            slide = _xml(archive, part)
            for run in slide.iter(f"{{{NS['a']}}}r", f"{{{NS['a']}}}fld"):
                text = run.find("a:t", NS)
                if text is None or not (text.text or "").strip():
                    continue
                props = run.find("a:rPr", NS)
                size = props.get("sz") if props is not None else None
                if size is None:
                    paragraph = run.getparent()
                    default = paragraph.find("a:pPr/a:defRPr", NS)
                    size = default.get("sz") if default is not None else None
                if size is None:
                    implicit += 1
                    continue
                shape = run
                while shape is not None and shape.tag != f"{{{NS['p']}}}sp":
                    shape = shape.getparent()
                name = ""
                if shape is not None:
                    props_nv = shape.find("p:nvSpPr/p:cNvPr", NS)
                    name = props_nv.get("name", "") if props_nv is not None else ""
                smallest = _smallest(
                    smallest, int(size) / 100, f"слайд {number}, «{name}»"
                )
            for latin in slide.iter(f"{{{NS['a']}}}latin"):
                if latin.get("typeface"):
                    fonts.add(latin.get("typeface"))
            slide_rels = _relations(archive, part)
            for frame in slide.iter(f"{{{NS['p']}}}graphicFrame"):
                reference = frame.find(".//c:chart", NS)
                if reference is None:
                    continue
                chart_part = slide_rels.get(reference.get(f"{{{NS['r']}}}id"))
                extent = frame.find("p:xfrm/a:ext", NS)
                share = int(extent.get("cy")) / slide_height if extent is not None else None
                chart = _xml(archive, chart_part) if chart_part else None
                charts.append(_inspect_chart(chart, number, share))
                if chart is not None:
                    for element in chart.iter(f"{{{NS['a']}}}defRPr", f"{{{NS['a']}}}rPr"):
                        if element.get("sz"):
                            smallest = _smallest(
                                smallest,
                                int(element.get("sz")) / 100,
                                f"слайд {number}, диаграмма",
                            )
    return {
        "min_font": smallest[0] if smallest else None,
        "min_font_where": smallest[1] if smallest else None,
        "implicit_size_runs": implicit,
        "fonts": sorted(fonts),
        "charts": charts,
        "charts_without_legend": sum(1 for c in charts if not c["legend"]),
        "charts_without_axis_titles": sum(1 for c in charts if not c["axis_titles"]),
        "charts_without_value_labels": sum(1 for c in charts if not c["value_labels"]),
        "chart_height_shares": [c["height_share"] for c in charts],
    }


def _inspect_chart(chart, slide_number, share):
    """Легенда, подписи осей и значений одной нативной диаграммы.

    «Подписи осей» — заголовок хотя бы у одной оси (у нас это единица
    измерения на оси значений). «Подписи значений» — c:showVal=1 у ряда или у
    всей диаграммы: без них короткий столбец рядом с длинным не прочитать.
    """
    if chart is None:
        return {
            "slide": slide_number,
            "height_share": round(share, 3) if share is not None else None,
            "legend": False,
            "axis_titles": False,
            "value_labels": False,
        }
    axes = chart.findall(".//c:plotArea/*", NS)
    titled = any(
        axis.find("c:title", NS) is not None
        for axis in axes
        if etree.QName(axis).localname in ("valAx", "catAx", "dateAx", "serAx")
    )
    labels = any(
        flag.get("val", "1") in ("1", "true")
        for flag in chart.findall(".//c:dLbls/c:showVal", NS)
    )
    return {
        "slide": slide_number,
        "height_share": round(share, 3) if share is not None else None,
        "legend": chart.find("c:chart/c:legend", NS) is not None,
        "axis_titles": titled,
        "value_labels": labels,
    }


def contact_sheet(images, target: Path):
    """Склеить слайды колоды в один лист: три колонки, номер в углу миниатюры."""
    import pymupdf

    first = pymupdf.Pixmap(images[0])
    tile_height = SHEET_TILE_WIDTH * first.height / first.width
    rows = math.ceil(len(images) / SHEET_COLUMNS)
    width = SHEET_COLUMNS * SHEET_TILE_WIDTH + (SHEET_COLUMNS + 1) * SHEET_GAP
    height = rows * tile_height + (rows + 1) * SHEET_GAP
    document = pymupdf.open()
    page = document.new_page(width=width, height=height)
    page.draw_rect(page.rect, color=None, fill=(0.91, 0.92, 0.94))
    for index, image in enumerate(images):
        column, row = index % SHEET_COLUMNS, index // SHEET_COLUMNS
        left = SHEET_GAP + column * (SHEET_TILE_WIDTH + SHEET_GAP)
        top = SHEET_GAP + row * (tile_height + SHEET_GAP)
        tile = pymupdf.Rect(left, top, left + SHEET_TILE_WIDTH, top + tile_height)
        page.insert_image(tile, stream=image, keep_proportion=True)
        page.draw_rect(tile, color=(0.75, 0.77, 0.8), width=0.6)
        badge = pymupdf.Rect(left, top, left + 26, top + 18)
        page.draw_rect(badge, color=None, fill=(0.1, 0.1, 0.12))
        page.insert_text(
            (left + 5, top + 13), str(index + 1), fontsize=11, color=(1, 1, 1)
        )
    target.write_bytes(page.get_pixmap(dpi=72).tobytes("png"))
    document.close()


def deck_name(path: Path, variant):
    return f"{path.stem[:18].strip().replace(' ', '_')}_{variant}"


def run(templates, plan, sources, variants, render: Path | None, sheets: Path | None):
    rows = []
    scratch = tempfile.TemporaryDirectory()
    for path in templates:
        started = time.monotonic()
        try:
            template = parse_template(path.read_bytes(), path.name)
        except Exception as error:  # noqa: BLE001 - отчёт важнее стектрейса
            print(f"{path.name:44} разбор не удался: {error}")
            rows.append({"template": path.name, "error": str(error)})
            continue
        parsed = time.monotonic() - started
        for variant in variants:
            begun = time.monotonic()
            deck = compose(Outline.model_validate(plan).model_dump(), template, variant)
            report = audit(deck, template, sources)
            codes = collections.Counter(i["code"] for i in report["issues"])
            errors = sum(1 for i in report["issues"] if i["severity"] == "error")
            cards = sum(
                1
                for slide in deck["slides"]
                if any(e["id"].startswith("card_") for e in slide["elements"])
            )
            composed = time.monotonic() - begun
            # Метрики снимаются с записанного файла, поэтому экспорт нужен
            # всегда; без --render он уходит во временную папку.
            folder = render or Path(scratch.name)
            folder.mkdir(parents=True, exist_ok=True)
            name = deck_name(path, variant)
            pptx = folder / f"{name}.pptx"
            export_pptx(path, template, deck, pptx)
            native = verify_pptx(pptx, len(deck["slides"]))
            written = inspect_pptx(pptx)
            if render is not None:
                pdf = folder / f"{name}.pdf"
                convert_pdf(pptx, pdf)
                images = render_slides(pdf)
                for number, image in enumerate(images, 1):
                    (folder / f"{name}_{number}.png").write_bytes(image)
                if sheets is not None and images:
                    sheets.mkdir(parents=True, exist_ok=True)
                    contact_sheet(images, sheets / f"{name}_sheet.png")
            rows.append(
                {
                    "template": path.name,
                    "variant": variant,
                    "slides": len(deck["slides"]),
                    "parse_seconds": round(parsed, 2),
                    "compose_seconds": round(composed, 2),
                    "patterns": len(template["patterns"]),
                    "card_slides": cards,
                    "errors": errors,
                    "warnings": dict(codes),
                    "native_objects": native.get("native_objects"),
                    "raster_slides": native.get("raster_slides"),
                    **written,
                }
            )
            print_row(rows[-1])
    scratch.cleanup()
    return rows


COLUMNS = [
    ("шаблон", 22),
    ("вариант", 8),
    ("ошиб", 4),
    ("предупр", 7),
    ("карт", 4),
    ("мин.кегль", 9),
    ("шрифты", 26),
    ("диагр", 5),
    ("без легенды", 11),
    ("без осей", 8),
    ("без значений", 12),
    ("высота диагр", 14),
]


def cells(row):
    shares = ", ".join(f"{s:.2f}" for s in row["chart_height_shares"] if s is not None)
    return [
        Path(row["template"]).stem,
        row["variant"],
        str(row["errors"]),
        str(sum(row["warnings"].values())),
        str(row["card_slides"]),
        "—" if row["min_font"] is None else f"{row['min_font']:g}",
        ", ".join(row["fonts"]) or "—",
        str(len(row["charts"])),
        str(row["charts_without_legend"]),
        str(row["charts_without_axis_titles"]),
        str(row["charts_without_value_labels"]),
        shares or "—",
    ]


def print_header():
    print(" | ".join(title.ljust(width) for title, width in COLUMNS))
    print("-+-".join("-" * width for _, width in COLUMNS))


def print_row(row):
    values = cells(row)
    print(
        " | ".join(
            (value if len(value) <= width else value[: width - 1] + "…").ljust(width)
            for value, (_, width) in zip(values, COLUMNS)
        )
    )


def markdown(rows):
    """Та же таблица для сводки CI и для документации."""
    lines = [
        "| " + " | ".join(title for title, _ in COLUMNS) + " |",
        "|" + "|".join("---" for _ in COLUMNS) + "|",
    ]
    for row in rows:
        if row.get("error"):
            lines.append(f"| {row['template']} | разбор не удался: {row['error']} |")
            continue
        lines.append("| " + " | ".join(v.replace("|", "\\|") for v in cells(row)) + " |")
    details = [
        f"- **{Path(r['template']).stem} / {r['variant']}**: мин. кегль "
        f"{r['min_font']:g} ({r['min_font_where']}); предупреждения: "
        + (", ".join(f"{k} × {v}" for k, v in sorted(r["warnings"].items())) or "нет")
        for r in rows
        if not r.get("error") and r["min_font"] is not None
    ]
    return "\n".join(lines) + "\n\n" + "\n".join(details) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "paths", type=Path, nargs="+", help="папки с .pptx и/или отдельные файлы"
    )
    parser.add_argument(
        "--outline",
        type=Path,
        default=DEFAULT_OUTLINE,
        help="план колоды (JSON по схеме Outline), по умолчанию tools/bench_outline.json",
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="материал, с которым аудит сверяет числа; по умолчанию — текст самого плана",
    )
    parser.add_argument("--render", type=Path, help="куда класть pptx, pdf и PNG слайдов")
    parser.add_argument(
        "--sheets",
        type=Path,
        help="куда класть контакт-листы 3xN; без --render слайды рендерятся туда же",
    )
    parser.add_argument(
        "--variants",
        default="classic,split,focus",
        help="какие варианты вёрстки проверять",
    )
    parser.add_argument("--json", type=Path, help="куда записать отчёт")
    parser.add_argument("--markdown", type=Path, help="куда записать таблицу в Markdown")
    args = parser.parse_args()

    templates = discover(args.paths)
    if not templates:
        print("шаблонов не найдено")
        return 1
    plan_text = args.outline.read_text(encoding="utf-8")
    plan = json.loads(plan_text)
    source_text = args.source.read_text(encoding="utf-8") if args.source else plan_text
    sources = [{"id": "brief", "text": source_text}]
    render = args.render or args.sheets
    print(f"шаблонов: {len(templates)}, план: {args.outline.name}, слайдов: {len(plan['slides'])}")
    print_header()
    rows = run(
        templates, plan, sources, args.variants.split(","), render, args.sheets
    )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print("отчёт:", args.json)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown(rows), encoding="utf-8")
        print("таблица:", args.markdown)
    broken = [r for r in rows if r.get("error") or r.get("errors")]
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
