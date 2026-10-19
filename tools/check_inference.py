"""Probe the actual selected transport, then optionally the full business service.

No secrets, headers or provider response bodies are printed. A profile/model name
alone never counts as a successful model request. Service mode generates the
12-slide business story and all three variants with actual per-job call evidence.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

import httpx
from fastapi import HTTPException

from acceptance_evidence import code_version, sanitized_inference, validate_inference
from check_parallel_generation import parser as parallel_parser, run_scenario

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def load_env(path):
    if path:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def validate_probe(value):
    if not isinstance(value, dict) or set(value) != {"ok"} or value["ok"] is not True:
        raise ValueError("Probe response failed its schema")
    return value


async def run(args):
    from designer.ai import complete_json
    from designer.inference import require_llm
    from designer.inference_trace import capture_inference
    settings = require_llm()
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {**code_version(ROOT), "status": "running", "profile": settings.profile,
              "model": settings.model, "json_mode": settings.json_mode, "probe_scope": "actual HTTP plus JSON schema"}
    trace = {}
    started = time.monotonic()
    try:
        with capture_inference() as trace:
            await complete_json([
                {"role": "system", "content": "Return only a JSON object."},
                {"role": "user", "content": 'Return {"ok": true}.'},
            ], validate=validate_probe, agent="acceptance_probe", attempts=args.attempts)
        report["inference"] = validate_inference(trace, live=True, variants=0,
                                                  provider=settings.profile, model=settings.model)
        report["probe_seconds"] = round(time.monotonic() - started, 3)
        if args.service:
            base = args.service.rstrip("/")
            if not base.endswith("/api/v1"):
                base += "/api/v1"
            service_args = parallel_parser().parse_args(["--url", base, "--live", "--one-template",
                "--template-id", args.template_id, "--provider", settings.profile, "--model", settings.model,
                "--label", "inference-service", "--output", str(output.parent / "service")])
            service = await run_scenario(service_args)
            report["generation"] = {key: service[key] for key in
                ("status", "validated_model_calls", "actual_attempts", "all_variants_ready_seconds", "jobs", "runs")}
        report["status"] = "passed"
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, inference=sanitized_inference(trace),
                      probe_seconds=round(time.monotonic() - started, 3))
        raise
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", help="Running service; creates real business content and three decks")
    parser.add_argument("--template-id")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--attempts", type=int, default=1, help="Probe retries (default one; full service has its own retry policy)")
    parser.add_argument("--output", type=Path, default=ROOT / "output/live-qwen/inference.json")
    args = parser.parse_args()
    if bool(args.service) != bool(args.template_id):
        parser.error("--service and --template-id must be supplied together")
    if args.attempts < 1:
        parser.error("--attempts must be positive")
    load_env(args.env_file)
    asyncio.run(run(args))


if __name__ == "__main__":
    try:
        main()
    except (httpx.HTTPError, HTTPException, ValueError) as exc:
        raise SystemExit("Inference check failed (" + type(exc).__name__ + "); see sanitized report") from None
