"""Собрать эталонные колоды: один и тот же материал на каждом шаблоне.

Запускается против работающего сервиса и складывает результат в samples/:
по три варианта на шаблон плюс отчёт аудита и время генерации.

    python tools/make_samples.py http://158.160.183.219
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"
BRIEF = (
    "Защита инициативы перед руководством: предложить сервис автоматической "
    "вёрстки презентаций, показать эффект пилота в цифрах и попросить решение "
    "о запуске на всю компанию."
)


def call(base, path, payload=None, method=None, raw=False):
    url = base.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=300) as response:
        body = response.read()
    return body if raw else json.loads(body)


def upload(base, path, field_file: Path, content_type):
    boundary = "----designer-samples"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{field_file.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    body = head + field_file.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(base.rstrip("/") + path, data=body, method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read())


def slug(name):
    table = str.maketrans(" .,()", "_____")
    return name.translate(table).strip("_")[:40]


def main(base):
    OUT.mkdir(exist_ok=True)
    pack = upload(
        base,
        "/api/v1/content-packs",
        OUT / "source" / "материал-инициатива.md",
        "text/markdown",
    )
    print("материал загружен:", pack["id"], len(pack["text"]), "символов")
    templates = call(base, "/api/v1/templates")["items"]
    # На сервере остаются шаблоны, загруженные во время проверок интерфейса.
    # В эталоны идут только те, что лежат в templates/ репозитория.
    known = {path.stem for path in (ROOT / "templates").glob("*.pptx")}
    templates = [t for t in templates if Path(t["name"]).stem in known]
    print("шаблонов в наборе:", len(templates))
    summary = []
    for template in templates:
        name = slug(Path(template["name"]).stem)
        started = time.monotonic()
        job = call(
            base,
            "/api/v1/generations",
            {
                "template_id": template["id"],
                "brief": BRIEF,
                "purpose": "initiative",
                "language": "ru",
                "slide_count": 10,
                "content_pack_ids": [pack["id"]],
            },
        )
        while True:
            state = call(base, f"/api/v1/jobs/{job['id']}")
            if state["status"] in ("completed", "failed"):
                break
            time.sleep(3)
        if state["status"] == "failed":
            print("!", name, "провалилась:", state.get("error"))
            continue
        elapsed = time.monotonic() - started
        for identifier in state["presentation_ids"]:
            deck = call(base, f"/api/v1/presentations/{identifier}")
            variant = deck["variant"]
            for fmt in ("pptx", "pdf"):
                data = call(
                    base,
                    f"/api/v1/presentations/{identifier}/export/{fmt}"
                    f"?revision={deck['revision']}",
                    raw=True,
                )
                (OUT / f"{name}__{variant}.{fmt}").write_bytes(data)
            issues = deck.get("audit", {}).get("issues", [])
            codes = {}
            for item in issues:
                codes[item["code"]] = codes.get(item["code"], 0) + 1
            errors = sum(1 for i in issues if i["severity"] == "error")
            summary.append(
                {
                    "template": template["name"],
                    "variant": variant,
                    "slides": len(deck["deck"]["slides"]),
                    "seconds": round(elapsed, 1),
                    "errors": errors,
                    "warnings": codes,
                }
            )
            count = len(deck["deck"]["slides"])
            print(f"{name:32} {variant:8} слайдов {count:2} "
                  f"за {elapsed:5.1f} c | ошибок {errors} | {codes}")
    (OUT / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("отчёт:", OUT / "report.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")
