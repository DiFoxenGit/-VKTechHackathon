"""Прогнать вёрстку по папке шаблонов без обращения к модели.

На финале шаблон будет незнакомый, поэтому проверять надо не один файл, а
устойчивость: сколько времени занимает разбор и сборка, сколько находок у
аудита, используются ли карточные сетки шаблона, остаются ли слайды из
редактируемых объектов. План колоды фиксированный — значит, различия в отчёте
объясняются шаблоном, а не капризом модели.

    python tools/bench_templates.py templates            # отчёт в консоль
    python tools/bench_templates.py templates --render out/  # ещё и PNG слайдов
"""

import argparse
import collections
import json
import sys
import time
from pathlib import Path

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

SOURCES = [{"id": "brief", "text": Path(__file__).with_name("bench_outline.json").read_text(encoding="utf-8")}]
PLAN = json.loads(Path(__file__).with_name("bench_outline.json").read_text(encoding="utf-8"))


def run(folder: Path, variants, render: Path | None):
    rows = []
    for path in sorted(folder.glob("*.pptx")):
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
            deck = compose(Outline.model_validate(PLAN).model_dump(), template, variant)
            report = audit(deck, template, SOURCES)
            codes = collections.Counter(i["code"] for i in report["issues"])
            errors = sum(1 for i in report["issues"] if i["severity"] == "error")
            cards = sum(
                1
                for slide in deck["slides"]
                if any(e["id"].startswith("card_") for e in slide["elements"])
            )
            native = None
            if render is not None:
                render.mkdir(parents=True, exist_ok=True)
                name = f"{path.stem[:18].strip().replace(' ', '_')}_{variant}"
                pptx = render / f"{name}.pptx"
                export_pptx(path, template, deck, pptx)
                native = verify_pptx(pptx, len(deck["slides"]))
                pdf = render / f"{name}.pdf"
                convert_pdf(pptx, pdf)
                for number, image in enumerate(render_slides(pdf), 1):
                    (render / f"{name}_{number}.png").write_bytes(image)
            rows.append(
                {
                    "template": path.name,
                    "variant": variant,
                    "parse_seconds": round(parsed, 2),
                    "compose_seconds": round(time.monotonic() - begun, 2),
                    "patterns": len(template["patterns"]),
                    "card_slides": cards,
                    "errors": errors,
                    "warnings": dict(codes),
                    "native_objects": (native or {}).get("native_objects"),
                    "raster_slides": (native or {}).get("raster_slides"),
                }
            )
            print(
                f"{path.stem[:26]:28} {variant:8} разбор {parsed:5.2f} c | "
                f"вёрстка {rows[-1]['compose_seconds']:5.2f} c | карточных {cards} | "
                f"ошибок {errors} | {dict(codes)}"
            )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="папка с .pptx")
    parser.add_argument("--render", type=Path, help="куда класть pptx, pdf и PNG слайдов")
    parser.add_argument(
        "--variants",
        default="classic,split,focus",
        help="какие варианты вёрстки проверять",
    )
    parser.add_argument("--json", type=Path, help="куда записать отчёт")
    args = parser.parse_args()
    rows = run(args.folder, args.variants.split(","), args.render)
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print("отчёт:", args.json)
    broken = [r for r in rows if r.get("error") or r.get("errors")]
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
