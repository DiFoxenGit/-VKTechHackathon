"""Probe the selected profile; optionally verify a running service's three decks.

Reads process environment, never prints keys or provider response bodies.
"""

import argparse
import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path

import httpx
from fastapi import HTTPException
from pptx import Presentation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from designer.generation import InvalidCompletion, ask, parse_json  # noqa: E402
from designer.inference import require_llm  # noqa: E402


def check_service(base, template_id, settings):
    headers = {"Authorization": "Bearer " + os.environ["DESIGNER_API_KEY"]} if os.getenv("DESIGNER_API_KEY") else {}
    with httpx.Client(base_url=base.rstrip("/"), headers=headers, timeout=30) as client:
        def call(method, path, **kwargs):
            response = client.request(method, "/api/v1" + path, **kwargs)
            response.raise_for_status()
            return response

        source = ROOT / "samples/source/материал-инициатива.md"
        pack = call("POST", "/content-packs", files={"file": (source.name, source.read_bytes(), "text/markdown")}).json()
        started = time.monotonic()
        job = call("POST", "/generations", json={
            "template_id": template_id, "brief": "Защита инициативы перед руководством: эффект пилота и решение о запуске на всю компанию.",
            "purpose": "initiative", "language": "ru", "slide_count": 12,
            "content_pack_ids": [pack["id"]],
        }).json()
        while True:
            if time.monotonic() - started >= 300:
                raise ValueError("Generation exceeded 300 seconds")
            state = call("GET", "/jobs/" + job["id"]).json()
            if state["status"] == "failed":
                raise ValueError("Generation failed; inspect the service job")
            if state["status"] == "completed":
                break
            time.sleep(2)
        elapsed = time.monotonic() - started
        if elapsed >= 300:
            raise ValueError("Generation exceeded 300 seconds")
        variants = []
        for identifier in state["presentation_ids"]:
            deck = call("GET", "/presentations/" + identifier).json()
            if deck["generation"].get("model") != settings.model or deck["generation"].get("provider") != settings.profile:
                raise ValueError("Service is using a different inference profile/model")
            count = len(deck["deck"]["slides"])
            if count != 12 or any(i["severity"] == "error" for i in deck["audit"]["issues"]):
                raise ValueError("Unexpected slide count or audit errors")
            pptx = call("GET", f"/presentations/{identifier}/export/pptx").content
            if len(Presentation(io.BytesIO(pptx)).slides) != count:
                raise ValueError("Exported PPTX slide count mismatch")
            variants.append(deck["variant"])
        if sorted(variants) != ["classic", "focus", "split"]:
            raise ValueError("Expected all three layout variants")
        return {"job_id": job["id"], "seconds": round(elapsed, 2), "variants": variants}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", help="Running designer service URL; creates a content pack and three decks")
    parser.add_argument("--template-id")
    args = parser.parse_args()
    if bool(args.service) != bool(args.template_id):
        parser.error("--service and --template-id must be supplied together")
    settings = require_llm()
    started = time.monotonic()
    answer = parse_json(asyncio.run(ask([
        {"role": "system", "content": "Return only a JSON object."},
        {"role": "user", "content": 'Return {"ok": true}.'},
    ])))
    if answer != {"ok": True}:
        raise ValueError("Probe response failed JSON validation")
    report = {"profile": settings.profile, "model": settings.model, "probe_seconds": round(time.monotonic() - started, 2)}
    if args.service:
        report["generation"] = check_service(args.service, args.template_id, settings)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"HTTP {exc.response.status_code}; check provider/service settings and quotas", file=sys.stderr)
        sys.exit(1)
    except (httpx.HTTPError, HTTPException, InvalidCompletion, ValueError) as exc:
        print(f"Inference check failed ({type(exc).__name__}); check settings and service job", file=sys.stderr)
        sys.exit(1)
