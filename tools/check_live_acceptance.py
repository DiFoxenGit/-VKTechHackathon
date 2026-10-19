"""Run S8/S9 acceptance only after a single transport/service probe succeeds.

Creates 21 business decks across seven independent jobs, plus nine deterministic
seven-type decks. Baseline jobs use one shared timer. Never run automatically
against a provider that is unavailable or while diagnosing transport errors.
"""
import argparse
import asyncio
import json
from pathlib import Path

from acceptance_evidence import EvidenceError, code_version, require, verify_independent_jobs
from check_parallel_generation import ROOT, parser as scenario_parser, run_scenario


async def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    report = {**code_version(ROOT), "status": "running", "scope": "S8/S9 business Qwen plus deterministic seven types",
              "scenarios": [], "visual_review": "pending", "image_provider_included": args.images}
    def persist():
        (args.output / "acceptance-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    scenarios = [("baseline", []), ("version-b", ["--version", "version-b", "--one-template"]),
                 ("alternate-period", ["--period", "alternate", "--one-template"]),
                 ("repeat-1", ["--one-template"]), ("repeat-2", ["--one-template"]),
                 ("seven-types", ["--scenario", "seven-types"])]
    try:
        for label, extra in scenarios:
            params = ["--url", args.url, "--label", label, "--output", str(args.output / label)] + extra
            if label != "seven-types":
                params += ["--live"]
            if args.images:
                params += ["--images"]
            for identifier in args.template_id:
                params += ["--template-id", identifier]
            result = await run_scenario(scenario_parser().parse_args(params))
            report["scenarios"].append(result)
            persist()
        business = report["scenarios"][:-1]
        jobs = [job for scenario in business for job in scenario["jobs"]]
        report.update(verify_independent_jobs(jobs, expected_count=7))
        report["business_decks"] = sum(len(s["runs"]) for s in business)
        report["seven_type_decks"] = len(report["scenarios"][-1]["runs"])
        require(report["business_decks"] == 21 and report["seven_type_decks"] == 9, "Incomplete acceptance matrix")
        baseline = business[0]
        report["s9_all_nine_ready_seconds"] = baseline["all_nine_ready_seconds"]
        report["s9_within_five_minutes"] = baseline["within_five_minutes"]
        report["s9_pdf_export_seconds"] = baseline["pdf_export_total_seconds"]
        report["status"] = "automated_checks_passed"
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        if isinstance(exc, EvidenceError):
            report["check_failure"] = str(exc)
        raise
    finally:
        persist()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8036/api/v1")
    parser.add_argument("--output", type=Path, default=ROOT / "output/live-qwen/full-acceptance")
    parser.add_argument("--template-id", action="append", default=[])
    parser.add_argument("--images", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
        print(json.dumps({key: result[key] for key in ("status", "independent_business_jobs", "validated_model_calls",
            "business_decks", "seven_type_decks", "s9_all_nine_ready_seconds")}, ensure_ascii=False, indent=2))
    except Exception as exc:
        raise SystemExit("Acceptance failed (" + type(exc).__name__ + "); see acceptance-report.json") from None
