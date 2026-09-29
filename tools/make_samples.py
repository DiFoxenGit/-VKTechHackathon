"""Collect a demo: arbitrary templates, source, three layouts, full audits and all exports."""

import argparse
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"
BRIEF = ("Защита инициативы перед руководством: предложить сервис автоматической "
         "вёрстки презентаций и показать результаты из материалов. Не добавлять "
         "сроки, ресурсы или решения, которых нет в источнике.")
VARIANTS = {"classic", "split", "focus"}


def headers(request):
    if key := os.getenv("DESIGNER_API_KEY"):
        request.add_header("Authorization", "Bearer " + key)


def call(base, path, payload=None, method=None, raw=False):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    headers(request)
    with urllib.request.urlopen(request, timeout=300) as response:
        body = response.read()
    return body if raw else json.loads(body)


def upload(base, path, field_file, content_type):
    boundary = "----designer-samples"
    head = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{field_file.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n").encode()
    body = head + field_file.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(base.rstrip("/") + path, data=body, method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    headers(request)
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read())


def slug(name):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:64]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def file_info(path):
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def collect(base, template_paths, source, output, brief=BRIEF, slide_count=12, visual=False, require_chart=False):
    if not template_paths:
        raise ValueError("No templates supplied; use --template or --template-dir")
    for path in [source, *template_paths]:
        if not path.is_file():
            raise ValueError(f"Missing input: {path}")
    output.mkdir(parents=True, exist_ok=True)
    evidence = output / "evidence"
    evidence.mkdir(exist_ok=True)
    (evidence / source.name).write_bytes(source.read_bytes())
    run = {"status": "running", "brief": brief, "requested_slides": slide_count,
           "source": file_info(source), "templates": [], "visual_audit_requested": visual}
    summary = []
    try:
        pack = upload(base, "/api/v1/content-packs", source, "application/octet-stream")
        for number, path in enumerate(template_paths, 1):
            template = upload(base, "/api/v1/templates", path, "application/vnd.openxmlformats-officedocument.presentationml.presentation")
            name = f"{number}_{slug(path.stem)}"
            run["templates"].append({**file_info(path), "id": template["id"]})
            started = time.monotonic()
            job = call(base, "/api/v1/generations", {
                "template_id": template["id"], "brief": brief, "purpose": "initiative",
                "language": "ru", "slide_count": slide_count,
                "content_pack_ids": [pack["id"]], "contextual_audit": True,
            })
            while True:
                state = call(base, f"/api/v1/jobs/{job['id']}")
                if state["status"] in {"completed", "failed"}:
                    break
                if time.monotonic() - started > 330:
                    raise RuntimeError(f"Generation did not finish within 330 seconds: {job['id']}")
                time.sleep(3)
            write_json(evidence / f"{name}__job.json", state)
            if state["status"] != "completed":
                raise RuntimeError(f"Generation failed: {state.get('error')}")
            decks = [call(base, f"/api/v1/presentations/{pid}") for pid in state["presentation_ids"]]
            if len(decks) != 3 or {deck["variant"] for deck in decks} != VARIANTS:
                raise RuntimeError("Expected exactly classic, split and focus")
            rows = []
            for deck in decks:
                variant, identifier = deck["variant"], deck["id"]
                report = deck.get("audit", {})
                if report.get("contextual", {}).get("status") != "completed":
                    raise RuntimeError("Content audit did not complete")
                if visual:
                    report = call(base, f"/api/v1/presentations/{identifier}/audit?visual=true", method="POST")
                write_json(evidence / f"{name}__{variant}__audit.json", report)
                write_json(evidence / f"{name}__{variant}__presentation.json", deck)
                files = {}
                for fmt in ("pptx", "pdf", "html"):
                    data = call(base, f"/api/v1/presentations/{identifier}/export/{fmt}?revision={deck['revision']}", raw=True)
                    if not data:
                        raise RuntimeError(f"Empty {fmt} export")
                    target = output / f"{name}__{variant}.{fmt}"
                    target.write_bytes(data)
                    files[fmt] = file_info(target)
                issues = report.get("issues", [])
                warnings = {}
                for finding in issues:
                    if finding["severity"] != "error":
                        warnings[finding["code"]] = warnings.get(finding["code"], 0) + 1
                rows.append({
                    "template": template["name"], "variant": variant,
                    "slides": len(deck["deck"]["slides"]), "errors": sum(i["severity"] == "error" for i in issues),
                    "warnings": warnings, "contextual_audit": "completed", "visual_audit": "completed" if visual else "not_run",
                    "workflow": deck.get("workflow"), "generation": deck.get("generation"),
                    "export_check": deck.get("export_check"), "files": files,
                    "server_seconds": state.get("elapsed_seconds"), "job_warnings": state.get("warnings", []),
                })
            elapsed = round(time.monotonic() - started, 1)
            for row in rows:
                row.update(seconds=elapsed, within_five_minutes=elapsed <= 300)
            summary.extend(rows)
            print(f"{path.name}: 3 variants, {elapsed}s including PPTX/PDF/HTML, {sum(r['errors'] for r in rows)} errors")
        run["status"] = "completed"
        run["missing_native_chart"] = require_chart and not any((r.get("export_check") or {}).get("charts") for r in summary)
        run["quality"] = "needs_review" if run["missing_native_chart"] or any(r["errors"] or not r["within_five_minutes"] for r in summary) else "no_reported_errors"
    except Exception as exc:
        run.update(status="failed", error=str(exc))
        raise
    finally:
        write_json(output / "report.json", summary)
        write_json(output / "run.json", run)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    parser.add_argument("--template", type=Path, action="append", default=[])
    parser.add_argument("--template-dir", type=Path, default=ROOT / "templates")
    parser.add_argument("--source", type=Path, default=OUT / "source" / "материал-инициатива.md")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--brief", default=BRIEF)
    parser.add_argument("--slide-count", type=int, default=12, choices=range(1, 31), metavar="1..30")
    parser.add_argument("--visual-audit", action="store_true")
    parser.add_argument("--require-chart", action="store_true", help="Fail if no exported native chart is recorded")
    args = parser.parse_args()
    templates = args.template or sorted(args.template_dir.glob("*.pptx"))
    rows = collect(args.base, templates, args.source, args.output, args.brief, args.slide_count, args.visual_audit, args.require_chart)
    if args.require_chart and not any((row.get("export_check") or {}).get("charts") for row in rows):
        raise SystemExit("Files saved; no native chart found. Inspect the source and generated outline.")
    if any(row["errors"] or not row["within_five_minutes"] for row in rows):
        raise SystemExit("Files saved; the run has audit errors or exceeds five minutes. Inspect report.json.")


if __name__ == "__main__":
    main()
