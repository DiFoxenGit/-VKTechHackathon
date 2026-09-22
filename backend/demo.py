"""Exercise the public API on all supplied templates with one shared outline."""

import argparse
import json
import os
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--templates", type=Path, default=Path("Датасет"))
    parser.add_argument(
        "--brief", type=Path, required=True, help="UTF-8 brief/content source"
    )
    parser.add_argument(
        "--outline",
        type=Path,
        help="Optional Outline JSON; without it the configured LLM runs once",
    )
    parser.add_argument("--output", type=Path, default=Path("demo-output"))
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=["pptx", "pdf", "html"],
        default=["pptx", "pdf", "html"],
    )
    args = parser.parse_args()
    headers = (
        {"Authorization": "Bearer " + os.environ["DESIGNER_API_KEY"]}
        if os.getenv("DESIGNER_API_KEY")
        else {}
    )
    with httpx.Client(base_url=args.url, headers=headers, timeout=240) as client:

        def check(response):
            response.raise_for_status()
            return response.json()

        brief = args.brief.read_text(encoding="utf-8")
        outline = (
            json.loads(args.outline.read_text())
            if args.outline
            else check(
                client.post(
                    "/api/v1/outlines", json={"brief": brief, "slide_count": 12}
                )
            )
        )
        manifest = []
        for path in sorted(args.templates.glob("*.pptx")):
            template = check(
                client.post(
                    "/api/v1/templates", files={"file": (path.name, path.read_bytes())}
                )
            )
            job = check(
                client.post(
                    "/api/v1/generations",
                    json={
                        "template_id": template["id"],
                        "brief": brief,
                        "slide_count": len(outline["slides"]),
                        "outline": outline,
                    },
                )
            )
            deadline = time.monotonic() + 360
            while job["status"] not in ("completed", "failed"):
                if time.monotonic() > deadline:
                    raise RuntimeError("Generation did not complete in 6 minutes")
                time.sleep(1)
                job = check(client.get("/api/v1/jobs/" + job["id"]))
            if job["status"] != "completed":
                raise RuntimeError(job.get("error", "Generation failed"))
            folder = args.output / path.stem
            folder.mkdir(parents=True, exist_ok=True)
            for identifier in job["presentation_ids"]:
                presentation = check(client.get("/api/v1/presentations/" + identifier))
                (folder / (presentation["variant"] + ".json")).write_text(
                    json.dumps(presentation, ensure_ascii=False, indent=2)
                )
                for fmt in args.formats:
                    response = client.get(presentation["exports"][fmt])
                    response.raise_for_status()
                    (folder / (presentation["variant"] + "." + fmt)).write_bytes(
                        response.content
                    )
                manifest.append(
                    {
                        "template": path.name,
                        "id": identifier,
                        "variant": presentation["variant"],
                        "revision": presentation["revision"],
                    }
                )
                print(path.name, presentation["variant"], "OK", flush=True)
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2)
        )


if __name__ == "__main__":
    main()
