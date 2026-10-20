"""One shared generation clock, actual Qwen telemetry, all variants and exports.

Uploads/pre-analysis precede the clock. Queueing, calls, retries and PPTX assembly
are inside it. PDF export is measured separately. Seven-type mode deliberately
uses deterministic analytics; only --live business may pass as Qwen acceptance.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time

import httpx

from acceptance_evidence import (EvidenceError, code_version, require, response_summary, safe_name, sanitized_inference,
                                 sha256, validate_inference, verify_business, verify_office_exports, verify_slide_evidence,
                                 verify_shared_jobs)
from business_reference import calculate

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "samples/business-acceptance/period-context-v1"
DATA = ROOT / "samples/business-acceptance/data-v1"
BRIEF = ("Подготовьте управленческий отчёт для коммерческого директора и руководителя продукта. "
         "Покажите чистую выручку, валовую прибыль, маржу, изменения к сравнительным периодам, "
         "план-факт, вклад продуктов и регионов, экономику каналов и возвраты. Разделите "
         "подтверждённые выводы и гипотезы о причинах. Предложите приоритеты, владельцев, сроки "
         "и критерии действий с учётом утверждённых бюджетных и кадровых ограничений. "
         "Все числа и периоды берите из проверенных фактов; не обещайте эффект инвестиций.")


def read(path):
    return json.loads(path.read_text(encoding="utf8"))


def business_inputs(version="baseline", period="default"):
    folder = EXT / version
    settings, conditions = read(EXT / "settings.json"), read(folder / "conditions.json")
    context = (folder / "context.txt").read_text(encoding="utf8")
    if period == "alternate":
        settings.update(current=["2026-07", "2026-09"], previous=["2026-04", "2026-06"],
                        year_ago=["2025-07", "2025-09"], history=["2025-01", "2026-09"])
        replacements = {"2026-04 — 2026-06": "2026-07 — 2026-09",
                        "июль — сентябрь 2026": "октябрь — декабрь 2026"}
        def updated(value):
            if isinstance(value, dict):
                return {key: updated(item) for key, item in value.items()}
            if isinstance(value, list):
                return [updated(item) for item in value]
            if isinstance(value, str):
                for before, after in replacements.items():
                    value = value.replace(before, after)
            return value
        context, conditions = updated(context), updated(conditions)
        conditions["reporting_period"]["value"] = settings["current"]
    expected = calculate(folder, {"q3": settings["current"], "q2": settings["previous"],
                                  "year_ago": settings["year_ago"]})
    return folder, settings, conditions, context, expected


async def run_scenario(args):
    output = args.output or ROOT / "output/live-qwen" / args.label
    output.mkdir(parents=True, exist_ok=True)
    report = {"scenario": args.scenario, "label": args.label, **code_version(ROOT),
              "environment": "local HTTP service", "service_url": args.url,
              "source_data_synthetic": True, "live_acceptance_requested": args.live,
              "model_content_generation": False,
              "image_generation_requested": args.images, "analysis_preflight_outside_clock": True,
              "image_generation_included_in_ready_time": False,
              "queue_model_retries_assembly_inside_clock": True, "pdf_conversion_outside_clock": True,
              "status": "running", "checks": [], "jobs": [], "runs": [], "sources": []}
    headers = {"Authorization": "Bearer " + os.environ["DESIGNER_API_KEY"]} if os.getenv("DESIGNER_API_KEY") else {}
    def persist():
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    async with httpx.AsyncClient(base_url=args.url.rstrip("/"), headers=headers, timeout=args.timeout) as client:
        async def req(method, path, **kw):
            result = await client.request(method, path, **kw)
            result.raise_for_status()
            return result
        async def upload(path, raw=None):
            raw = path.read_bytes() if raw is None else raw
            pack = (await req("POST", "/content-packs", files={"file": (path.name, raw)})).json()
            require((await req("GET", f'/content-packs/{pack["id"]}/source')).content == raw, "Source round-trip failed")
            report["sources"].append({"name": path.name, "sha256": sha256(raw), "pack_id": pack["id"]})
            return pack
        try:
            templates = list({t.get("sha256", t["id"]): t for t in
                              (await req("GET", "/templates")).json()["items"]}.values())
            if args.template_id:
                templates = [t for t in templates if t["id"] in args.template_id]
                require(len(templates) == len(set(args.template_id)), "Requested template missing")
            if args.one_template and templates:
                templates = [next((t for t in templates if "vk tech" in t["name"].lower()), templates[0])]
            require(len(templates) == (1 if args.one_template else 3), "Expected exactly three original templates (or --one-template)")
            expected = settings = None
            if args.scenario == "business":
                folder, settings, conditions, context, expected = business_inputs(args.version, args.period)
                report.update(version=args.version, periods=settings)
                packs = []
                for name in ("sales.csv", "plan.csv", "products.csv", "regions.csv", "context.txt", "content-pack.zip"):
                    path = (DATA if name in {"products.csv", "regions.csv", "content-pack.zip"} else folder) / name
                    packs.append(await upload(path, context.encode("utf8") if name == "context.txt" else None))
                payload = {"brief": BRIEF, "slide_count": 12, "content_pack_ids": [p["id"] for p in packs],
                           "generate_images": args.images, "model_content_generation": args.live,
                           "business_settings": settings, "business_conditions": conditions,
                           "business_context_id": packs[-2]["id"]}
                preflight = (await req("POST", "/analysis", json={**payload, "template_id": templates[0]["id"]})).json()
                require(preflight.get("business") and len(preflight["items"]) == 12, "Business preflight failed")
            else:
                require(not args.live, "Seven-type matrix is intentionally deterministic")
                folder = ROOT / "samples/analytics/datasets"
                packs, selections, goals, expected_dataset_ids, expected_contracts = [], {}, {}, set(), {}
                for spec in sorted(folder.glob("*.request.json")):
                    stem = spec.name.removesuffix(".request.json")
                    path = next(p for p in folder.glob(stem + ".*") if p.suffix in {".csv", ".md"})
                    pack = await upload(path)
                    packs.append(pack)
                    selection, dataset = read(spec), pack["datasets"][0]["dataset_id"]
                    expected_dataset_ids.add(dataset)
                    preview = (await req("POST", f'/content-packs/{pack["id"]}/analysis',
                        json={"goal": selection["goal"], "requests": {dataset: selection}})).json()
                    require(preview["analysis_results"][0] == read(folder / (stem + ".result.json")), "Contract mismatch: " + stem)
                    expected_contracts[dataset] = preview["analysis_results"][0]
                    selections[dataset], goals[pack["id"]] = selection, selection["goal"]
                    report["checks"].append({"dataset": stem, "dataset_id": dataset, "exact_contract_match": True})
                require(len(packs) == 7, "Expected seven input datasets")
                payload = {"brief": "Семь видов данных: динамика, категории, доли, распределение, справочник, пропуски, таблица в тексте.",
                           "slide_count": 30, "narrative": False, "model_content_generation": False,
                           "content_pack_ids": [p["id"] for p in packs], "analysis_requests": selections,
                           "analysis_goals": goals, "generate_images": args.images}
            persist()
            started = time.monotonic()
            batch = (await req('POST', '/generation-batches', json={'requests': [
                {**payload, 'template_id': template['id']} for template in templates]})).json()
            report['batch_id'] = batch['id']
            async def generate(template, job):
                while job["status"] not in {"completed", "failed"} and time.monotonic() - started < args.timeout:
                    await asyncio.sleep(.25)
                    job = (await req("GET", "/jobs/" + job["id"])).json()
                raw_trace = job.get("inference", {})
                summary = {"template": template["name"], "template_sha256": template.get("sha256"),
                           "job_id": job["id"], "status": job["status"],
                           "ready_since_shared_start_seconds": round(time.monotonic() - started, 3),
                           "presentation_ids": job.get("presentation_ids", [])}
                try:
                    summary["inference"] = validate_inference(raw_trace, live=args.live,
                        provider=args.provider if args.live else None, model=args.model if args.live else None)
                except ValueError as exc:
                    # Retain safe failure evidence without provider bodies, prompts or headers.
                    summary["inference"] = sanitized_inference(raw_trace)
                    if isinstance(exc, EvidenceError):
                        summary["check_failure"] = str(exc)
                    report["jobs"].append(summary)
                    persist()
                    raise
                report["jobs"].append(summary)
                persist()
                require(job["status"] == "completed", "Generation did not complete: " + job["id"])
                require(len(job["presentation_ids"]) == 3, "Job did not produce all three variants")
                return template, job
            outcomes = await asyncio.gather(*(generate(t, j) for t, j in zip(templates, batch['jobs'])), return_exceptions=True)
            report["shared_generation_elapsed_seconds"] = round(time.monotonic() - started, 3)
            report["all_variants_ready_seconds"] = report["shared_generation_elapsed_seconds"] if all(
                j["status"] == "completed" for j in report["jobs"]) and len(report["jobs"]) == len(templates) else None
            report["within_five_minutes"] = (report["all_variants_ready_seconds"] <= 300
                if report["all_variants_ready_seconds"] is not None else False)
            report.update(response_summary([j["inference"] for j in report["jobs"]]))
            failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
            report["model_content_generation"] = bool(args.live and report["validated_model_calls"] and not failures)
            report["all_nine_ready_seconds"] = report["all_variants_ready_seconds"] if len(templates) == 3 else None
            persist()
            require(not failures, "One or more jobs failed required generation/model evidence checks")
            if args.live:
                report['editorial_sharing'] = verify_shared_jobs(report['jobs'], len(templates))
                require(report['within_five_minutes'], 'Generation exceeded the shared five-minute budget')
            groups = outcomes
            for template, job in groups:
                variants = []
                for identifier in job["presentation_ids"]:
                    record = (await req("GET", "/presentations/" + identifier)).json()
                    variants.append(record["variant"])
                    trace = validate_inference(record.get("generation", {}).get("inference"), live=args.live,
                        provider=args.provider if args.live else None, model=args.model if args.live else None)
                    require(trace == validate_inference(job["inference"], live=args.live,
                        provider=args.provider if args.live else None, model=args.model if args.live else None), "Variant inference differs from job")
                    require(record["generation"]["mode"] == ("llm" if args.live else "deterministic_analytics"), "Wrong generation mode")
                    require(not any(i["severity"] == "error" for i in record["audit"]["issues"]), "Presentation audit contains errors")
                    checks = verify_business(record, expected, settings) if expected else {}
                    if expected:
                        checks.update(verify_slide_evidence(record, live=args.live))
                    if not expected:
                        found = {result["dataset_ref"]["dataset_id"] for result in record["analysis_results"]}
                        require(expected_dataset_ids <= found, "A deck lost one of the seven datasets")
                        for result in record["analysis_results"]:
                            require(result == expected_contracts[result["dataset_ref"]["dataset_id"]],
                                    "Saved analysis differs from independent seven-type contract")
                        rendered = {item["dataset_id"] for item in record["analysis"] if any(
                            slide["content"].get("analysis_id") == item["analysis_id"] for slide in record["deck"]["slides"])}
                        require(expected_dataset_ids <= rendered, "A dataset exists in metadata but is absent from slide content")
                        checks["all_seven_datasets_in_this_deck"] = True
                    slides = [s["content"] for s in record["deck"]["slides"]]
                    saved = (await req("PATCH", "/presentations/" + identifier, json={
                        "revision": record["revision"], "title": record["title"], "variant": record["variant"], "slides": slides})).json()
                    reopened = (await req("GET", "/presentations/" + identifier)).json()
                    require(saved["revision"] == record["revision"] + 1 and reopened["deck"] == saved["deck"], "Save/reopen changed deck")
                    base = output / safe_name(template["name"] + "-" + record["variant"])
                    exports, durations = {}, {}
                    for fmt in ("pptx", "pdf"):
                        before = time.monotonic()
                        exports[fmt] = (await req("GET", f'/presentations/{identifier}/export/{fmt}?revision={saved["revision"]}')).content
                        durations[fmt + "_export_seconds"] = round(time.monotonic() - before, 3)
                        base.with_suffix("." + fmt).write_bytes(exports[fmt])
                    checks.update(verify_office_exports(exports["pptx"], exports["pdf"], reopened))
                    if expected:
                        require(checks["slides"] == 12 and checks["native_charts"] == 5 and checks["native_tables"] == 2, "Wrong business story structure")
                    comparisons = record.get("generation", {}).get("editorial", []) if args.live else []
                    item = {"template": template["name"], "variant": record["variant"], "id": identifier,
                            "job_id": job["id"], "revision": saved["revision"], "save_reopen_verified": True,
                            "audit": record["audit"]["counts"], **checks, **durations,
                            "pptx_file": str(base.with_suffix(".pptx")), "pdf_file": str(base.with_suffix(".pdf")),
                            "image_generation": record.get("image_generation"), "text_comparisons": comparisons[:4]}
                    report["runs"].append(item)
                    persist()
                    print(json.dumps({key: item[key] for key in ("template", "variant", "id", "slides")}, ensure_ascii=False), flush=True)
                require(sorted(variants) == ["classic", "focus", "split"], "Missing layout variant")
            report["pdf_export_total_seconds"] = round(sum(r["pdf_export_seconds"] for r in report["runs"]), 3)
            if args.images:
                require(all((run.get("image_generation") or {}).get("status") == "ready" for run in report["runs"]),
                        "Requested images were unavailable or incomplete; full image pipeline not proven")
                report["image_generation_included_in_ready_time"] = True
            report.update(status="passed", visual_review="pending: inspect four exported samples and slide contact sheets")
            persist()
            return report
        except Exception as exc:
            report.update(status="failed", error_type=type(exc).__name__)
            if isinstance(exc, EvidenceError):
                report["check_failure"] = str(exc)
            persist()
            raise


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--url", default="http://127.0.0.1:8036/api/v1")
    result.add_argument("--scenario", choices=["business", "seven-types"], default="business")
    result.add_argument("--live", action="store_true")
    result.add_argument("--images", action="store_true")
    result.add_argument("--version", choices=["baseline", "version-b"], default="baseline")
    result.add_argument("--period", choices=["default", "alternate"], default="default")
    result.add_argument("--one-template", action="store_true")
    result.add_argument("--template-id", action="append", default=[])
    result.add_argument("--label", default="parallel-business")
    result.add_argument("--output", type=Path)
    result.add_argument("--provider", default="vk")
    result.add_argument("--model", default="qwen38-27b-fp8")
    result.add_argument("--timeout", type=float, default=600)
    return result


if __name__ == "__main__":
    try:
        result = asyncio.run(run_scenario(parser().parse_args()))
        print(json.dumps({key: result[key] for key in ("status", "all_variants_ready_seconds", "within_five_minutes",
                                                      "validated_model_calls", "model_content_generation")}, ensure_ascii=False))
    except (ValueError, httpx.HTTPError) as exc:
        raise SystemExit("Acceptance failed (" + type(exc).__name__ + "); see sanitized report.json") from None
